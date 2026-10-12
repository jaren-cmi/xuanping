import pytest

from xuanping.analysis.bsr_sales import BSRSalesEstimator
from xuanping.storage import Storage


def test_estimate_has_uncertainty_and_sales_fall_with_bsr():
    estimator = BSRSalesEstimator()
    strong_rank = estimator.estimate(100, "home")
    weak_rank = estimator.estimate(1000, "home")

    assert strong_rank.monthly_sales > weak_rank.monthly_sales
    assert strong_rank.lower_bound < strong_rank.monthly_sales < strong_rank.upper_bound
    assert strong_rank.confidence == "low"


def test_calibration_fits_power_curve_and_persists(tmp_path):
    storage = Storage(tmp_path / "calibration.db")
    estimator = BSRSalesEstimator(storage)

    a, b = estimator.calibrate(
        [(100, 100), (1000, 10), (10000, 1)],
        "test-category",
    )

    assert a == pytest.approx(10_000)
    assert b == pytest.approx(1)
    assert storage.get_calibration("test-category") == pytest.approx((a, b, 3))
    assert estimator.estimate(100, "test-category").confidence == "low"


def test_calibration_requires_two_distinct_bsr_samples():
    with pytest.raises(ValueError):
        BSRSalesEstimator().calibrate([(100, 10)], "home")
    with pytest.raises(ValueError):
        BSRSalesEstimator().calibrate([(100, 10), (100, 20)], "home")
