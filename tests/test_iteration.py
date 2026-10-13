import pandas as pd
import pytest
import httpx

from xuanping.analysis.fba_fees import estimate_fba_fee
from xuanping.analysis.scoring import score_product
from xuanping.analysis.sourcing import SourcingAnalyzer
from xuanping.collectors.base import BaseCollector, CaptchaDetected
from xuanping.collectors.proxy_pool import ProxyPool
from xuanping.collectors.product import ProductCollector
from xuanping.collectors.trends import TrendsCollector
from xuanping.config import Settings
from xuanping.models import Product, SalesEstimate
from xuanping.pipeline import Pipeline
from xuanping.storage import Storage


class FakeResponse:
    status_code = 200
    url = "https://www.amazon.com/dp/example"

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_captcha_response_aborts_collector_without_retry():
    collector = BaseCollector(
        Settings(request_delay_min=0, request_delay_max=0),
        client=FakeHttp(FakeResponse("Enter the characters you see below")),
        sleep=lambda _: None,
    )

    with pytest.raises(CaptchaDetected):
        collector.get("https://example.test")


def test_collector_does_not_retry_rate_limit_responses():
    class RateLimitedResponse(FakeResponse):
        status_code = 429

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(429),
            )

    client = FakeHttp(RateLimitedResponse("Too Many Requests"))
    collector = BaseCollector(
        Settings(request_delay_min=0, request_delay_max=0),
        client=client,
        sleep=lambda _: None,
    )
    with pytest.raises(httpx.HTTPStatusError):
        collector.get("https://example.test")
    assert client.calls == 1


def test_proxy_pool_round_robin_failure_and_cooldown():
    now = [0]
    pool = ProxyPool(
        Settings(
            proxies="http://one,http://two",
            proxy_strategy="round_robin",
            proxy_max_failures=1,
            proxy_cooldown=10,
        ),
        clock=lambda: now[0],
    )
    first = pool.get_proxy()
    assert first == "http://one"
    pool.report(first, False)
    second = pool.get_proxy()
    assert second == "http://two"
    pool.report(second, False)
    with pytest.raises(RuntimeError, match="均不可用"):
        pool.get_proxy()
    now[0] = 11
    assert pool.get_proxy() == "http://one"


def test_product_collector_parses_brand_ratings_and_package_data():
    html = """
    <span id="productTitle">Test</span>
    <span id="bylineInfo">Visit the Acme Store</span>
    <span id="acrCustomerReviewText">100 ratings</span>
    <div id="histogramTable"><span data-hook="rating-bar">5 star 70%</span>
    <span data-hook="rating-bar">1 star 10%</span></div>
    <div id="productDetails_techSpec_section_1">
      Product Dimensions 5 x 4 x 3 inches Shipping Weight 8 ounces
    </div>
    """
    collector = ProductCollector(
        Settings(request_delay_min=0, request_delay_max=0),
        client=FakeHttp(FakeResponse(html)),
        sleep=lambda _: None,
    )
    product = collector.collect("B000000001")
    assert product.brand == "Acme"
    assert product.rating_distribution == {"5": 70, "1": 10}
    assert product.package_length_in == 5
    assert product.package_weight_lb == 0.5


def test_fba_fee_uses_size_weight_and_marks_missing_measurements():
    standard = Product(
        asin="B000000001",
        package_length_in=5,
        package_width_in=4,
        package_height_in=3,
        package_weight_lb=0.25,
    )
    missing = Product(asin="B000000002")
    assert estimate_fba_fee(standard) == (3.06, "size_tier")
    assert estimate_fba_fee(missing) == (5.5, "conservative_fallback")


@pytest.mark.parametrize("dimensions", [(18, 14, 8), (8, 18, 14)])
def test_light_standard_item_uses_actual_weight(dimensions):
    product = Product(
        asin="B000000001", package_length_in=dimensions[0],
        package_width_in=dimensions[1], package_height_in=dimensions[2],
        package_weight_lb=0.25,
    )
    assert estimate_fba_fee(product) == (3.06, "size_tier")


def test_large_item_uses_dimensional_weight():
    product = Product(
        asin="B000000001", package_length_in=20, package_width_in=15,
        package_height_in=10, package_weight_lb=0.25,
    )
    fee, source = estimate_fba_fee(product)
    assert fee == pytest.approx(6.92 + (3000 / 139 - 1) * 2 * 0.16)
    assert source == "size_tier"


