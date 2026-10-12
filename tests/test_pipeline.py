import csv
import json
from io import StringIO

import pytest

from xuanping.analysis.scoring import score_product
from xuanping.config import Settings
from xuanping.models import DimensionScores, Product, ReportProduct, SalesEstimate, TaskResult
from xuanping.pipeline import Pipeline, _compute_brand_share, export_report, render_report
from xuanping.storage import Storage


class FakeBestsellers:
    def __init__(self):
        self.products = [Product(asin="B000000001", rank=1, title="Product", bsr=100)]
        self.calls = 0

    def collect(self, category, list_type):
        self.calls += 1
        return self.products


class FakeProducts:
    def collect(self, asin, category):
        return Product(
            asin=asin,
            title="Product",
            category=category,
            bsr=100,
            price=25,
            rating=4.1,
            review_count=100,
        )


class FakeTrends:
    def collect(self, keyword):
        return {"slope": 1.0, "seasonality": 0.2}


class FakeReviews:
    def collect_low_star(self, asin, limit):
        return ["Battery life is poor"]


class FakePainPoints:
    def analyze(self, reviews):
        return []


def test_pipeline_saves_report_and_resumes_collected_asins(tmp_path):
    storage = Storage(tmp_path / "pipeline.db")
    bestsellers = FakeBestsellers()
    pipeline = Pipeline(
        settings=Settings(database_path=str(tmp_path / "pipeline.db"), request_delay_min=0),
        storage=storage,
        bestsellers=bestsellers,
        products=FakeProducts(),
        reviews=FakeReviews(),
        trends=FakeTrends(),
        pain_points=FakePainPoints(),
    )
    task_id, _ = pipeline.collect("home")

    result = pipeline.run("home", top=1, task_id=task_id)

    assert bestsellers.calls == 1
    assert result.products[0].product.asin == "B000000001"
    assert "Top 3 深度分析" in export_report(storage, task_id, "md")
    assert "供应链比价" in export_report(storage, task_id, "md")
    assert storage.list_products(task_id)[0]["asin"] == "B000000001"


@pytest.mark.parametrize("dimension", ["demand", "competition", "profit", "opportunity", "risk"])
def test_report_renders_missing_dimension_as_na(dimension):
    values = dict.fromkeys(["demand", "competition", "profit", "opportunity", "risk"], 0)
    values[dimension] = None
    result = TaskResult(
        task_id="test", category="home", status="completed",
        products=[ReportProduct(
            product=Product(asin="B000000001"),
            estimate=SalesEstimate(
                monthly_sales=100, lower_bound=50, upper_bound=150,
                confidence="low", category="home",
            ),
            scores=DimensionScores(**values, total=0),
        )],
    )
    index = list(values).index(dimension)
    row = next(line for line in render_report(result).splitlines() if line.startswith("| B000"))
    assert row.split("|")[5 + index].strip() == "N/A"
    assert row.count("0.0") == 5
    csv_row = list(csv.reader(StringIO(render_report(result, "csv"))))[1]
    assert csv_row[4 + index] == "N/A"
    assert json.loads(render_report(result, "json"))["products"][0]["scores"][dimension] is None


def test_brand_share_counts_asins_and_includes_unknown_brands():
    products = [
        Product(asin="one", brand="Acme"), Product(asin="two", brand="ACME"),
        Product(asin="three", brand="Other"), Product(asin="four", brand_share=1),
    ]
    _compute_brand_share(products)
    assert [product.brand_share for product in products] == [0.5, 0.5, 0.25, None]
    _compute_brand_share([])


def test_pipeline_brand_share_uses_only_scored_products_and_refreshes_cached_scores(tmp_path):
    class BrandedProducts:
        def collect(self, asin, category):
            return Product(asin=asin, brand="Acme", bsr=None if asin == "missing" else 100)

    bestsellers = FakeBestsellers()
    bestsellers.products = [
        Product(asin="one", brand="Acme"), Product(asin="two", brand="ACME"),
        Product(asin="missing", brand="Other"),
    ]
    storage = Storage(tmp_path / "brands.db")
    pipeline = Pipeline(
        settings=Settings(enable_1688=False), storage=storage,
        bestsellers=bestsellers, products=BrandedProducts(), trends=FakeTrends(),
        reviews=FakeReviews(), pain_points=FakePainPoints(),
    )
    task_id, _ = pipeline.collect("home")
    result = pipeline.run("home", task_id=task_id, top=0)
    assert len(result.products) == 2
    assert all(item.product.brand_share == 1 for item in result.products)
    assert all(item.scores.competition == 0 for item in result.products)
    for record in storage.list_product_records(task_id):
        product = Product.model_validate(record["product"])
        if record["stage"] == "scored":
            product.metadata["pipeline_scores"]["profit"] = 100
            product.metadata["pipeline_scores"]["competition"] = 100
            storage.save_product(task_id, product.asin, product.model_dump(mode="json"), "scored")
    resumed = pipeline.run("home", task_id=task_id, top=0)
    assert all(item.scores.profit is None for item in resumed.products)
    assert all(item.scores.competition == 0 for item in resumed.products)
    assert all(
        item.scores.total == score_product(item.product, item.estimate).total
        for item in resumed.products
    )
