import random
import logging
import time
from typing import Any

import httpx

from xuanping.config import Settings, get_settings
from xuanping.collectors.proxy_pool import ProxyPool

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
]
logger = logging.getLogger(__name__)
CAPTCHA_MARKERS = (
    "api-services-support@amazon.com",
    "enter the characters you see below",
    "/errors/validatecaptcha",
    "robot check",
    "captcha",
    "安全验证",
)


class CaptchaDetected(RuntimeError):
    """Amazon/1688 returned a human-verification page."""


class BaseCollector:
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
        *,
        sleep: Any = time.sleep,
        rng: Any = random,
        proxy_pool: ProxyPool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self.sleep = sleep
        self.rng = rng
        self.proxy_pool = proxy_pool or ProxyPool(self.settings, rng=rng)

    def get(self, url: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        for attempt in range(3):
            self.sleep(
                self.rng.uniform(
                    self.settings.request_delay_min, self.settings.request_delay_max
                )
            )
            headers.setdefault("User-Agent", self.rng.choice(USER_AGENTS))
            proxy = self.proxy_pool.get_proxy()
            try:
                if self.client is not None:
                    response = self.client.get(url, headers=headers, **kwargs)
                else:
                    with httpx.Client(
                        proxy=proxy, timeout=30, follow_redirects=True, headers=headers
                    ) as client:
                        response = client.get(url, **kwargs)
                body = getattr(response, "text", "")
                response_url = str(getattr(response, "url", ""))
                if any(marker in body.lower() or marker in response_url.lower()
                       for marker in CAPTCHA_MARKERS):
                    self.proxy_pool.report(proxy, False)
                    message = "检测到 Amazon/1688 CAPTCHA，已中止采集"
                    logger.error(message)
                    raise CaptchaDetected(message)
                status = getattr(response, "status_code", 200)
                if status >= 500:
                    if attempt < 2:
                        self.proxy_pool.report(proxy, False)
                        self.sleep(2**attempt)
                        continue
                    response.raise_for_status()
                elif status >= 400:
                    response.raise_for_status()
                self.proxy_pool.report(proxy, True)
                return response
            except CaptchaDetected:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                self.proxy_pool.report(proxy, False)
                if attempt == 2:
                    raise
                self.sleep(2**attempt)
            except httpx.HTTPStatusError as error:
                self.proxy_pool.report(proxy, False)
                if error.response.status_code < 500 or attempt == 2:
                    raise
                self.sleep(2**attempt)
        raise RuntimeError("请求重试耗尽")
