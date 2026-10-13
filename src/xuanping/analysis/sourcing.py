from collections.abc import Mapping
import json
import math
from typing import Any

from xuanping.llm.client import LLMClient
from xuanping.models import Product


class SourcingAnalyzer:
    def __init__(self, llm: Any | None = None, cny_usd_rate: float = 7.2) -> None:
        self.llm = llm or LLMClient()
        self.cny_usd_rate = cny_usd_rate

    def search_terms(self, title: str) -> str:
        result = self.llm.complete_json(
            [
                {"role": "system", "content": "将商品英文标题提炼成适合1688搜索的简短中文词组，只输出JSON。"},
                {"role": "user", "content": json.dumps({"title": title}, ensure_ascii=False)},
            ]
        )
        terms = result.get("keywords", "") if isinstance(result, Mapping) else ""
        return str(terms).strip() or title

    def match(self, product: Product, offers: list[dict[str, Any]]) -> dict[str, Any]:
        if not offers:
            return {
                "matches": [], "confidence": "low", "spread": None,
                "cost_min_cny": None, "cost_max_cny": None,
                "cost_min_usd": None, "cost_max_usd": None,
            }
        result = self.llm.complete_json(
            [
                {"role": "system", "content": (
                    "比较Amazon商品与1688商品的实际用途、材质、结构和规格，"
                    "为每个候选输出0-100相似度。仅输出JSON："
                    '{"matches":[{"index":0,"score":0}]}'
                )},
                {"role": "user", "content": json.dumps({
                    "amazon": {"title": product.title, "bullets": product.bullets},
                    "offers": [{"title": offer.get("title"), "index": index}
                               for index, offer in enumerate(offers)],
                }, ensure_ascii=False)},
            ]
        )
        scores = {}
        if isinstance(result, Mapping):
            scores = {
                int(entry["index"]): float(entry["score"])
                for entry in result.get("matches", [])
                if isinstance(entry, Mapping) and "index" in entry and "score" in entry
                and 0 <= int(entry["index"]) < len(offers)
            }
        matches = [
            {**offers[index], "match_score": score}
            for index, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ][:3]
        prices = []
        scores_top = []
        for match in matches:
            if match.get("price_min_cny") is None or match.get("price_max_cny") is None:
                continue
            low, high = float(match["price_min_cny"]), float(match["price_max_cny"])
            if math.isfinite(low) and math.isfinite(high) and 0 < low <= high:
                prices.append((low, high))
                scores_top.append(match["match_score"])
        # 单报价无法衡量跨供应商价格离散度，记为不适用而非最差。
        spread = (
            (max(high for _, high in prices) - min(low for low, _ in prices))
            / (sum((low + high) / 2 for low, high in prices) / len(prices))
            if len(prices) > 1 else None
        )
        confidence = (
            "high" if len(prices) >= 2 and min(scores_top) >= 80 and spread <= 0.30
            else "medium" if (
                len(prices) == 1 and scores_top[0] >= 85
                or len(prices) >= 2 and min(scores_top) >= 65 and spread <= 0.50
            )
            else "low"
        )
        return {
            "matches": matches,
            "confidence": confidence,
            "spread": spread,
            "cost_min_cny": min((low for low, _ in prices), default=None),
            "cost_max_cny": max((high for _, high in prices), default=None),
            "cost_min_usd": min((low for low, _ in prices), default=None) / self.cny_usd_rate if prices else None,
            "cost_max_usd": max((high for _, high in prices), default=None) / self.cny_usd_rate if prices else None,
        }
