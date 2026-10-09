from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Protocol

import httpx


class AsyncLimiter(Protocol):
    async def acquire(self) -> None: ...


class IntervalRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.interval_seconds = 60.0 / requests_per_minute
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_allowed = time.monotonic() + self.interval_seconds


class ProviderRequestError(RuntimeError):
    """Provider request failed without exposing sensitive query parameters."""


class RetryingHttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_attempts: int,
        user_agent: str,
        headers: Mapping[str, str] | None = None,
        limiter: AsyncLimiter | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.limiter = limiter
        request_headers = {"User-Agent": user_agent}
        if headers:
            request_headers.update(headers)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers=request_headers,
            follow_redirects=True,
        )

    async def __aenter__(self) -> RetryingHttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        await self.client.aclose()

    async def get(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> httpx.Response:
        last_error: httpx.HTTPError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                if self.limiter is not None:
                    await self.limiter.acquire()
                response = await self.client.get(url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except httpx.HTTPError as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
        assert last_error is not None
        response = getattr(last_error, "response", None)
        status_code = response.status_code if response is not None else None
        host = last_error.request.url.host if last_error.request is not None else "unknown"
        raise ProviderRequestError(
            f"Provider request failed after {self.max_attempts} attempts; "
            f"host={host}; status={status_code}"
        ) from last_error
