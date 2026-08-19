import logging
import time
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.adapters.base import JobSource, SourceHealthResult
from app.adapters.greenhouse import GreenhouseSource
from app.adapters.lever import LeverSource
from app.core.http_client import ResilientHttpClient
from app.core.exceptions import (
    TemporarySourceError,
    HttpTimeoutError,
    RateLimitExceededError,
    MalformedResponseError,
    PermanentSourceError,
    SchemaValidationError
)
from app.schemas.job import JobNormalized
from app.schemas.run import IngestionSummary
from app.services.repository import JobRepository

logger = logging.getLogger("ingestion_pipeline")


class IngestionPipeline:
    """
    Core Ingestion Orchestrator.
    Handles source execution, dynamic fallback switching, normalization,
    schema validation error tolerance, deduplication, and audit metrics.
    """

    def __init__(self, http_client: ResilientHttpClient | None = None):
        self.http_client = http_client or ResilientHttpClient()
        self.adapters: dict[str, JobSource] = {
            "greenhouse": GreenhouseSource(self.http_client),
            "lever": LeverSource(self.http_client)
        }
        self._health_cache: dict[str, tuple[float, SourceHealthResult]] = {}
        self._cache_ttl_seconds = 15.0

    async def get_health(self, source_name: str) -> SourceHealthResult:
        """
        Retrieves source health with a 15-second in-memory TTL cache
        to prevent blocking dashboard and /health requests.
        """
        clean_name = source_name.strip().lower()
        now = time.monotonic()

        if clean_name in self._health_cache:
            cached_time, cached_result = self._health_cache[clean_name]
            if now - cached_time < self._cache_ttl_seconds:
                return cached_result

        adapter = self.adapters.get(clean_name)
        if not adapter:
            result = SourceHealthResult(
                source_name=clean_name,
                is_healthy=False,
                latency_ms=0.0,
                message=f"Unknown source adapter: '{clean_name}'"
            )
        else:
            result = await adapter.health_check()

        self._health_cache[clean_name] = (now, result)
        return result

    async def run_ingestion(
        self,
        session: AsyncSession,
        source_name: str = "greenhouse",
        board_token: str = "cloudflare",
        allow_fallback: bool = True,
        trigger_type: str = "MANUAL"
    ) -> IngestionSummary:
        """
        Executes a complete ingestion cycle for a given source and company board.
        """
        start_time = time.perf_counter()
        clean_source_name = source_name.strip().lower()

        # 1. Validate Source Adapter Exists BEFORE any DB writes (prevents stray rows)
        active_adapter = self.adapters.get(clean_source_name)
        if not active_adapter:
            raise ValueError(f"Unknown source adapter: '{clean_source_name}'")

        # 2. Resolve Primary DB Source — base_url comes from the adapter, not hardcoded
        primary_source_db = await JobRepository.get_or_create_source(
            session,
            name=clean_source_name,
            slug=clean_source_name,
            base_url=active_adapter.base_url
        )

        # 3. Create Audit Ingestion Run Record
        run_record = await JobRepository.create_ingestion_run(
            session,
            source_id=primary_source_db.id,
            trigger_type=trigger_type
        )
        await session.commit()

        raw_items: list[dict[str, Any]] = []
        fallback_used = False
        fallback_source_db = None
        executed_adapter = active_adapter
        active_source_id = primary_source_db.id

        # 4. Fetch from Primary Source with Fallback Switching
        try:
            logger.info(f"Starting ingestion run {run_record.id} for {clean_source_name}:{board_token}")
            raw_items = await active_adapter.fetch_raw_data(board_token)

        except (TemporarySourceError, HttpTimeoutError, RateLimitExceededError, MalformedResponseError) as err:
            logger.warning(f"Primary source {clean_source_name} failed: {err}")

            # Eligible for fallback
            fallback_name = "lever" if clean_source_name == "greenhouse" else "greenhouse"
            if allow_fallback and fallback_name in self.adapters:
                logger.info(f"Switching to fallback adapter: {fallback_name}")
                fallback_used = True
                executed_adapter = self.adapters[fallback_name]
                fallback_source_db = await JobRepository.get_or_create_source(
                    session,
                    name=fallback_name,
                    slug=fallback_name,
                    base_url=executed_adapter.base_url  # derived from adapter, not hardcoded
                )
                active_source_id = fallback_source_db.id

                try:
                    raw_items = await executed_adapter.fetch_raw_data(board_token)
                except Exception as fb_err:
                    logger.error(f"Fallback source {fallback_name} also failed: {fb_err}")
                    error_msg = f"Primary ({clean_source_name}) failed: {err}. Fallback ({fallback_name}) failed: {fb_err}"
                    await JobRepository.complete_ingestion_run(
                        session,
                        run_id=run_record.id,
                        status="FAILED",
                        fetched_count=0,
                        valid_count=0,
                        invalid_count=0,
                        new_count=0,
                        duplicate_count=0,
                        failed_count=0,
                        fallback_source_id=fallback_source_db.id if fallback_source_db else None,
                        error_message=error_msg,
                        error_details={"primary_error": str(err), "fallback_error": str(fb_err)}
                    )
                    await session.commit()
                    return IngestionSummary(
                        run_id=run_record.id,
                        source_name=clean_source_name,
                        fallback_used=True,
                        fallback_source_name=fallback_name,
                        status="FAILED",
                        fetched_count=0,
                        valid_count=0,
                        invalid_count=0,
                        new_count=0,
                        duplicate_count=0,
                        failed_count=0,
                        duration_ms=int((time.perf_counter() - start_time) * 1000),
                        started_at=run_record.started_at,
                        error_message=error_msg
                    )
            else:
                # Fallback disabled or exhausted
                error_msg = f"Ingestion failed on {clean_source_name}: {err}"
                await JobRepository.complete_ingestion_run(
                    session,
                    run_id=run_record.id,
                    status="FAILED",
                    fetched_count=0,
                    valid_count=0,
                    invalid_count=0,
                    new_count=0,
                    duplicate_count=0,
                    failed_count=0,
                    error_message=error_msg,
                    error_details={"error": str(err)}
                )
                await session.commit()
                return IngestionSummary(
                    run_id=run_record.id,
                    source_name=clean_source_name,
                    fallback_used=False,
                    status="FAILED",
                    fetched_count=0,
                    valid_count=0,
                    invalid_count=0,
                    new_count=0,
                    duplicate_count=0,
                    failed_count=0,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                    started_at=run_record.started_at,
                    error_message=error_msg
                )

        except PermanentSourceError as perm_err:
            # Permanent errors (e.g. 404 bad board token) — do NOT trigger fallback
            logger.error(f"Permanent source error for {clean_source_name}: {perm_err}")
            error_msg = f"Permanent source error from {clean_source_name}: {perm_err}"
            await JobRepository.complete_ingestion_run(
                session,
                run_id=run_record.id,
                status="FAILED",
                fetched_count=0,
                valid_count=0,
                invalid_count=0,
                new_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=error_msg,
                error_details={"permanent_error": str(perm_err)}
            )
            await session.commit()
            return IngestionSummary(
                run_id=run_record.id,
                source_name=clean_source_name,
                fallback_used=False,
                status="FAILED",
                fetched_count=0,
                valid_count=0,
                invalid_count=0,
                new_count=0,
                duplicate_count=0,
                failed_count=0,
                duration_ms=int((time.perf_counter() - start_time) * 1000),
                started_at=run_record.started_at,
                error_message=error_msg
            )

        except Exception as unhandled_err:
            logger.error(f"Fatal error fetching from {clean_source_name}: {unhandled_err}")
            await JobRepository.complete_ingestion_run(
                session,
                run_id=run_record.id,
                status="FAILED",
                fetched_count=0,
                valid_count=0,
                invalid_count=0,
                new_count=0,
                duplicate_count=0,
                failed_count=0,
                error_message=str(unhandled_err)
            )
            await session.commit()
            raise

        fetched_count = len(raw_items)

        # 5. Handle Empty Responses Explicitly (valid 200 OK with 0 items — no fallback)
        if fetched_count == 0:
            logger.warning(f"Source {executed_adapter.source_name()} returned 0 jobs for board '{board_token}'")
            await JobRepository.complete_ingestion_run(
                session,
                run_id=run_record.id,
                status="EMPTY_RESPONSE",
                fetched_count=0,
                valid_count=0,
                invalid_count=0,
                new_count=0,
                duplicate_count=0,
                failed_count=0,
                fallback_source_id=fallback_source_db.id if fallback_used and fallback_source_db else None,
                error_message=f"Received empty job list from {executed_adapter.source_name()}"
            )
            await session.commit()
            return IngestionSummary(
                run_id=run_record.id,
                source_name=clean_source_name,
                fallback_used=fallback_used,
                fallback_source_name=executed_adapter.source_name() if fallback_used else None,
                status="EMPTY_RESPONSE",
                fetched_count=0,
                valid_count=0,
                invalid_count=0,
                new_count=0,
                duplicate_count=0,
                failed_count=0,
                duration_ms=int((time.perf_counter() - start_time) * 1000),
                started_at=run_record.started_at,
                error_message=f"Source returned empty job list for '{board_token}'"
            )

        # 6. Normalization & Schema Validation (error-tolerant, partial allowed)
        valid_jobs: list[JobNormalized] = []
        invalid_count = 0

        for raw_item in raw_items:
            try:
                normalized = executed_adapter.normalize_item(raw_item, board_token)
                valid_jobs.append(normalized)
            except (SchemaValidationError, ValueError, TypeError, KeyError) as val_err:
                # Expected validation failures from malformed upstream data
                invalid_count += 1
                logger.warning(f"Validation failure on item from {executed_adapter.source_name()}: {val_err}")
            except Exception as unexp_err:
                # Unexpected bugs in normalize_item — log with stack trace, don't silently drop
                invalid_count += 1
                logger.error(
                    f"Unexpected error normalizing item from {executed_adapter.source_name()}: {unexp_err}",
                    exc_info=True
                )

        valid_count = len(valid_jobs)

        # 7. Deduplication & Persistence
        new_count, duplicate_count, db_failed_count = await JobRepository.insert_jobs_batch(
            session,
            source_id=active_source_id,
            normalized_jobs=valid_jobs
        )

        total_failed_count = invalid_count + db_failed_count

        # 8. Determine Final Status
        if fallback_used:
            final_status = "FALLBACK_SUCCESS"
        elif invalid_count > 0 and valid_count > 0:
            final_status = "PARTIAL"
        elif valid_count == 0 and fetched_count > 0:
            final_status = "FAILED"
        else:
            final_status = "SUCCESS"

        # 9. Complete Ingestion Run in DB
        completed_run = await JobRepository.complete_ingestion_run(
            session,
            run_id=run_record.id,
            status=final_status,
            fetched_count=fetched_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            new_count=new_count,
            duplicate_count=duplicate_count,
            failed_count=total_failed_count,
            fallback_source_id=fallback_source_db.id if fallback_used and fallback_source_db else None
        )
        await session.commit()

        duration_ms = completed_run.duration_ms or int((time.perf_counter() - start_time) * 1000)

        logger.info(
            f"Ingestion completed for run {run_record.id} [{final_status}]: "
            f"Fetched={fetched_count}, Valid={valid_count}, Invalid={invalid_count}, "
            f"New={new_count}, Duplicates={duplicate_count}, Failed={total_failed_count} in {duration_ms}ms"
        )

        return IngestionSummary(
            run_id=run_record.id,
            source_name=clean_source_name,
            fallback_used=fallback_used,
            fallback_source_name=executed_adapter.source_name() if fallback_used else None,
            status=final_status,
            fetched_count=fetched_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            new_count=new_count,
            duplicate_count=duplicate_count,
            failed_count=total_failed_count,
            duration_ms=duration_ms,
            started_at=run_record.started_at,
            finished_at=completed_run.finished_at
        )


# Global shared pipeline instance — ensures a single rate limiter and httpx client pool
# is used across the API router and dashboard views router.
shared_pipeline = IngestionPipeline()
