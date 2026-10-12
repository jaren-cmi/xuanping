from collections.abc import Mapping
import math

from xuanping.analysis.fba_fees import commission_rate, estimate_fba_fee
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


def _weighted(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in values)
    return (
        sum(value * weight for value, weight in values) / total_weight
        if total_weight
        else None
    )


def score_product(
    product: Product,
    estimate: SalesEstimate,
    *,
    weights: Mapping[str, float] | None = None,
    acquisition_cost: float | None = None,
    default_cost_multiplier: float = 0.3,
) -> DimensionScores:
    """根据有效数据生成 0-100 分；缺失子项退出加权并动态归一化。"""
    weights = dict(weights or DEFAULT_WEIGHTS)
    skipped: list[str] = []

    demand_parts = [( _clamp(20 + 20 * math.log10(max(1, estimate.monthly_sales))), 0.7)]
    if product.trends_slope is not None:
        demand_parts.append((_clamp(50 + product.trends_slope * 10), 0.3))
    else:
        skipped.append("trend")
    demand = _weighted(demand_parts) or 0

    competition_parts: list[tuple[float, float]] = []
    if product.review_count > 0:
        competition_parts.append((_clamp(100 - product.review_count / 50), 0.5))
    else:
        skipped.append("review_barrier")
    if product.rating is not None:
        competition_parts.append(
            (_clamp(100 - max(0, product.rating - 3.5) * 30), 0.25)
        )
    else:
        skipped.append("rating_barrier")
    if product.brand_share is not None:
        competition_parts.append((_clamp(100 - product.brand_share * 100), 0.25))
    else:
        skipped.append("brand_concentration")
    competition = _weighted(competition_parts)

    price = product.price
    cost = acquisition_cost if acquisition_cost is not None else product.acquisition_cost
    cost_confidence = product.metadata.get("supplier_analysis", {}).get("confidence")
    cost_source = (
        f"1688_{cost_confidence}"
        if cost is not None and cost_confidence in {"high", "medium"} else "fallback"
    )
    fba_fee, fba_source = estimate_fba_fee(product)
    profit_margin = None
    profit = None
    if price is not None and price > 0:
        cost = cost if cost is not None else price * default_cost_multiplier
        profit_margin = (
            price - cost - fba_fee - price * commission_rate(product.category) - price * 0.10
        ) / price
        profit = _clamp(profit_margin * 250)
    else:
        skipped.append("profit_price")
    if fba_source == "conservative_fallback":
        skipped.append("fba_fee_dimensions")

    opportunity_parts: list[tuple[float, float]] = []
    if product.rating is not None:
        opportunity_parts.append((_clamp((4.3 - product.rating) * 80), 0.6))
    else:
        skipped.append("rating_opportunity")
    opportunity_parts.append((_clamp(estimate.monthly_sales / 10), 0.25))
    low_share = None
    if product.rating_distribution:
        count = sum(product.rating_distribution.values())
        if count > 0:
            low_share = sum(
                product.rating_distribution.get(str(star), 0) for star in (1, 2, 3)
            ) / count
            opportunity_parts.append((_clamp(low_share * 100), 0.15))
        else:
            skipped.append("low_star_share")
    else:
        low_share = None
        skipped.append("low_star_share")
    opportunity = _weighted(opportunity_parts)

    risk_flags = {
        "high_ip_risk": (product.high_ip_risk, 35),
        "regulated": (product.regulated, 20),
        "fragile": (product.fragile, 15),
        "oversized": (product.oversized, 15),
        "seasonal": (product.seasonal, 15),
    }
    risk_penalty = sum(
        penalty for value, penalty in risk_flags.values() if value is True
    )
    risk = _weighted([
        (100 - penalty if value else 100, 1)
        for value, penalty in risk_flags.values() if value is not None
    ])
    if risk is None:
        skipped.extend(f"risk_{name}" for name, (value, _) in risk_flags.items() if value is None)
    dimensions: dict[str, float | None] = {
        "demand": demand,
        "competition": competition,
        "profit": profit,
        "opportunity": opportunity,
        "risk": risk,
    }
    active = {
        key: value for key, value in dimensions.items()
        if value is not None and weights.get(key, 0) > 0
    }
    total_weight = sum(weights[key] for key in active)
    total = (
        sum(float(active[key]) * weights[key] for key in active) / total_weight
        if total_weight
        else 0
    )
    source_fields = (
        product.bsr is not None,
        product.price is not None,
        product.rating is not None,
        product.review_count > 0,
        bool(product.brand),
        product.brand_share is not None,
        bool(product.rating_distribution),
        product.trends_slope is not None,
        all(value is not None for value in (
            product.package_length_in, product.package_width_in,
            product.package_height_in, product.package_weight_lb
        )),
        product.acquisition_cost is not None,
        *(value is not None for value, _ in risk_flags.values()),
    )
    details = {
        "estimated_sales": _clamp(
            20 + 20 * math.log10(max(1, estimate.monthly_sales))
        ),
        "review_barrier": (
            _clamp(100 - product.review_count / 50) if product.review_count > 0 else None
        ),
        "rating_barrier": (
            _clamp(100 - max(0, product.rating - 3.5) * 30)
            if product.rating is not None else None
        ),
        "brand_concentration": (
            _clamp(100 - product.brand_share * 100)
            if product.brand_share is not None else None
        ),
        "profit_margin": _clamp(profit_margin * 100) if profit_margin is not None else None,
        "cost_source": cost_source,
        "fba_fee": fba_fee,
        "fba_fee_source": fba_source,
        "commission_rate": commission_rate(product.category),
        "rating_opportunity": (
            _clamp((4.3 - product.rating) * 80) if product.rating is not None else None
        ),
        "low_star_share": low_share * 100 if low_share is not None else None,
        "risk_penalty": risk_penalty,
        "skipped_subitems": skipped,
        "data_completeness": round(sum(source_fields) / len(source_fields), 2),
    }
    return DimensionScores(
        **{
            key: round(value, 2) if value is not None else None
            for key, value in dimensions.items()
        },
        total=round(total, 2),
        details={
            key: round(value, 2) if isinstance(value, float) else value
            for key, value in details.items()
        },
    )
