import random
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from xuanping.config import Settings, get_settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
]


class BaseCollector:
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
        *,
        sleep: Any = time.sleep,
        rng: Any = random,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self.sleep = sleep
        self.rng = rng

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def get(self, url: str, **kwargs: Any) -> Any:
        self.sleep(self.rng.uniform(self.settings.request_delay_min, self.settings.request_delay_max))
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", self.rng.choice(USER_AGENTS))
        if self.client is not None:
            response = self.client.get(url, headers=headers, **kwargs)
        else:
            proxy = self.rng.choice(self.settings.proxy_pool) if self.settings.proxy_pool else None
            with httpx.Client(
                proxy=proxy, timeout=30, follow_redirects=True, headers=headers
            ) as client:
                response = client.get(url, **kwargs)
        response.raise_for_status()
        return response
