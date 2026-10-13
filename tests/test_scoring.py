import pytest

from xuanping.analysis.scoring import score_product
from xuanping.models import Product, SalesEstimate


def estimate(sales):
    return SalesEstimate(
        monthly_sales=sales,
        lower_bound=sales * 0.5,
        upper_bound=sales * 1.5,
        confidence="low",
        category="home",
    )


def test_scores_are_bounded_and_detail_each_dimension():
    product = Product(
        asin="B000000001",
        price=30,
        rating=4.0,
        review_count=500,
        rating_distribution={"1": 10, "2": 20, "3": 30, "4": 100, "5": 50},
        trends_slope=1,
    )

    scores = score_product(product, estimate(500))

    assert 0 <= scores.total <= 100
    assert set(scores.model_dump()) >= {
        "demand",
        "competition",
        "profit",
        "opportunity",
        "risk",
        "total",
        "details",
    }
    assert scores.details["low_star_share"] > 0


def test_product_risk_flags_reduce_risk_score():
    baseline = Product(
        asin="B000000001", price=20, high_ip_risk=False, regulated=False,
        fragile=False, oversized=False, seasonal=False,
    )
    risky = Product(
        asin="B000000002",
        price=20,
        high_ip_risk=True,
        regulated=True,
        fragile=True,
        oversized=True,
        seasonal=True,
    )
    assert score_product(risky, estimate(100)).risk < score_product(
        baseline, estimate(100)
    ).risk


def test_missing_dimensions_are_none_and_excluded_from_total():
    scores = score_product(Product(asin="B000000001"), estimate(100))
    assert scores.competition is None
    assert scores.profit is None
    assert scores.risk is None
    assert scores.total == round(
        (scores.demand * 0.30 + scores.opportunity * 0.15) / 0.45, 2
    )


@pytest.mark.parametrize(
    ("product_cost", "confidence", "override_cost", "source"),
    [
        (None, None, None, "fallback"),
        (20, None, None, "provided"),
        (20, None, 0, "provided"),
        (5, "high", None, "1688_high"),
        (5, "medium", None, "1688_medium"),
        (5, "high", 20, "provided"),
    ],
)
def test_cost_source_identifies_the_cost_actually_used(
    product_cost, confidence, override_cost, source,
):
    product = Product(
        asin="B000000001", price=30, acquisition_cost=product_cost,
        metadata={"supplier_analysis": {"confidence": confidence}},
    )
    scores = score_product(product, estimate(100), acquisition_cost=override_cost)
    assert scores.details["cost_source"] == source
    used_cost = override_cost if override_cost is not None else product_cost
    expected_margin = (
        30 - (used_cost if used_cost is not None else 9) - 5.5 - 30 * 0.15 - 30 * 0.10
    ) / 30
    assert scores.profit == round(max(0, min(100, expected_margin * 250)), 2)
