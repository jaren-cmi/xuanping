import csv
import logging
import uuid
from pathlib import Path
from typing import Any

from xuanping.analysis.bsr_sales import BSRSalesEstimator
from xuanping.analysis.pain_points import PainPointAnalyzer
from xuanping.analysis.sourcing import SourcingAnalyzer
from xuanping.analysis.scoring import score_product
from xuanping.collectors.bestsellers import BestsellersCollector
from xuanping.collectors.product import ProductCollector
from xuanping.collectors.reviews import ReviewsCollector
from xuanping.collectors.base import CaptchaDetected
from xuanping.collectors.supplier_1688 import Supplier1688Collector
from xuanping.collectors.trends import TrendsCollector
from xuanping.config import Settings, get_settings
from xuanping.models import Product, ReportProduct, TaskResult
from xuanping.storage import Storage

logger = logging.getLogger(__name__)


def _compute_brand_share(products: list[Product]) -> None:
    # 同一榜单内品牌集中度的代理指标，分母为实际参与评分的商品数（含未知品牌）。
    brand_counts: dict[str, int] = {}
    for product in products:
        if product.brand:
            brand = product.brand.casefold()
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
    for product in products:
        product.brand_share = (
            brand_counts[product.brand.casefold()] / len(products)
            if product.brand else None
        )


