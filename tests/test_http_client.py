import pytest
import httpx
from app.core.http_client import ResilientHttpClient
from app.core.rate_limiter import TokenBucketRateLimiter
from app.core.retry import RetryPolicy
from app.core.exceptions import (
    MalformedResponseError,
    RateLimitExceededError,
    TemporarySourceError,
    PermanentSourceError,
    HttpTimeoutError
)

@pytest.mark.asyncio
async def test_http_client_success():
    def handler(request):
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=1, initial_backoff=0.01)

    resilient_client = ResilientHttpClient(
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        client=client
    )

    data = await resilient_client.get_json("https://api.example.com/test")
    assert data == {"status": "ok"}

@pytest.mark.asyncio
async def test_http_client_malformed_json():
    def handler(request):
        return httpx.Response(200, text="<html><body>Not JSON</body></html>")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    resilient_client = ResilientHttpClient(rate_limiter=rate_limiter, client=client)

    with pytest.raises(MalformedResponseError):
        await resilient_client.get_json("https://api.example.com/bad-json")

@pytest.mark.asyncio
async def test_http_client_429_exhaustion():
    attempts = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01, max_backoff=0.05)

    resilient_client = ResilientHttpClient(
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        client=client
    )

    with pytest.raises(RateLimitExceededError):
        await resilient_client.get_json("https://api.example.com/rate-limited")
    
    assert attempts == 3 # Initial attempt + 2 retries

@pytest.mark.asyncio
async def test_http_client_503_retry_and_exhaustion():
    attempts = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01, max_backoff=0.05)

    resilient_client = ResilientHttpClient(
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        client=client
    )

    with pytest.raises(TemporarySourceError):
        await resilient_client.get_json("https://api.example.com/server-error")

    assert attempts == 3

@pytest.mark.asyncio
async def test_http_client_404_no_retry():
    attempts = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=3, initial_backoff=0.01)

    resilient_client = ResilientHttpClient(
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        client=client
    )

    with pytest.raises(PermanentSourceError):
        await resilient_client.get_json("https://api.example.com/not-found")

    assert attempts == 1 # Non-retryable status must not retry

@pytest.mark.asyncio
async def test_http_client_timeout():
    def handler(request):
        raise httpx.ReadTimeout("Timeout reading response", request=request)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=1, initial_backoff=0.01)

    resilient_client = ResilientHttpClient(
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        client=client
    )

    with pytest.raises(HttpTimeoutError):
        await resilient_client.get_json("https://api.example.com/timeout")