def test_sourcing_uses_llm_similarity_and_converts_prices():
    class FakeLLM:
        def __init__(self):
            self.responses = [
                {"keywords": "便携咖啡杯"},
                {"matches": [{"index": 0, "score": 90}, {"index": 1, "score": 86}]},
            ]

        def complete_json(self, messages):
            return self.responses.pop(0)

    sourcing = SourcingAnalyzer(FakeLLM(), cny_usd_rate=7.2)
    product = Product(asin="B000000001", title="Portable coffee cup")
    assert sourcing.search_terms(product.title) == "便携咖啡杯"
    result = sourcing.match(
        product,
        [
            {"title": "保温咖啡杯", "price_min_cny": 36, "price_max_cny": 40},
            {"title": "便携水杯", "price_min_cny": 38, "price_max_cny": 42},
        ],
    )
    assert result["confidence"] == "high"
    assert result["cost_min_usd"] == 5
    assert result["matches"][0]["match_score"] == 90


def test_scoring_skips_missing_inputs_and_normalizes_weights():
    estimate = SalesEstimate(
        monthly_sales=100,
        lower_bound=50,
        upper_bound=150,
        confidence="low",
        category="home",
    )
    scores = score_product(Product(asin="B000000001", price=20), estimate)
    assert scores.details["brand_concentration"] is None
    assert "brand_concentration" in scores.details["skipped_subitems"]
    assert scores.details["cost_source"] == "fallback"
    assert scores.details["data_completeness"] < 0.6
    assert 0 <= scores.total <= 100


def test_trends_queries_at_most_five_keywords_per_request():
    class FakeTrends:
        def __init__(self):
            self.batches = []

        def build_payload(self, batch, **kwargs):
            self.batches.append(batch)

        def interest_over_time(self):
            return pd.DataFrame({keyword: [20, 40] for keyword in self.batches[-1]})

        def interest_by_region(self, **kwargs):
            return pd.DataFrame()

    client = FakeTrends()
    trends = TrendsCollector(client, sleep=lambda _: None)
    results = trends.collect_many([f"keyword {i}" for i in range(6)])
    assert [len(batch) for batch in client.batches] == [5, 1]
    assert len(results) == 6


def test_storage_reuses_single_connection_and_persists_stage(tmp_path):
    storage = Storage(tmp_path / "stage.db")
    connection = storage._connect()
    for index in range(30):
        storage.save_product("task", f"B000000{index:03d}", {"asin": str(index)}, "scored")
    assert storage._connect() is connection
    assert all(record["stage"] == "scored" for record in storage.list_product_records("task"))
    storage.close()


def test_resume_skips_completed_product_and_analysis_stages(tmp_path):
    class FakeBestsellers:
        def collect(self, category, list_type):
            return [Product(asin="B000000001", title="Product", bsr=100)]

    class FakeProducts:
        def __init__(self):
            self.calls = 0

        def collect(self, asin, category):
            self.calls += 1
            return Product(
                asin=asin, title="Product", bsr=100, price=25, rating=4, review_count=50
            )

    class FakeReviews:
        def __init__(self):
            self.calls = 0

        def collect_low_star(self, asin, limit):
            self.calls += 1
            return []

    class FakeTrends:
        def __init__(self):
            self.calls = 0

        def collect(self, keyword):
            self.calls += 1
            return {"slope": 0, "seasonality": 0}

    storage = Storage(tmp_path / "resume.db")
    products, reviews, trends = FakeProducts(), FakeReviews(), FakeTrends()
    pipeline = Pipeline(
        settings=Settings(database_path=str(tmp_path / "resume.db"), enable_1688=False,
                          request_delay_min=0),
        storage=storage,
        bestsellers=FakeBestsellers(),
        products=products,
        reviews=reviews,
        trends=trends,
    )
    task_id, _ = pipeline.collect("home")
    pipeline.run("home", task_id=task_id)
    first_counts = (products.calls, reviews.calls, trends.calls)
    result = pipeline.run("home", task_id=task_id)
    assert first_counts == (1, 1, 1)
    assert (products.calls, reviews.calls, trends.calls) == first_counts
    assert result.products[0].product.asin == "B000000001"


def test_pipeline_stops_all_collection_after_captcha(tmp_path):
    class FakeBestsellers:
        def collect(self, category, list_type):
            return [
                Product(asin="B000000001", bsr=100),
                Product(asin="B000000002", bsr=200),
            ]

    class CaptchaProducts:
        calls = 0

        def collect(self, asin, category):
            self.calls += 1
            raise CaptchaDetected("robot check")

    products = CaptchaProducts()
    storage = Storage(tmp_path / "captcha.db")
    pipeline = Pipeline(
        settings=Settings(database_path=str(tmp_path / "captcha.db"), enable_1688=False),
        storage=storage,
        bestsellers=FakeBestsellers(),
        products=products,
    )
    result = pipeline.run("home")
    assert result.status == "captcha_detected"
    assert products.calls == 1
    assert "CAPTCHA 告警" in result.errors[0]