class Pipeline:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage: Storage | None = None,
        bestsellers: Any | None = None,
        products: Any | None = None,
        reviews: Any | None = None,
        trends: Any | None = None,
        pain_points: Any | None = None,
        supplier: Any | None = None,
        sourcing: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or Storage(self.settings.database_path)
        self.bestsellers = bestsellers or BestsellersCollector(self.settings)
        self.products = products or ProductCollector(self.settings)
        self.reviews = reviews or ReviewsCollector(self.settings)
        self.trends = trends or TrendsCollector()
        self.pain_points = pain_points or PainPointAnalyzer()
        self.supplier = supplier
        self.sourcing = sourcing
        if self.settings.enable_1688 and self.settings.llm_api_key and (
            self.supplier is None or self.sourcing is None
        ):
            from xuanping.llm.client import LLMClient

            llm = LLMClient(self.settings)
            self.supplier = self.supplier or Supplier1688Collector(self.settings)
            self.sourcing = self.sourcing or SourcingAnalyzer(
                llm, self.settings.cny_usd_rate
            )
        self.estimator = BSRSalesEstimator(self.storage)

    def collect(self, category: str, list_type: str = "bestsellers") -> tuple[str, list[Product]]:
        task_id = str(uuid.uuid4())
        results = self.bestsellers.collect(category, list_type)
        self.storage.save_task(
            task_id, category, "collected", {"list_type": list_type, "count": len(results)}
        )
        for product in results:
            self.storage.save_product(
                task_id, product.asin, product.model_dump(mode="json"), stage="collected"
            )
        return task_id, results

    def _captcha_result(self, task_id: str, category: str, errors: list[str]) -> TaskResult:
        result = TaskResult(
            task_id=task_id, category=category, status="captcha_detected", errors=errors
        )
        self.storage.save_task(task_id, category, result.status, result.model_dump(mode="json"))
        return result

    def run(
        self,
        category: str,
        top: int = 20,
        list_type: str = "bestsellers",
        task_id: str | None = None,
        resume: bool = True,
        force: bool = False,
    ) -> TaskResult:
        """分阶段保存进度；task_id 可用于断点续跑已有分析。"""
        task_id = task_id or str(uuid.uuid4())
        errors: list[str] = []
        records = self.storage.list_product_records(task_id)
        stages = {record["product"]["asin"]: record["stage"] for record in records}
        if self.storage.get_task(task_id):
            candidates = [Product.model_validate(record["product"]) for record in records]
        else:
            candidates = []
        if not candidates:
            try:
                print("采集榜单...")
                candidates = self.bestsellers.collect(category, list_type)
            except Exception as error:
                if isinstance(error, CaptchaDetected):
                    message = f"CAPTCHA 告警：{error}"
                    logger.error(message)
                    errors.append(message)
                    return self._captcha_result(task_id, category, errors)
                message = f"榜单采集失败: {error}"
                logger.exception(message)
                errors.append(message)
        if not self.storage.get_task(task_id):
            self.storage.save_task(task_id, category, "collecting", {})
        analyzed: list[ReportProduct] = []
        product_records: dict[str, tuple[Product, str]] = {}
        for index, candidate in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] 分析 {candidate.asin}")
            stage = stages.get(candidate.asin, "collected")
            if force or not resume:
                stage = "collected"
            try:
                if stage not in {"detailed", "scored", "pain_analyzed"}:
                    product = self.products.collect(candidate.asin, category)
                    product.rank = candidate.rank
                    if not product.title:
                        product.title = candidate.title
                    if product.bsr is None:
                        product.bsr = candidate.bsr
                    if not product.brand:
                        product.brand = candidate.brand
                    if product.bsr is None:
                        raise ValueError("商品详情页没有可用 BSR")
                    self.storage.save_product(
                        task_id, product.asin, product.model_dump(mode="json"), stage="detailed"
                    )
                    stage = "detailed"
                else:
                    product = candidate
            except Exception as error:
                if isinstance(error, CaptchaDetected):
                    message = f"CAPTCHA 告警：{error}"
                    logger.error(message)
                    errors.append(message)
                    return self._captcha_result(task_id, category, errors)
                logger.warning("商品 %s 详情采集失败，使用榜单信息: %s", candidate.asin, error)
                errors.append(f"{candidate.asin} 商品详情: {error}")
                product = candidate
            if product.bsr is None:
                errors.append(f"{candidate.asin} 缺少 BSR，跳过销量和评分")
                continue
            product_records[product.asin] = (product, stage)

        _compute_brand_share([product for product, _ in product_records.values()])
        for product, stage in product_records.values():
            if force:
                product.metadata.pop("supplier_analysis", None)
                product.acquisition_cost = None
            if self.sourcing and self.supplier and not product.metadata.get("supplier_analysis"):
                try:
                    terms = self.sourcing.search_terms(product.title)
                    offers = self.supplier.collect(
                        terms, self.settings.supplier_1688_candidates
                    )
                    sourcing = self.sourcing.match(product, offers)
                    product.metadata["supplier_analysis"] = sourcing
                    if sourcing["confidence"] != "low" and sourcing["cost_min_usd"] is not None:
                        product.acquisition_cost = (
                            sourcing["cost_min_usd"] + sourcing["cost_max_usd"]
                        ) / 2
                except CaptchaDetected as error:
                    message = f"CAPTCHA 告警：{error}"
                    logger.error(message)
                    errors.append(message)
                    break
                except Exception as error:
                    logger.warning("商品 %s 1688 比价失败: %s", product.asin, error)
                    errors.append(f"{product.asin} 1688 比价: {error}")
            self.storage.save_product(
                task_id, product.asin, product.model_dump(mode="json"), stage=stage
            )

        if any(error.startswith("CAPTCHA 告警") for error in errors):
            return self._captcha_result(task_id, category, errors)
        estimates = {
            asin: self.estimator.estimate(product.bsr, category)
            for asin, (product, _) in product_records.items()
        }
        preliminary_scores = {
            asin: score_product(
                product, estimates[asin], weights=self.settings.score_weights,
                default_cost_multiplier=self.settings.default_cost_multiplier,
            )
            for asin, (product, _) in product_records.items()
        }
        trend_candidates = [
            asin for asin, (_, stage) in sorted(
                product_records.items(),
                key=lambda item: preliminary_scores[item[0]].total,
                reverse=True,
            )
            if stage not in {"scored", "pain_analyzed"}
        ][: self.settings.trends_top_n]
        trend_keywords = {
            asin: " ".join(product_records[asin][0].title.split()[:5])
            for asin in trend_candidates if product_records[asin][0].title
        }
        try:
            if trend_keywords and hasattr(self.trends, "collect_many"):
                trend_results = self.trends.collect_many(list(trend_keywords.values()))
            else:
                trend_results = {
                    keyword: self.trends.collect(keyword)
                    for keyword in trend_keywords.values()
                }
            for asin, keyword in trend_keywords.items():
                trend_result = trend_results.get(keyword, {})
                if trend_result.get("available", bool(trend_result)):
                    product = product_records[asin][0]
                    product.trends_slope = float(trend_result.get("slope", 0))
                    product.trend_seasonality = float(trend_result.get("seasonality", 0))
                    product.metadata["trend_regions"] = trend_result.get("regions", {})
                else:
                    product_records[asin][0].metadata["trends_unavailable"] = True
        except Exception as error:
            logger.warning("Google Trends 批量验证失败: %s", error)
            errors.append(f"Google Trends 数据不可用: {error}")

        for asin, (product, stage) in product_records.items():
            estimate = estimates[asin]
            scores = score_product(
                product, estimate, weights=self.settings.score_weights,
                default_cost_multiplier=self.settings.default_cost_multiplier,
            )
            pain_points = []
            if stage in {"scored", "pain_analyzed"} and resume and not force:
                saved_estimate = product.metadata.get("pipeline_estimate")
                if saved_estimate:
                    from xuanping.models import SalesEstimate

                    estimate = SalesEstimate.model_validate(saved_estimate)
                    scores = score_product(
                        product, estimate, weights=self.settings.score_weights,
                        default_cost_multiplier=self.settings.default_cost_multiplier,
                    )
                if stage == "pain_analyzed":
                    from xuanping.models import PainPoint

                    pain_points = [
                        PainPoint.model_validate(point)
                        for point in product.metadata.get("pipeline_pain_points", [])
                    ]
            product.metadata["pipeline_scores"] = scores.model_dump(mode="json")
            product.metadata["pipeline_estimate"] = estimate.model_dump(mode="json")
            self.storage.save_product(
                task_id, asin, product.model_dump(mode="json"),
                stage=stage if stage in {"scored", "pain_analyzed"} and resume and not force
                else "scored",
            )
            analyzed.append(ReportProduct(
                product=product, estimate=estimate, scores=scores,
                pain_points=pain_points,
                supplier_matches=product.metadata.get("supplier_analysis", {}).get("matches", []),
            ))
        analyzed.sort(key=lambda item: item.scores.total, reverse=True)
        for item in analyzed[: max(0, top)]:
            current_stage = stages.get(item.product.asin, "detailed")
            if current_stage == "pain_analyzed" and resume and not force:
                continue
            try:
                print(f"分析差评：{item.product.asin}")
                item.product.low_star_reviews = self.reviews.collect_low_star(
                    item.product.asin, self.settings.review_limit
                )
                item.pain_points = self.pain_points.analyze(item.product.low_star_reviews)
                item.product.metadata["pipeline_pain_points"] = [
                    point.model_dump(mode="json") for point in item.pain_points
                ]
                self.storage.save_product(
                    task_id, item.product.asin, item.product.model_dump(mode="json"),
                    stage="pain_analyzed",
                )
            except Exception as error:
                if isinstance(error, CaptchaDetected):
                    message = f"CAPTCHA 告警：{error}"
                    logger.error(message)
                    errors.append(message)
                    break
                logger.warning("商品 %s 差评分析失败: %s", item.product.asin, error)
                errors.append(f"{item.product.asin} 差评分析: {error}")
        result = TaskResult(
            task_id=task_id,
            category=category,
            status=("captcha_detected" if any("CAPTCHA 告警" in e for e in errors)
                    else "completed" if not errors else "completed_with_errors"),
            products=analyzed,
            errors=errors,
        )
        for item in analyzed:
            if not any(record["product"]["asin"] == item.product.asin for record in records):
                self.storage.save_product(
                    task_id, item.product.asin, item.product.model_dump(mode="json"),
                    stage="pain_analyzed" if item.pain_points else "scored",
                )
        self.storage.save_task(
            task_id, category, result.status, result.model_dump(mode="json")
        )
        return result


