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
        )
