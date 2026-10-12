import math
from collections.abc import Iterable

from xuanping.models import CalibrationSample, SalesEstimate
from xuanping.storage import Storage

# 经验初始曲线（月销量 = a * BSR^(-b)），并非 Amazon 官方数据或保证值。
# 各类目真实关系不同，应使用自有已知销量样本校准。
DEFAULT_CURVES: dict[str, tuple[float, float]] = {
    "default": (12000.0, 0.72),
    "home": (18000.0, 0.75),
    "electronics": (9000.0, 0.68),
    "beauty": (15000.0, 0.73),
    "toys": (14000.0, 0.74),
    "sports": (13000.0, 0.72),
}


class BSRSalesEstimator:
    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage

    def curve(self, category: str) -> tuple[float, float, int]:
        if self.storage:
            calibrated = self.storage.get_calibration(category)
            if calibrated:
                return calibrated
        a, b = DEFAULT_CURVES.get(category.lower(), DEFAULT_CURVES["default"])
        return a, b, 0

    def estimate(self, bsr: int, category: str = "default") -> SalesEstimate:
        if bsr <= 0:
            raise ValueError("BSR 必须为正整数")
        a, b, samples = self.curve(category)
        sales = max(1.0, a * bsr ** (-b))
        # 置信区间表达模型误差；未校准的经验曲线区间更宽。
        spread = 0.35 if samples >= 10 else 0.7 if samples >= 3 else 1.0
        confidence = "high" if samples >= 20 else "medium" if samples >= 8 else "low"
        return SalesEstimate(
            monthly_sales=round(sales, 1),
            lower_bound=round(max(0.0, sales * (1 - spread)), 1),
            upper_bound=round(sales * (1 + spread), 1),
            confidence=confidence,
            category=category,
        )

    def calibrate(
        self, samples: Iterable[CalibrationSample | dict[str, float] | tuple[int, float]], category: str
    ) -> tuple[float, float]:
        points = []
        for sample in samples:
            if isinstance(sample, CalibrationSample):
                bsr, sales = sample.bsr, sample.monthly_sales
            elif isinstance(sample, dict):
                bsr, sales = int(sample["bsr"]), float(sample["monthly_sales"])
            else:
                bsr, sales = int(sample[0]), float(sample[1])
            if bsr <= 0 or sales <= 0:
                raise ValueError("校准样本的 BSR 和月销量必须为正数")
            points.append((math.log(bsr), math.log(sales)))
        if len(points) < 2:
            raise ValueError("至少需要两个有效样本进行最小二乘校准")
        x_mean = sum(x for x, _ in points) / len(points)
        y_mean = sum(y for _, y in points) / len(points)
        denominator = sum((x - x_mean) ** 2 for x, _ in points)
        if denominator == 0:
            raise ValueError("校准样本的 BSR 必须包含不同取值")
        slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
        b = -slope
        a = math.exp(y_mean - slope * x_mean)
        if not math.isfinite(a) or not math.isfinite(b) or a <= 0 or b <= 0:
            raise ValueError("样本拟合结果无效；请检查销量和 BSR 是否相关")
        if self.storage:
            self.storage.save_calibration(category, a, b, len(points))
        return a, b
