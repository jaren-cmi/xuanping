import re
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from xuanping.collectors.base import BaseCollector

# 1688 搜索页结构可能变化；选择器集中维护并保留备用结构。
OFFER_SELECTORS = (".offer-list-row", ".offer-card", "[data-offer-id]")


class Supplier1688Collector(BaseCollector):
    def collect(self, keywords: str, limit: int = 10) -> list[dict[str, object]]:
        url = (
            "https://s.1688.com/selloffer/offer_search.htm?keywords="
            + quote(keywords)
        )
        tree = HTMLParser(self.get(url).text)
        items = next(
            (tree.css(selector) for selector in OFFER_SELECTORS if tree.css(selector)),
            [],
        )
        offers: list[dict[str, object]] = []
        for item in items[:limit]:
            link = item.css_first("a[href]")
            text = item.text(separator=" ", strip=True)
            price_values = [
                float(value.replace(",", ""))
                for value in re.findall(r"(?:¥|￥)\s*([\d,.]+)", text)
            ]
            if not price_values:
                price_values = [
                    float(value.replace(",", ""))
                    for value in re.findall(r"(?<!\d)(\d+(?:\.\d{1,2})?)\s*元", text)
                ]
            if not link or not price_values:
                continue
            title_node = item.css_first("a[title]") or link
            title = title_node.attributes.get("title", "").strip() or title_node.text(strip=True)
            if not title:
                continue
            moq_match = re.search(r"(\d+)\s*(?:件起批|件起订|起批)", text)
            sold_match = re.search(r"([\d.]+)\s*(万)?\s*(?:件成交|笔成交)", text)
            sold = float(sold_match.group(1)) if sold_match else None
            if sold_match and sold_match.group(2):
                sold *= 10_000
            supplier = item.css_first(".company-name, [class*='company']")
            href = link.attributes.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://s.1688.com" + href
            offers.append(
                {
                    "title": title,
                    "price_min_cny": min(price_values),
                    "price_max_cny": max(price_values),
                    "moq": int(moq_match.group(1)) if moq_match else None,
                    "transactions": sold,
                    "supplier": supplier.text(strip=True) if supplier else "",
                    "url": href,
                }
            )
        return offers
