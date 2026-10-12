import csv
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from xuanping.analysis.bsr_sales import BSRSalesEstimator
from xuanping.analysis.pain_points import PainPointAnalyzer
from xuanping.analysis.scoring import score_product
from xuanping.collectors.bestsellers import BestsellersCollector
from xuanping.collectors.product import ProductCollector
from xuanping.collectors.reviews import ReviewsCollector
from xuanping.collectors.trends import TrendsCollector
from xuanping.config import Settings, get_settings
from xuanping.models import Product, ReportProduct, TaskResult
from xuanping.storage import Storage

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or Storage(self.settings.database_path)
        self.bestsellers = bestsellers or BestsellersCollector(self.settings)
        self.products = products or ProductCollector(self.settings)
        self.reviews = reviews or ReviewsCollector(self.settings)
        self.trends = trends or TrendsCollector()
        self.pain_points = pain_points or PainPointAnalyzer()
        self.estimator = BSRSalesEstimator(self.storage)

    def collect(self, category: str, list_type: str = "bestsellers") -> tuple[str, list[Product]]:
        task_id = str(uuid.uuid4())
        results = self.bestsellers.collect(category, list_type)
        self.storage.save_task(
            task_id, category, "collected", {"list_type": list_type, "count": len(results)}
        )
        for product in results:
            self.storage.save_product(task_id, product.asin, product.model_dump(mode="json"))
        return task_id, results

    def run(
        self,
        category: str,
        top: int = 20,
        list_type: str = "bestsellers",
        task_id: str | None = None,
    ) -> TaskResult:
        """逐商品容错执行分析；task_id 可用于接续 collect 命令保存的榜单。"""
        task_id = task_id or str(uuid.uuid4())
        errors: list[str] = []
        if task_id and self.storage.get_task(task_id):
            saved = self.storage.list_products(task_id)
            candidates = [Product.model_validate(item) for item in saved]
        else:
            candidates = []
        if not candidates:
            try:
                candidates = self.bestsellers.collect(category, list_type)
            except Exception as error:
                message = f"榜单采集失败: {error}"
                logger.exception(message)
                errors.append(message)
        analyzed: list[ReportProduct] = []
        for index, candidate in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] 分析 {candidate.asin}")
            try:
                product = self.products.collect(candidate.asin, category)
                product.rank = candidate.rank
                if not product.title:
                    product.title = candidate.title
                if product.bsr is None:
                    product.bsr = candidate.bsr
                if product.bsr is None:
                    raise ValueError("商品详情页没有可用 BSR")
            except Exception as error:
                logger.warning("商品 %s 详情采集失败，使用榜单信息: %s", candidate.asin, error)
                errors.append(f"{candidate.asin} 商品详情: {error}")
                product = candidate
            if product.bsr is None:
                errors.append(f"{candidate.asin} 缺少 BSR，跳过销量和评分")
                continue
            try:
                if product.title:
                    keyword = " ".join(product.title.split()[:5])
                    trend_result = self.trends.collect(keyword)
                    product.trends_slope = float(trend_result.get("slope", 0))
                    product.trend_seasonality = float(trend_result.get("seasonality", 0))
            except Exception as error:
                logger.warning("商品 %s 趋势验证失败: %s", product.asin, error)
                errors.append(f"{product.asin} Google Trends: {error}")
            estimate = self.estimator.estimate(product.bsr, category)
            scores = score_product(product, estimate)
            analyzed.append(ReportProduct(product=product, estimate=estimate, scores=scores))
            self.storage.save_product(task_id, product.asin, product.model_dump(mode="json"))
        analyzed.sort(key=lambda item: item.scores.total, reverse=True)
        for item in analyzed[: max(0, top)]:
            try:
                item.product.low_star_reviews = self.reviews.collect_low_star(
                    item.product.asin, self.settings.review_limit
                )
                item.pain_points = self.pain_points.analyze(item.product.low_star_reviews)
            except Exception as error:
                logger.warning("商品 %s 差评分析失败: %s", item.product.asin, error)
                errors.append(f"{item.product.asin} 差评分析: {error}")
        result = TaskResult(
            task_id=task_id,
            category=category,
            status="completed" if not errors else "completed_with_errors",
            products=analyzed,
            errors=errors,
        )
        for item in analyzed:
            self.storage.save_product(
                task_id, item.product.asin, item.model_dump(mode="json")
            )
        self.storage.save_task(
            task_id, category, result.status, result.model_dump(mode="json")
        )
        return result


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
                    score.demand,
                    score.competition,
                    score.profit,
                    score.opportunity,
                    score.risk,
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
        "## 候选商品",
        "",
        "| ASIN | 标题 | 售价 | 估算月销（区间） | 需求 | 竞争 | 利润 | 机会 | 风险 | 总分 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result.products:
        product, score, estimate = item.product, item.scores, item.estimate
        interval = f"{estimate.monthly_sales:.0f}（{estimate.lower_bound:.0f}-{estimate.upper_bound:.0f}）"
        lines.append(
            f"| {product.asin} | {product.title.replace('|', ' ')} | "
            f"{product.price or '未知'} | {interval} / {estimate.confidence} | "
            f"{score.demand:.1f} | {score.competition:.1f} | {score.profit:.1f} | "
            f"{score.opportunity:.1f} | {score.risk:.1f} | {score.total:.1f} |"
        )
    lines.extend(["", "## Top 3 深度分析", ""])
    for index, item in enumerate(result.products[:3], start=1):
        lines.extend([f"### {index}. {item.product.title or item.product.asin}", ""])
        lines.append(f"- 评分明细：{item.scores.model_dump_json()}")
        if item.pain_points:
            lines.append("- 用户痛点与改进建议：")
            lines.extend(
                f"  - **{point.issue}**（{point.frequency} 次）：{point.recommendation}"
                for point in item.pain_points
            )
        else:
            lines.append("- 未发现可用的评论痛点数据。")
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
