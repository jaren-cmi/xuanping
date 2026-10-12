import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from xuanping.collectors.base import BaseCollector
from xuanping.models import Product

# Amazon 详情页选择器可能随页面改版；多个备用选择器集中管理。
SELECTORS = {
    "title": ["#productTitle"],
    "price": ["#corePrice_feature_div .a-offscreen", ".a-price .a-offscreen"],
    "rating": ["#acrPopover", "[data-hook='rating-out-of-text']"],
    "reviews": ["#acrCustomerReviewText", "[data-hook='total-review-count']"],
    "bsr": ["#detailBullets_feature_div", "#productDetails_detailBullets_sections1"],
    "image": ["#landingImage", "#imgBlkFront"],
    "bullets": ["#feature-bullets li"],
    "brand": ["#bylineInfo", "#brand"],
    "rating_bars": [
        "#histogramTable tr",
        "#histogramTable [data-hook='rating-bar']",
        "[data-hook='rating-bar']",
    ],
    "details": ["#productDetails_techSpec_section_1", "#detailBullets_feature_div"],
}


class ProductCollector(BaseCollector):
    def collect(self, asin: str, category: str = "default") -> Product:
        url = f"https://{self.settings.amazon_domain}/dp/{asin}"
        response = self.get(url)
        tree = HTMLParser(response.text)

        def text_for(key: str) -> str:
            for selector in SELECTORS[key]:
                node = tree.css_first(selector)
                if node:
                    return node.text(strip=True)
            return ""

        price_text = text_for("price").replace(",", "")
        price_match = re.search(r"\d+(?:\.\d+)?", price_text)
        rating_text = text_for("rating")
        rating_match = re.search(r"\d+(?:\.\d+)?", rating_text)
        reviews_text = text_for("reviews").replace(",", "")
        reviews_match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])?", reviews_text, re.I)
        bsr_text = text_for("bsr")
        bsr_match = re.search(r"#([\d,]+)", bsr_text)
        review_count = 0
        if reviews_match:
            multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
                reviews_match.group(2).upper() if reviews_match.group(2) else "", 1
            )
            review_count = int(float(reviews_match.group(1)) * multiplier)
        distribution: dict[str, int] = {}
        rating_bars = next(
            (tree.css(selector) for selector in SELECTORS["rating_bars"] if tree.css(selector)),
            [],
        )
        for bar in rating_bars:
            label = " ".join(
                [bar.text(strip=True), *bar.attributes.values()]
            )
            star_match = re.search(r"([1-5])\s*star", label, re.I)
            percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", label)
            if star_match and percent_match:
                distribution[star_match.group(1)] = round(
                    review_count * float(percent_match.group(1)) / 100
                )
        brand = ""
        for selector in SELECTORS["brand"]:
            brand_node = tree.css_first(selector)
            if brand_node:
                brand = brand_node.text(strip=True)
                brand = re.sub(r"^(visit the|brand:)\s*", "", brand, flags=re.I)
                brand = re.sub(r"\s+store$", "", brand, flags=re.I).strip()
                if brand:
                    break
        detail_text = " ".join(
            node.text(strip=True)
            for selector in SELECTORS["details"]
            for node in tree.css(selector)
        )
        dimensions_match = re.search(
            r"(?:Product Dimensions|Package Dimensions)[\s:]*"
            r"([\d.]+)\s*[x×]\s*([\d.]+)\s*[x×]\s*([\d.]+)\s*(inches|cm|centimeters)",
            detail_text,
            re.I,
        )
        dims = [float(value) for value in dimensions_match.groups()[:3]] if dimensions_match else []
        if dimensions_match and dimensions_match.group(4).lower() in {"cm", "centimeters"}:
            dims = [value / 2.54 for value in dims]
        weight_match = re.search(
            r"(?:Shipping Weight|Package Weight|Item Weight)[\s:]*([\d.]+)\s*(pounds|lbs?|ounces?|oz|kg|g)\b",
            detail_text,
            re.I,
        )
        weight = None
        if weight_match:
            weight = float(weight_match.group(1))
            unit = weight_match.group(2).lower()
            weight *= {"kg": 2.20462, "g": 0.00220462, "oz": 1 / 16, "ounce": 1 / 16,
                       "ounces": 1 / 16}.get(unit, 1)
        image = next((tree.css_first(s) for s in SELECTORS["image"] if tree.css_first(s)), None)
        bullets = [
            node.text(strip=True)
            for node in tree.css(SELECTORS["bullets"][0])
            if node.text(strip=True)
        ]
        return Product(
            asin=asin.upper(),
            category=category,
            title=text_for("title"),
            price=float(price_match.group()) if price_match else None,
            rating=float(rating_match.group()) if rating_match else None,
            review_count=review_count,
            bsr=int(bsr_match.group(1).replace(",", "")) if bsr_match else None,
            image_url=image.attributes.get("src") if image else None,
            bullets=bullets,
            brand=brand,
            rating_distribution=distribution,
            package_length_in=dims[0] if dims else None,
            package_width_in=dims[1] if dims else None,
            package_height_in=dims[2] if dims else None,
            package_weight_lb=weight,
        )
