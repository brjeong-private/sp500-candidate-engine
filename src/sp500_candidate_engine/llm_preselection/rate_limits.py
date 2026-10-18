from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sp500_candidate_engine.llm_preselection.config import RateLimits


@dataclass(eq=False)
class TokenReservation:
    started_at: float
    tokens: int


class LlmRateLimiter:
    def __init__(
        self, limits: RateLimits, *, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.calls: deque[TokenReservation] = deque()

    async def acquire(self, estimated_input_tokens: int) -> TokenReservation:
        tokens = estimated_input_tokens + self.limits.output_token_reserve
        if tokens > self.limits.tokens_per_minute:
            raise ValueError("One LLM request exceeds the configured TPM budget")
        while True:
            now = self.clock()
            while self.calls and self.calls[0].started_at <= now - 60:
                self.calls.popleft()
            if len(self.calls) < self.limits.requests_per_minute and (
                sum(call.tokens for call in self.calls) + tokens <= self.limits.tokens_per_minute
            ):
                reservation = TokenReservation(now, tokens)
                self.calls.append(reservation)
                return reservation
            await self.sleep(max(0.001, self.calls[0].started_at + 60 - now))

    def record_usage(
        self, total_tokens: int | None, reservation: TokenReservation,
    ) -> None:
        if total_tokens is None:
            return
        if type(total_tokens) is not int or total_tokens < 0:
            raise ValueError("Provider token usage is invalid")
        if reservation in self.calls:
            reservation.tokens = max(reservation.tokens, total_tokens)
        elif total_tokens > reservation.tokens:
            self.calls.append(TokenReservation(self.clock(), total_tokens - reservation.tokens))