def _format_dimension(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "N/A"


def render_report(result: TaskResult, output_format: str = "md") -> str:
    if output_format == "json":
        return result.model_dump_json(indent=2)
    if output_format == "csv":
        from io import StringIO

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["ASIN", "标题", "售价", "估算月销", "需求", "竞争", "利润", "机会", "风险", "总分"]
        )
        for item in result.products:
            product, score = item.product, item.scores
            writer.writerow(
                [
                    product.asin,
                    product.title,
                    product.price,
                    item.estimate.monthly_sales,
                    score.demand if score.demand is not None else "N/A",
                    score.competition if score.competition is not None else "N/A",
                    score.profit if score.profit is not None else "N/A",
                    score.opportunity if score.opportunity is not None else "N/A",
                    score.risk if score.risk is not None else "N/A",
                    score.total,
                ]
            )
        return buffer.getvalue()
    if output_format != "md":
        raise ValueError("报告格式必须为 md、csv 或 json")
    lines = [
        f"# 亚马逊选品报告：{result.category}",
        "",
        f"- 任务 ID：`{result.task_id}`",
        f"- 任务状态：{result.status}",
        "",
    ]
    if result.status == "captcha_detected":
        lines.extend(["## 采集告警", "", "- 检测到 CAPTCHA，已立即中止本轮采集；请勿自动重试。", ""])
    lines.extend([
        "## 候选商品",
        "",
        "| ASIN | 标题 | 售价 | 估算月销（区间） | 需求 | 竞争 | 利润 | 机会 | 风险 | 总分 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for item in result.products:
        product, score, estimate = item.product, item.scores, item.estimate
        warning = " ⚠️" if score.details.get("data_completeness", 1) < 0.6 else ""
        interval = f"{estimate.monthly_sales:.0f}（{estimate.lower_bound:.0f}-{estimate.upper_bound:.0f}）"
        lines.append(
            f"| {product.asin}{warning} | {product.title.replace('|', ' ')} | "
            f"{product.price or '未知'} | {interval} / {estimate.confidence} | "
            f"{_format_dimension(score.demand)} | {_format_dimension(score.competition)} | "
            f"{_format_dimension(score.profit)} | {_format_dimension(score.opportunity)} | "
            f"{_format_dimension(score.risk)} | {score.total:.1f} |"
        )
    lines.extend(["", "## Top 3 深度分析", ""])
    for index, item in enumerate(result.products[:3], start=1):
        lines.extend([f"### {index}. {item.product.title or item.product.asin}", ""])
        lines.append(f"- 评分明细：{item.scores.model_dump_json()}")
        lines.append(
            f"- 数据完整度：{item.scores.details.get('data_completeness', 0):.0%}"
        )
        if item.product.metadata.get("trends_unavailable"):
            lines.append("- Google Trends：趋势数据不可用，已跳过该子项。")
        if item.pain_points:
            lines.append("- 用户痛点与改进建议：")
            lines.extend(
                f"  - **{point.issue}**（{point.frequency} 次）：{point.recommendation}"
                for point in item.pain_points
            )
        else:
            lines.append("- 未发现可用的评论痛点数据。")
        lines.append("")
    lines.extend(["## 供应链比价", ""])
    sourced = [item for item in result.products if item.supplier_matches]
    if not sourced:
        lines.append("本次未获得可用的 1688 匹配结果。")
    for item in sourced:
        product = item.product
        sourcing = product.metadata.get("supplier_analysis", {})
        lines.append(
            f"### {product.asin}：{product.title or product.asin} "
            f"（置信度：{sourcing.get('confidence', 'low')}）"
        )
        for match in item.supplier_matches:
            low = match.get("price_min_cny", "?")
            high = match.get("price_max_cny", "?")
            margin = ""
            if product.price and sourcing.get("cost_min_usd") is not None:
                cost_low = sourcing["cost_min_usd"]
                cost_high = sourcing["cost_max_usd"]
                margin = (
                    f" | 推算毛利率 {((product.price - cost_high) / product.price) * 100:.1f}%"
                    f"–{((product.price - cost_low) / product.price) * 100:.1f}%"
                )
            url = match.get("url", "")
            title = match.get("title", "未知商品").replace("|", " ")
            supplier = match.get("supplier") or "未知供应商"
            link = f"[{title}]({url})" if url else title
            lines.append(
                f"- {link} | ¥{low}–¥{high} | MOQ {match.get('moq', '未知')}"
                f" | 成交量 {match.get('transactions', '未知')} | {supplier}"
                f" | 匹配分 {match.get('match_score', 0):.0f}{margin}"
            )
        lines.append("")
    lines.extend(["## 风险提示", ""])
    if result.errors:
        lines.extend(f"- {error}" for error in result.errors)
    for item in result.products:
        product = item.product
        flags = [
            name
            for flag, name in (
                (product.high_ip_risk, "侵权风险类目"),
                (product.regulated, "可能需要认证"),
                (product.fragile, "易碎商品"),
                (product.oversized, "超大件"),
                (product.seasonal, "季节性商品"),
            )
            if flag
        ]
        if flags:
            lines.append(f"- {product.asin}：{'、'.join(flags)}")
    if not result.errors and not any(
        item.product.high_ip_risk or item.product.regulated
        or item.product.fragile or item.product.oversized or item.product.seasonal
        for item in result.products
    ):
        lines.append("- 本次未检测到已标注风险；采集和估算数据不保证完整或准确。")
    return "\n".join(lines) + "\n"


def export_report(storage: Storage, task_id: str, output_format: str, output: str | None = None) -> str:
    task = storage.get_task(task_id)
    if task is None:
        raise ValueError(f"未找到任务：{task_id}")
    result = TaskResult.model_validate(task["result"])
    content = render_report(result, output_format)
    if output:
        Path(output).write_text(content, encoding="utf-8")
    return content


def load_calibration_csv(path: str) -> tuple[str, list[dict[str, float]]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"bsr", "monthly_sales"}.issubset(reader.fieldnames):
            raise ValueError("CSV 必须包含 bsr 和 monthly_sales 列")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV 中没有校准样本")
    categories = {row.get("category", "default") or "default" for row in rows}
    if len(categories) != 1:
        raise ValueError("每次校准的 CSV 只能包含一个 category")
    samples = [{"bsr": int(row["bsr"]), "monthly_sales": float(row["monthly_sales"])} for row in rows]
    return categories.pop(), samples
