import random
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from xuanping.config import Settings, get_settings


@dataclass
class _ProxyState:
    failures: int = 0
    unavailable_until: float = 0


class ProxyPool:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Any = time.monotonic,
        rng: Any = random,
        health_checker: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.proxies = self.settings.proxy_pool
        self.clock = clock
        self.rng = rng
        self.health_checker = health_checker
        self._states = {proxy: _ProxyState() for proxy in self.proxies}
        self._index = 0
        self._lock = threading.Lock()
        if self.settings.proxy_health_check:
            self._check_health()

    def _check_health(self) -> None:
        checker = self.health_checker or self._default_health_check
        for proxy in self.proxies:
            self.report(proxy, bool(checker(proxy)))

    @staticmethod
    def _default_health_check(proxy: str) -> bool:
        try:
            response = httpx.get(
                "https://www.amazon.com/robots.txt", proxy=proxy, timeout=5
            )
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    def get_proxy(self) -> str | None:
        if not self.proxies:
            return None
        with self._lock:
            now = self.clock()
            available = [
                proxy
                for proxy in self.proxies
                if self._states[proxy].unavailable_until <= now
            ]
            if not available:
                raise RuntimeError(
                    "代理池中的代理均不可用；请检查代理配置或等待冷却期结束"
                )
            if self.settings.proxy_strategy == "random":
                return self.rng.choice(available)
            for offset in range(len(self.proxies)):
                index = (self._index + offset) % len(self.proxies)
                proxy = self.proxies[index]
                if proxy in available:
                    self._index = (index + 1) % len(self.proxies)
                    return proxy
            raise RuntimeError("代理池中的代理均不可用")

    def report(self, proxy: str | None, success: bool) -> None:
        if proxy is None or proxy not in self._states:
            return
        with self._lock:
            state = self._states[proxy]
            if success:
                state.failures = 0
                state.unavailable_until = 0
            else:
                state.failures += 1
                if state.failures >= self.settings.proxy_max_failures:
                    state.unavailable_until = self.clock() + self.settings.proxy_cooldown

