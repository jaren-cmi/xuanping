from xuanping.models import Product

# Source: Amazon Seller Central US FBA fulfillment fee tables, effective 2025-01-15.
# Simplified rate bands; verify against the official table before making decisions.
STANDARD_FEES = ((4, 3.06), (8, 3.35), (12, 3.77), (16, 4.25), (32, 4.55))
LARGE_BASE_FEE = 6.92
LARGE_PER_HALF_POUND = 0.16
COMMISSION_RATES = {
    "amazon device accessories": 0.45,
    "clothing": 0.17,
    "apparel": 0.17,
    "electronics": 0.08,
    "consumer electronics": 0.08,
    "jewelry": 0.20,
    "watches": 0.16,
    "grocery": 0.08,
    "beauty": 0.08,
    "personal care": 0.08,
    "furniture": 0.15,
    "home": 0.15,
    "default": 0.15,
}


def estimate_fba_fee(product: Product) -> tuple[float, str]:
    dimensions = (
        product.package_length_in,
        product.package_width_in,
        product.package_height_in,
        product.package_weight_lb,
    )
    if any(value is None or value <= 0 for value in dimensions):
        return 5.50, "conservative_fallback"
    length, width, height, weight = (float(value) for value in dimensions)
    if max(length, width, height) <= 18 and sorted(dimensions[:3])[1] <= 14 and min(dimensions[:3]) <= 8 and weight <= 20:
        ounces = weight * 16
        for upper_bound, fee in STANDARD_FEES:
            if ounces <= upper_bound:
                return fee, "size_tier"
        return 4.55 + ((ounces - 32) / 16) * 0.16, "size_tier"
    # 仅大件段使用体积重；139 为上述美国站费率表的立方英寸/磅换算系数。
    weight = max(weight, length * width * height / 139)
    return LARGE_BASE_FEE + max(0, weight - 1) * 2 * LARGE_PER_HALF_POUND, "size_tier"


def commission_rate(category: str) -> float:
    category = category.lower()
    return next(
        (rate for name, rate in COMMISSION_RATES.items() if name != "default" and name in category),
        COMMISSION_RATES["default"],
    )
