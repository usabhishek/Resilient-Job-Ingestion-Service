import asyncio
import json
import logging
from typing import Any
import httpx
from app.config import get_settings
from app.core.rate_limiter import TokenBucketRateLimiter
from app.core.retry import RetryPolicy
from app.core.exceptions import (
    HttpTimeoutError,
    RateLimitExceededError,
    TemporarySourceError,
    PermanentSourceError,
    MalformedResponseError
)

logger = logging.getLogger("http_client")

class ResilientHttpClient:
    """
    Production-grade HTTP client wrapping httpx.AsyncClient.
    Enforces explicit timeouts, rate pacing, bounded exponential retries,
    and granular exception categorization.
    """
    def __init__(
        self,
        rate_limiter: TokenBucketRateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        client: httpx.AsyncClient | None = None
    ):
        settings = get_settings()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(rate_limit_rps=settings.DEFAULT_RATE_LIMIT_RPS)
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=settings.HTTP_MAX_RETRIES,
            initial_backoff=settings.HTTP_INITIAL_BACKOFF_SECONDS,
            max_backoff=settings.HTTP_MAX_BACKOFF_SECONDS
        )
        self._external_client = client
        self._timeout = httpx.Timeout(
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            connect=settings.HTTP_CONNECT_TIMEOUT_SECONDS
        )
        self._default_headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "application/json"
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self._timeout, headers=self._default_headers)

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None
    ) -> Any:
        """
        Executes a paced, resilient HTTP GET request and returns parsed JSON.
        """
        merged_headers = {**self._default_headers, **(headers or {})}
        attempt = 0

        while attempt <= self.retry_policy.max_retries:
            attempt += 1
            
            # Request Pacing via Token Bucket
            await self.rate_limiter.acquire(1.0)
            
            logger.info(f"HTTP GET attempt {attempt}/{self.retry_policy.max_retries + 1} -> {url}")
            
            try:
                # Use external client or fresh client
                if self._external_client is not None:
                    response = await self._external_client.get(url, params=params, headers=merged_headers)
                else:
                    async with httpx.AsyncClient(timeout=self._timeout, headers=merged_headers) as client:
                        response = await client.get(url, params=params)

                status_code = response.status_code

                # 1. Successful Response
                if status_code == 200:
                    try:
                        return response.json()
                    except (json.JSONDecodeError, ValueError) as json_err:
                        logger.error(f"Malformed JSON from {url}: {json_err}. Raw preview: {response.text[:200]}")
                        raise MalformedResponseError(
                            f"Received non-JSON or malformed payload from {url}",
                            details={"status_code": status_code, "body_preview": response.text[:200]}
                        ) from json_err

                # 2. Rate Limited (429)
                if status_code == 429:
                    retry_after = self.retry_policy.parse_retry_after(response.headers.get("Retry-After"))
                    logger.warning(f"HTTP 429 Rate Limited from {url}. Retry-After: {retry_after}s")
                    if attempt <= self.retry_policy.max_retries:
                        delay = self.retry_policy.calculate_delay(attempt, retry_after=retry_after)
                        logger.info(f"Backing off for {delay:.2f}s before retry {attempt}...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise RateLimitExceededError(
                            f"Rate limit exceeded for {url} after {attempt} attempts",
                            retry_after=retry_after,
                            details={"status_code": 429, "url": url}
                        )

                # 3. Server Errors (5xx)
                if self.retry_policy.is_retryable_status(status_code):
                    logger.warning(f"HTTP {status_code} Server Error from {url} on attempt {attempt}")
                    if attempt <= self.retry_policy.max_retries:
                        delay = self.retry_policy.calculate_delay(attempt)
                        logger.info(f"Backing off for {delay:.2f}s before retry {attempt}...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise TemporarySourceError(
                            f"Server returned HTTP {status_code} for {url} after {attempt} attempts",
                            details={"status_code": status_code, "url": url}
                        )

                # 4. Permanent Client Errors (400, 401, 403, 404, etc.)
                logger.error(f"HTTP {status_code} Permanent Client Error for {url}")
                raise PermanentSourceError(
                    f"Permanent HTTP {status_code} error from source: {url}",
                    details={"status_code": status_code, "url": url, "body": response.text[:200]}
                )

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as timeout_err:
                logger.warning(f"HTTP Timeout for {url} on attempt {attempt}: {timeout_err}")
                if attempt <= self.retry_policy.max_retries:
                    delay = self.retry_policy.calculate_delay(attempt)
                    logger.info(f"Backing off for {delay:.2f}s after timeout...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise HttpTimeoutError(
                        f"Request to {url} timed out after {attempt} attempts",
                        details={"url": url, "error": str(timeout_err)}
                    ) from timeout_err

            except (httpx.ConnectError, httpx.NetworkError) as conn_err:
                logger.warning(f"Network/Connection error for {url} on attempt {attempt}: {conn_err}")
                if attempt <= self.retry_policy.max_retries:
                    delay = self.retry_policy.calculate_delay(attempt)
                    logger.info(f"Backing off for {delay:.2f}s after connection error...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise TemporarySourceError(
                        f"Network connection failed for {url} after {attempt} attempts",
                        details={"url": url, "error": str(conn_err)}
                    ) from conn_err

        # Exhausted retries fallback
        raise TemporarySourceError(f"HTTP request exhausted retries for {url}")
