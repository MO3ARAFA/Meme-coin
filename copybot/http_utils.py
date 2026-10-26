"""Shared async HTTP plumbing: a token-bucket rate limiter and retrying JSON requests.

Free RPC / API tiers answer bursts with HTTP 429. Every outbound client in this project goes
through a RateLimiter so we degrade into "slower" instead of "banned".
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class RateLimiter:
    """Async token bucket. `rate` tokens per second, bursts up to `burst`."""

    def __init__(self, rate: float, burst: float | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.capacity = burst if burst is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / self.rate)

    def penalize(self, seconds: float) -> None:
        """After a 429, drain the bucket so the next calls wait ~`seconds`. Not cumulative:
        N concurrent requests hitting 429 together must not stack into an N-times longer stall."""
        self._tokens = min(self._tokens, -seconds * self.rate)


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    retries: int = 4,
    timeout: float = 10.0,
    **kwargs: Any,
) -> Any:
    """Send a request and decode JSON, retrying on 429/5xx and transport errors with backoff."""
    delay = 0.4
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        if limiter is not None:
            await limiter.acquire()
        try:
            resp = await client.request(method, url, timeout=timeout, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            log.debug("transport error %s %s: %s", method, url, exc)
        else:
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code not in RETRY_STATUSES:
                raise HttpError(f"{method} {url} -> {resp.status_code}: {resp.text[:300]}", resp.status_code)
            last_exc = HttpError(f"{method} {url} -> {resp.status_code}", resp.status_code)
            if resp.status_code == 429 and limiter is not None:
                retry_after = resp.headers.get("retry-after")
                limiter.penalize(float(retry_after) if retry_after and retry_after.isdigit() else 1.0)
        if attempt < retries:
            await asyncio.sleep(delay + random.uniform(0, delay / 2))
            delay = min(delay * 2, 8.0)
    raise HttpError(f"{method} {url} failed after {retries + 1} attempts: {last_exc}")


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"user-agent": "copybot/0.1", "accept": "application/json"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        http2=False,
    )
