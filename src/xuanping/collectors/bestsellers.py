import re
from urllib.parse import quote, urljoin

from selectolax.parser import HTMLParser

from xuanping.collectors.base import BaseCollector
from xuanping.models import Product

# Amazon 页面会改版；选择器集中在此处，便于快速维护。
PRODUCT_SELECTORS = (
    "#gridItemRoot",
    ".zg-grid-general-faceout",
    "[data-asin]",
)
ASIN_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


class BestsellersCollector(BaseCollector):
    LIST_TYPES = {
        "bestsellers": "bestsellers",
        "movers": "movers_and_shakers",
        "new": "new_releases",
    }

    def collect(self, category: str, list_type: str = "bestsellers") -> list[Product]:
        if list_type not in self.LIST_TYPES:
            raise ValueError("榜单类型必须为 bestsellers、movers 或 new")
        if category.startswith(("http://", "https://")):
            url = category
        else:
            node = quote(category, safe="")
            url = f"https://{self.settings.amazon_domain}/gp/{self.LIST_TYPES[list_type]}/?node={node}"
        response = self.get(url)
        tree = HTMLParser(response.text)
        items = []
        for selector in PRODUCT_SELECTORS:
            items = tree.css(selector)
            if items:
                break
        products: list[Product] = []
        seen: set[str] = set()
        for fallback_rank, item in enumerate(items[:100], start=1):
            asin = (item.attributes.get("data-asin") or "").upper()
            link = item.css_first("a[href*='/dp/'], a[href*='/gp/product/']")
            if not asin and link:
                match = ASIN_PATTERN.search(link.attributes.get("href", ""))
                asin = match.group(1).upper() if match else ""
            if not asin or asin in seen:
                continue
            seen.add(asin)
            title_node = item.css_first("a[title], .p13n-sc-truncate, ._cDEzb_p13n-sc-css-line-clamp-3_g3dy1")
            rank_text = item.css_first(".zg-bdg-text")
            rank_match = re.search(r"\d+", rank_text.text() if rank_text else "")
            products.append(
                Product(
                    asin=asin,
                    rank=int(rank_match.group()) if rank_match else fallback_rank,
                    title=(
                        title_node.attributes.get("title", "").strip()
                        or title_node.text(strip=True)
                        if title_node
                        else ""
                    ),
                    category=category,
                )
            )
        return products
