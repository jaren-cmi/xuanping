from collections.abc import Mapping
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
                {"role": "user", "content": f'{{"title": {title!r}}}'},
            ]
        )
        terms = result.get("keywords", "") if isinstance(result, Mapping) else ""
        return str(terms).strip() or title

    def match(self, product: Product, offers: list[dict[str, Any]]) -> dict[str, Any]:
        if not offers:
            return {"matches": [], "confidence": "low", "cost_min_usd": None, "cost_max_usd": None}
        result = self.llm.complete_json(
            [
                {"role": "system", "content": (
                    "比较Amazon商品与1688商品的实际用途、材质、结构和规格，"
                    "为每个候选输出0-100相似度。仅输出JSON："
                    '{"matches":[{"index":0,"score":0}]}'
                )},
                {"role": "user", "content": str({
                    "amazon": {"title": product.title, "bullets": product.bullets},
                    "offers": [{"title": offer.get("title"), "index": index}
                               for index, offer in enumerate(offers)],
                })},
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
        prices = [
            (float(match["price_min_cny"]), float(match["price_max_cny"]))
            for match in matches if match.get("price_min_cny") and match.get("price_max_cny")
        ]
        scores_top = [match["match_score"] for match in matches]
        spread = (
            (max((low + high) / 2 for low, high in prices)
             - min((low + high) / 2 for low, high in prices))
            / max(1, sum((low + high) / 2 for low, high in prices) / len(prices))
            if len(prices) > 1 else 1
        )
        confidence = (
            "high" if len(prices) >= 2 and min(scores_top) >= 80 and spread <= 0.30
            else "medium" if len(prices) >= 2 and min(scores_top) >= 65
            else "low"
        )
        return {
            "matches": matches,
            "confidence": confidence,
            "cost_min_cny": min((low for low, _ in prices), default=None),
            "cost_max_cny": max((high for _, high in prices), default=None),
            "cost_min_usd": min((low for low, _ in prices), default=None) / self.cny_usd_rate if prices else None,
            "cost_max_usd": max((high for _, high in prices), default=None) / self.cny_usd_rate if prices else None,
        }
