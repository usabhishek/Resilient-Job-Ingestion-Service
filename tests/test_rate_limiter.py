import pytest
import asyncio
import time
from app.core.rate_limiter import TokenBucketRateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_immediate_token():
    limiter = TokenBucketRateLimiter(rate_limit_rps=10.0, capacity=5.0)
    # First acquire should not sleep as bucket starts full
    slept = await limiter.acquire(1.0)
    assert slept == 0.0
    assert limiter.tokens == 4.0

@pytest.mark.asyncio
async def test_rate_limiter_pacing_delay():
    # 2 requests per second -> 0.5s per token
    limiter = TokenBucketRateLimiter(rate_limit_rps=2.0, capacity=1.0)
    
    # Empty the single token
    await limiter.acquire(1.0)
    
    # Second acquire should pace
    start = time.perf_counter()
    slept = await limiter.acquire(1.0)
    elapsed = time.perf_counter() - start
    
    assert slept > 0.3
    assert elapsed >= 0.35

@pytest.mark.asyncio
async def test_rate_limiter_concurrency():
    limiter = TokenBucketRateLimiter(rate_limit_rps=20.0, capacity=5.0)
    
    async def worker():
        return await limiter.acquire(1.0)
        
    results = await asyncio.gather(*[worker() for _ in range(5)])
    assert len(results) == 5
