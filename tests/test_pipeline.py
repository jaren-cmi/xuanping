from xuanping.config import Settings
from xuanping.models import Product
from xuanping.pipeline import Pipeline, export_report
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
    assert storage.list_products(task_id)[0]["asin"] == "B000000001"
