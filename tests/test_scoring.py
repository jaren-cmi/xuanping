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
