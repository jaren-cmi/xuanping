from collections.abc import Mapping
import math

from xuanping.models import DimensionScores, Product, SalesEstimate

DEFAULT_WEIGHTS = {
    "demand": 0.30,
    "competition": 0.20,
    "profit": 0.25,
    "opportunity": 0.15,
    "risk": 0.10,
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_product(
    product: Product,
    estimate: SalesEstimate,
    *,
    weights: Mapping[str, float] | None = None,
    acquisition_cost: float | None = None,
    default_cost_multiplier: float = 0.3,
) -> DimensionScores:
    """根据销量、评论壁垒、利润、改进机会和风险生成 0-100 分。"""
    weights = dict(weights or DEFAULT_WEIGHTS)
    total_weight = sum(weights.get(key, 0) for key in DEFAULT_WEIGHTS)
    if total_weight <= 0:
        raise ValueError("至少需要一个正数维度权重")

    demand_sales = _clamp(20 + 20 * math.log10(max(1, estimate.monthly_sales)))
    bsr_stability = float(product.metadata.get("bsr_stability", 50))
    trend = product.trends_slope or 0.0
    demand_trend = _clamp(50 + trend * 10)
    demand = _clamp(demand_sales * 0.55 + bsr_stability * 0.25 + demand_trend * 0.20)

    review_barrier = _clamp(100 - product.review_count / 50)
    rating_barrier = _clamp(100 - max(0, (product.rating or 0) - 3.5) * 30)
    concentration = _clamp(100 - (product.brand_share or 0) * 100)
    competition = _clamp(review_barrier * 0.5 + rating_barrier * 0.25 + concentration * 0.25)

    price = product.price or 0.0
    cost = acquisition_cost if acquisition_cost is not None else product.acquisition_cost
    cost = cost if cost is not None else price * default_cost_multiplier
    estimated_fba = min(price * 0.25, 3.5 + price * 0.08) if price > 0 else 0
    estimated_ad = price * 0.10
    profit_margin = (price - cost - estimated_fba - price * 0.15 - estimated_ad) / price if price else 0
    profit = _clamp(profit_margin * 250)

    rating_opportunity = (
        _clamp((4.3 - product.rating) * 80) if product.rating is not None else 30.0
    )
    low_review_share = sum(
        product.rating_distribution.get(str(star), 0) for star in (1, 2, 3)
    ) / max(1, sum(product.rating_distribution.values()))
    opportunity = _clamp(
        rating_opportunity * 0.6 + min(100, estimate.monthly_sales / 10) * 0.25
        + low_review_share * 100 * 0.15
    )

    risk_penalty = (
        35 * product.high_ip_risk
        + 20 * product.regulated
        + 15 * product.fragile
        + 15 * product.oversized
        + 15 * product.seasonal
    )
    risk = _clamp(100 - risk_penalty)
    dimensions = {
        "demand": demand,
        "competition": competition,
        "profit": profit,
        "opportunity": opportunity,
        "risk": risk,
    }
    total = sum(dimensions[key] * weights.get(key, 0) for key in dimensions) / total_weight
    details = {
        "estimated_sales": demand_sales,
        "bsr_stability": _clamp(bsr_stability),
        "trend": demand_trend,
        "review_barrier": review_barrier,
        "rating_barrier": rating_barrier,
        "brand_concentration": concentration,
        "profit_margin": _clamp(profit_margin * 100),
        "rating_opportunity": rating_opportunity,
        "low_star_share": low_review_share * 100,
        "risk_penalty": risk_penalty,
    }
    return DimensionScores(
        **dimensions,
        total=round(total, 2),
        details={key: round(value, 2) for key, value in details.items()},
    )
