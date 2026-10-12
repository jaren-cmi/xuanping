from typing import Any

from pydantic import BaseModel, Field


class Product(BaseModel):
    asin: str
    rank: int | None = None
    title: str = ""
    price: float | None = None
    rating: float | None = None
    review_count: int = 0
    bsr: int | None = None
    category: str = "default"
    image_url: str | None = None
    bullets: list[str] = Field(default_factory=list)
    low_star_reviews: list[str] = Field(default_factory=list)
    trends_slope: float | None = None
    trend_seasonality: float | None = None
    known_monthly_sales: float | None = None
    acquisition_cost: float | None = None
    brand: str = ""
    brand_share: float | None = None
    rating_distribution: dict[str, int] = Field(default_factory=dict)
    package_length_in: float | None = None
    package_width_in: float | None = None
    package_height_in: float | None = None
    package_weight_lb: float | None = None
    fragile: bool | None = None
    oversized: bool | None = None
    seasonal: bool | None = None
    regulated: bool | None = None
    high_ip_risk: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CalibrationSample(BaseModel):
    bsr: int = Field(gt=0)
    monthly_sales: float = Field(gt=0)


class SalesEstimate(BaseModel):
    monthly_sales: float
    lower_bound: float
    upper_bound: float
    confidence: str
    category: str


class DimensionScores(BaseModel):
    demand: float
    competition: float
    profit: float
    opportunity: float
    risk: float
    total: float
    details: dict[str, Any] = Field(default_factory=dict)


class PainPoint(BaseModel):
    issue: str
    frequency: int = Field(ge=0)
    recommendation: str


class ReportProduct(BaseModel):
    product: Product
    estimate: SalesEstimate
    scores: DimensionScores
    pain_points: list[PainPoint] = Field(default_factory=list)
    supplier_matches: list[dict[str, Any]] = Field(default_factory=list)


class TaskResult(BaseModel):
    task_id: str
    category: str
    status: str
    products: list[ReportProduct] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
