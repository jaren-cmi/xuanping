from selectolax.parser import HTMLParser

from xuanping.collectors.base import BaseCollector

# Amazon 评论页结构可能变动；维护备用 selector 以便快速修复。
REVIEW_SELECTORS = ("[data-hook='review']", ".review")


class ReviewsCollector(BaseCollector):
    def collect_low_star(self, asin: str, limit: int = 30) -> list[str]:
        url = f"https://{self.settings.amazon_domain}/product-reviews/{asin}?sortBy=recent"
        response = self.get(url)
        tree = HTMLParser(response.text)
        reviews = []
        for selector in REVIEW_SELECTORS:
            reviews = tree.css(selector)
            if reviews:
                break
        results: list[str] = []
        for review in reviews:
            rating = review.css_first("[data-hook='review-star-rating'], .review-rating")
            rating_text = rating.text(strip=True) if rating else ""
            import re

            match = re.search(r"\d+(?:\.\d+)?", rating_text)
            if not match or float(match.group()) > 3:
                continue
            body = review.css_first("[data-hook='review-body'], .review-text")
            if body and body.text(strip=True):
                results.append(body.text(strip=True))
            if len(results) >= limit:
                break
        return results
