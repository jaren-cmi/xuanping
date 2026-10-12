import logging
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from xuanping.collectors.base import CaptchaDetected
from xuanping.collectors.supplier_1688 import Supplier1688Collector
from xuanping.config import Settings


def settings(**kwargs):
    return Settings(_env_file=None, request_delay_min=0, request_delay_max=0, **kwargs)


@pytest.mark.parametrize(
    ("html", "path", "message"),
    [
        ("<p>未找到相关商品</p>", "/search", "页面无商品：页面明确提示"),
        ("<p>empty</p>", "/search", "静态 HTML 未发现商品线索"),
        ("<p>请先登录</p>", "/search", "疑似被反爬拦截"),
        ("<p>访问频繁</p>", "/search", "疑似被反爬拦截"),
        ("<input type='password'>", "/search", "疑似被反爬拦截"),
        ("<html></html>", "/login", "疑似被反爬拦截"),
        ("<div id='app'></div><script>load()</script>", "/search", "选择器失效或页面未渲染"),
        ('<script>{"offerId":123}</script>', "/search", "选择器失效或页面未渲染"),
        ('<a href="https://detail.1688.com/offer/123.html">杯子</a>', "/search", "选择器失效"),
        ("<div class='offer-card'><a>无价格商品</a></div>", "/search", "选择器失效"),
    ],
)
def test_empty_offers_log_diagnostics(html, path, message, caplog):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    with httpx.Client(transport=transport) as client:
        collector = Supplier1688Collector(
            settings(supplier_1688_search_url=f"https://example.test{path}?q={{keywords}}"),
            client=client, sleep=lambda _: None,
        )
        with caplog.at_level(logging.WARNING):
            assert collector.collect("杯子") == []
    assert message in caplog.text
    assert "HTML 长度=" in caplog.text
    assert "候选节点=" in caplog.text


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_configured_encoding_and_url_parse_offers_without_warning(encoding, monkeypatch, caplog):
    monkeypatch.setenv("XUANPING_1688_KEYWORD_ENCODING", encoding)
    monkeypatch.setenv("XUANPING_1688_SEARCH_URL", "https://example.test/search?q={keywords}&sort=1")
    config = settings()
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="""
        <div class="offer-card"><a href="/offer/123" title="杯子">杯子</a>
        ￥36 ￥40 10件起批 2万件成交 <span class="company-name">工厂</span></div>
        """)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        offers = Supplier1688Collector(config, client=client, sleep=lambda _: None).collect("杯子/水")
    assert calls == [
        "https://example.test/search?q=" + quote("杯子/水", safe="", encoding=encoding) + "&sort=1"
    ]
    assert offers == [{
        "title": "杯子", "price_min_cny": 36, "price_max_cny": 40,
        "moq": 10, "transactions": 20000, "supplier": "工厂",
        "url": "https://example.test/offer/123",
    }]
    assert caplog.text == ""


def test_1688_defaults_and_invalid_settings():
    config = settings()
    assert config.supplier_1688_keyword_encoding == "utf-8"
    assert config.supplier_1688_search_url == (
        "https://s.1688.com/selloffer/offer_search.htm?keywords={keywords}"
    )
    with pytest.raises(ValidationError):
        settings(supplier_1688_keyword_encoding="unknown")
    with pytest.raises(ValidationError):
        settings(supplier_1688_search_url="https://example.test/no-placeholder")
    with pytest.raises(ValidationError):
        settings(supplier_1688_search_url="file:///tmp/{keywords}")


def test_gbk_does_not_silently_drop_unencodable_keywords():
    def unexpected_request(request):
        pytest.fail("无法编码的关键词不应发起请求")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        collector = Supplier1688Collector(
            settings(supplier_1688_keyword_encoding="gbk"), client=client,
            sleep=lambda _: None,
        )
        with pytest.raises(UnicodeEncodeError):
            collector.collect("杯子😀")


@pytest.mark.parametrize("status", [401, 403, 429])
def test_access_restrictions_log_and_do_not_retry(status, caplog):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="denied")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = Supplier1688Collector(settings(), client=client, sleep=lambda _: None)
        with pytest.raises(httpx.HTTPStatusError):
            collector.collect("杯子")
    assert len(calls) == 1
    assert f"HTTP {status}" in caplog.text
    assert "疑似被反爬拦截" in caplog.text


def test_captcha_logs_and_aborts_without_retry(caplog):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="CAPTCHA")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = Supplier1688Collector(settings(), client=client, sleep=lambda _: None)
        with pytest.raises(CaptchaDetected):
            collector.collect("杯子")
    assert len(calls) == 1
    assert "1688 疑似被反爬拦截" in caplog.text
