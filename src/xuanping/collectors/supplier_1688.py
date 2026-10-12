import logging
import re
from urllib.parse import quote, urljoin

import httpx

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from xuanping.collectors.base import BaseCollector, CaptchaDetected

# 这些选择器未经真实页面验证；1688 为 JS 渲染站点，静态 HTTP 抓取可能需要配合浏览器方案。
OFFER_SELECTORS = (".offer-list-row", ".offer-card", "[data-offer-id]")
LOGIN_SELECTORS = ("input[type='password']", "form[action*='login']")
PLACEHOLDER_SELECTORS = ("#app", "#root", "#offer-list", "[class*='skeleton']")
BLOCK_MARKERS = ("请先登录", "请登录后", "访问受限", "访问频繁", "异常访问", "滑块验证")
LOGIN_URL_MARKERS = ("login.1688.com", "passport.1688.com", "/login")
EMPTY_MARKERS = ("暂无商品", "无搜索结果", "没有相关商品", "未找到相关商品")
PRODUCT_MARKERS = ("detail.1688.com/offer/", '"offerid"', '"offerlist"')
logger = logging.getLogger(__name__)


class Supplier1688Collector(BaseCollector):
    def collect(self, keywords: str, limit: int = 10) -> list[dict[str, object]]:
        url = self.settings.supplier_1688_search_url.replace(
            "{keywords}",
            quote(keywords, safe="", encoding=self.settings.supplier_1688_keyword_encoding),
        )
        try:
            response = self.get(url)
        except CaptchaDetected:
            logger.warning("1688 疑似被反爬拦截：检测到验证码，已中止采集，不自动重试。")
            raise
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403, 429}:
                logger.warning(
                    "1688 疑似被反爬拦截：HTTP %s，请检查访问权限，不自动重试。",
                    error.response.status_code,
                )
            raise
        tree = HTMLParser(response.text)
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
            href = urljoin(str(getattr(response, "url", url)), href)
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
        if not offers:
            self._warn_empty_results(response, tree, len(items))
        return offers

    def _warn_empty_results(self, response, tree: HTMLParser, item_count: int) -> None:
        html = response.text.lower()
        response_url = str(getattr(response, "url", "")).lower()
        if (
            any(marker in html for marker in BLOCK_MARKERS)
            or any(marker in response_url for marker in LOGIN_URL_MARKERS)
            or any(tree.css_first(selector) for selector in LOGIN_SELECTORS)
        ):
            reason = "疑似被反爬拦截：返回登录或访问限制页面，请检查访问权限。"
        elif any(marker in html for marker in EMPTY_MARKERS):
            reason = "页面无商品：页面明确提示无搜索结果，请检查关键词或关键词编码。"
        elif (
            item_count
            or any(marker in html for marker in PRODUCT_MARKERS)
            or any(tree.css_first(selector) for selector in PLACEHOLDER_SELECTORS)
            or tree.css_first("script")
        ):
            reason = "选择器失效或页面未渲染：存在商品线索或 JS 占位结构，请核对页面与选择器。"
        else:
            reason = "页面无商品：静态 HTML 未发现商品线索，但不能据此认定真实搜索无结果。"
        logger.warning("1688 解析到 0 条报价；%s HTML 长度=%d，候选节点=%d", reason, len(html), item_count)
