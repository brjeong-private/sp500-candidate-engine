from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

from sp500_candidate_engine.llm_preselection.config import RateLimits


class LlmRateLimiter:
    def __init__(
        self, limits: RateLimits, *, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.calls: deque[tuple[float, int]] = deque()

    async def acquire(self, estimated_input_tokens: int) -> None:
        tokens = estimated_input_tokens + self.limits.output_token_reserve
        if tokens > self.limits.tokens_per_minute:
            raise ValueError("One LLM request exceeds the configured TPM budget")
        while True:
            now = self.clock()
            while self.calls and self.calls[0][0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) < self.limits.requests_per_minute and (
                sum(value for _, value in self.calls) + tokens <= self.limits.tokens_per_minute
            ):
                self.calls.append((now, tokens))
                return
            await self.sleep(max(0.001, self.calls[0][0] + 60 - now))

    def record_usage(self, total_tokens: int | None) -> None:
        if total_tokens is None:
            return
        if type(total_tokens) is not int or total_tokens < 0:
            raise ValueError("Provider token usage is invalid")
        started, reserved = self.calls.pop()
        self.calls.append((started, max(reserved, total_tokens)))
