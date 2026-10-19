import asyncio
import time
import logging

logger = logging.getLogger("rate_limiter")

class TokenBucketRateLimiter:
    """
    Async Token Bucket Rate Limiter for request pacing.
    Enforces smooth request flow and prevents burst traffic to public APIs.
    """
    def __init__(self, rate_limit_rps: float = 2.0, capacity: float | None = None):
        self.rate = max(0.1, float(rate_limit_rps))
        self.capacity = max(1.0, float(capacity if capacity is not None else rate_limit_rps))
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.rate))

    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquires `tokens` from the bucket. If tokens are not yet available,
        sleeps asynchronously until enough tokens are replenished.
        Returns the duration slept in seconds.
        """
        async with self._lock:
            self._refill()
            wait_time = 0.0

            if self.tokens < tokens:
                needed = tokens - self.tokens
                wait_time = needed / self.rate
                logger.debug(f"Pacing request: Rate limiter sleeping for {wait_time:.3f}s")
                await asyncio.sleep(wait_time)
                self.last_update = time.monotonic()
                self.tokens = 0.0
            else:
                self.tokens -= tokens

            return wait_time
