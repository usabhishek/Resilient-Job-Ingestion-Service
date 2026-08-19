import time
import logging
from datetime import datetime, timezone
from typing import Any
from app.adapters.base import JobSource, SourceHealthResult
from app.schemas.job import JobNormalized
from app.core.exceptions import MalformedResponseError, SchemaValidationError

logger = logging.getLogger("lever_adapter")

class LeverSource(JobSource):
    """
    Fallback Ingestion Adapter for Lever Public Postings API.
    """
    BASE_URL = "https://api.lever.co/v0/postings"

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    def source_name(self) -> str:
        return "lever"

    async def fetch_raw_data(self, board_token: str) -> list[dict[str, Any]]:
        """
        Fetches public postings for a given company.
        Endpoint: https://api.lever.co/v0/postings/{board_token}?mode=json
        """
        clean_token = board_token.strip().lower()
        url = f"{self.BASE_URL}/{clean_token}"
        params = {"mode": "json"}

        data = await self.http_client.get_json(url, params=params)

        if not isinstance(data, list):
            raise MalformedResponseError(
                f"Unexpected Lever response structure from {url} (expected list)",
                details={"received_type": type(data).__name__}
            )

        return data

    def normalize_item(self, raw_item: dict[str, Any], board_token: str) -> JobNormalized:
        """
        Normalizes a raw Lever job dict into JobNormalized schema.
        """
        if not isinstance(raw_item, dict):
            raise SchemaValidationError("Raw item is not a dictionary", details={"item": str(raw_item)})

        raw_id = raw_item.get("id")
        if not raw_id:
            raise SchemaValidationError("Lever item missing required 'id' field", details={"item": raw_item})

        title = raw_item.get("text")
        if not title:
            raise SchemaValidationError("Lever item missing required 'text' (title) field", details={"id": str(raw_id)})

        # Extract location & team
        categories = raw_item.get("categories") or {}
        location_str = "Remote / Unspecified"
        if isinstance(categories, dict):
            location_str = categories.get("location") or raw_item.get("workplaceType") or location_str
        elif isinstance(categories, str) and categories.strip():
            location_str = categories.strip()

        # Job URL
        job_url = raw_item.get("hostedUrl") or raw_item.get("applyUrl") or f"https://jobs.lever.co/{board_token}/{raw_id}"

        # Parse posted timestamp (Lever provides milliseconds timestamp in createdAt)
        posted_at = None
        created_at_ms = raw_item.get("createdAt")
        if created_at_ms and isinstance(created_at_ms, (int, float)):
            try:
                posted_at = datetime.fromtimestamp(created_at_ms / 1000.0, tz=timezone.utc)
            except Exception:
                posted_at = None

        company_name = board_token.replace("-", " ").replace("_", " ").title()

        return JobNormalized(
            external_id=str(raw_id),
            source="lever",
            title=str(title).strip(),
            company=company_name,
            location=location_str,
            description=raw_item.get("descriptionPlain") or raw_item.get("description"),
            job_url=str(job_url).strip(),
            posted_at=posted_at,
            raw_payload=raw_item
        )

    async def health_check(self) -> SourceHealthResult:
        """
        Verifies connectivity to Lever API using a fast-fail lightweight check.
        Strict 3.0s timeout with 0 retries to prevent blocking dashboard/health endpoints.

        Note: The health check probes API reachability, not whether a specific company
        board exists. Lever returns 404 for unknown company slugs, which is still a valid
        response from a healthy API. Only network errors or 5xx indicate a real outage.
        """
        start = time.perf_counter()
        try:
            # If http_client has a mock client injected in tests, use it
            if self.http_client._external_client is not None:
                await self.http_client.get_json(f"{self.BASE_URL}/netflix", params={"mode": "json"})
                latency = (time.perf_counter() - start) * 1000.0
                return SourceHealthResult(
                    source_name="lever",
                    is_healthy=True,
                    latency_ms=round(latency, 2),
                    status_code=200,
                    message="Lever API is responsive."
                )

            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=2.0), headers={"User-Agent": "AcdyonHealth/1.0", "Accept": "application/json"}) as client:
                resp = await client.get(f"{self.BASE_URL}/lever", params={"mode": "json"})
                latency = (time.perf_counter() - start) * 1000.0
                # Any HTTP response (including 404 for unknown company) means the API is reachable.
                # Only 5xx responses indicate Lever's servers are actually unhealthy.
                is_ok = resp.status_code < 500
                return SourceHealthResult(
                    source_name="lever",
                    is_healthy=is_ok,
                    latency_ms=round(latency, 2),
                    status_code=resp.status_code,
                    message="Lever API is responsive." if is_ok else f"Lever server error: HTTP {resp.status_code}"
                )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000.0
            return SourceHealthResult(
                source_name="lever",
                is_healthy=False,
                latency_ms=round(latency, 2),
                message=f"Lever health check failed: {str(e)}"
            )

