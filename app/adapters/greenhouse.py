import time
import logging
from datetime import datetime, timezone
from typing import Any
from app.adapters.base import JobSource, SourceHealthResult
from app.schemas.job import JobNormalized
from app.core.exceptions import MalformedResponseError, SchemaValidationError

logger = logging.getLogger("greenhouse_adapter")

class GreenhouseSource(JobSource):
    """
    Primary Ingestion Adapter for Greenhouse Public Job Board API.
    """
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    def source_name(self) -> str:
        return "greenhouse"

    async def fetch_raw_data(self, board_token: str) -> list[dict[str, Any]]:
        """
        Fetches public jobs list for a given company board token.
        Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
        """
        clean_token = board_token.strip().lower()
        url = f"{self.BASE_URL}/{clean_token}/jobs"
        params = {"content": "true"}

        data = await self.http_client.get_json(url, params=params)

        if not isinstance(data, dict) or "jobs" not in data:
            raise MalformedResponseError(
                f"Unexpected Greenhouse response structure from {url}",
                details={"received_type": type(data).__name__, "keys": list(data.keys()) if isinstance(data, dict) else []}
            )

        jobs_list = data.get("jobs", [])
        if not isinstance(jobs_list, list):
            raise MalformedResponseError(f"Greenhouse 'jobs' field is not a list in {url}")

        return jobs_list

    def normalize_item(self, raw_item: dict[str, Any], board_token: str) -> JobNormalized:
        """
        Normalizes a raw Greenhouse job dict into JobNormalized.
        """
        if not isinstance(raw_item, dict):
            raise SchemaValidationError("Raw item is not a dictionary", details={"item": str(raw_item)})

        raw_id = raw_item.get("id")
        if raw_id is None:
            raise SchemaValidationError("Greenhouse item missing required 'id' field", details={"item": raw_item})

        title = raw_item.get("title")
        if not title:
            raise SchemaValidationError("Greenhouse item missing required 'title' field", details={"id": str(raw_id)})

        # Extract location
        loc_data = raw_item.get("location")
        location_str = "Remote / Unspecified"
        if isinstance(loc_data, dict):
            location_str = loc_data.get("name") or location_str
        elif isinstance(loc_data, str) and loc_data.strip():
            location_str = loc_data.strip()

        # Job URL
        job_url = raw_item.get("absolute_url") or f"https://boards.greenhouse.io/{board_token}/jobs/{raw_id}"

        # Parse posted / updated timestamp
        posted_at = None
        ts_str = raw_item.get("updated_at") or raw_item.get("created_at")
        if ts_str:
            try:
                posted_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                posted_at = None

        company_name = board_token.replace("-", " ").replace("_", " ").title()

        return JobNormalized(
            external_id=str(raw_id),
            source="greenhouse",
            title=str(title).strip(),
            company=company_name,
            location=location_str,
            description=raw_item.get("content"),
            job_url=str(job_url).strip(),
            posted_at=posted_at,
            raw_payload=raw_item
        )

    async def health_check(self) -> SourceHealthResult:
        """
        Verifies connectivity to Greenhouse API using a fast-fail lightweight check.
        Strict 3.0s timeout with 0 retries to prevent blocking dashboard/health endpoints.
        """
        start = time.perf_counter()
        try:
            # If http_client has a mock client injected in tests, use it
            if self.http_client._external_client is not None:
                await self.http_client.get_json(f"{self.BASE_URL}/cloudflare/jobs", params={"content": "false"})
                latency = (time.perf_counter() - start) * 1000.0
                return SourceHealthResult(
                    source_name="greenhouse",
                    is_healthy=True,
                    latency_ms=round(latency, 2),
                    status_code=200,
                    message="Greenhouse API is responsive."
                )
            
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=2.0), headers={"User-Agent": "AcdyonHealth/1.0", "Accept": "application/json"}) as client:
                resp = await client.get(f"{self.BASE_URL}/cloudflare/jobs", params={"content": "false"})
                latency = (time.perf_counter() - start) * 1000.0
                is_ok = resp.status_code == 200
                return SourceHealthResult(
                    source_name="greenhouse",
                    is_healthy=is_ok,
                    latency_ms=round(latency, 2),
                    status_code=resp.status_code,
                    message="Greenhouse API is responsive." if is_ok else f"Greenhouse returned HTTP {resp.status_code}"
                )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000.0
            return SourceHealthResult(
                source_name="greenhouse",
                is_healthy=False,
                latency_ms=round(latency, 2),
                message=f"Greenhouse health check failed: {str(e)}"
            )
