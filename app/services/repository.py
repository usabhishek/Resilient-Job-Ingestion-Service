import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.source import Source
from app.models.job import Job
from app.models.run import IngestionRun
from app.schemas.job import JobNormalized

logger = logging.getLogger("repository")

class JobRepository:
    """
    Data Access Layer for Sources, Jobs, and IngestionRuns.
    Enforces atomic operations, deduplication, and audit persistence.
    """

    @staticmethod
    async def get_or_create_source(
        session: AsyncSession,
        name: str,
        slug: str,
        base_url: str,
        rate_limit_rps: float = 2.0
    ) -> Source:
        """Retrieves an existing source or inserts a new one."""
        stmt = select(Source).options(selectinload(Source.jobs), selectinload(Source.runs)).where(Source.name == name)
        result = await session.execute(stmt)
        source = result.scalar_one_or_none()

        if not source:
            source = Source(
                name=name,
                slug=slug,
                base_url=base_url,
                rate_limit_rps=rate_limit_rps,
                is_active=True
            )
            session.add(source)
            await session.flush()
            # Eagerly initialize relationships
            source.jobs = []
            source.runs = []
        return source

    @staticmethod
    async def get_source_by_name(session: AsyncSession, name: str) -> Source | None:
        stmt = select(Source).options(selectinload(Source.jobs), selectinload(Source.runs)).where(Source.name == name)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_sources(session: AsyncSession) -> list[Source]:
        stmt = select(Source).options(selectinload(Source.jobs), selectinload(Source.runs)).order_by(Source.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def insert_jobs_batch(
        session: AsyncSession,
        source_id: int,
        normalized_jobs: list[JobNormalized]
    ) -> tuple[int, int, int]:
        """
        Inserts normalized jobs while enforcing deduplication against (source_id, external_id).
        Returns: (new_count, duplicate_count, failed_count)
        """
        if not normalized_jobs:
            return (0, 0, 0)

        # 1. Fetch existing external_ids for this source in batch
        external_ids = [job.external_id for job in normalized_jobs]
        existing_stmt = select(Job.external_id).where(
            Job.source_id == source_id,
            Job.external_id.in_(external_ids)
        )
        existing_result = await session.execute(existing_stmt)
        existing_ids = set(existing_result.scalars().all())

        new_count = 0
        duplicate_count = 0
        failed_count = 0

        now = datetime.now(timezone.utc)
        jobs_to_insert: list[Job] = []

        for job_data in normalized_jobs:
            if job_data.external_id in existing_ids:
                duplicate_count += 1
                continue

            # Prepare new Job entity
            try:
                job_entity = Job(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    external_id=job_data.external_id,
                    title=job_data.title,
                    company=job_data.company,
                    location=job_data.location,
                    description=job_data.description,
                    job_url=job_data.job_url,
                    posted_at=job_data.posted_at,
                    raw_payload=job_data.raw_payload,
                    is_active=True,
                    created_at=now,
                    updated_at=now
                )
                jobs_to_insert.append(job_entity)
                existing_ids.add(job_data.external_id) # Prevent in-batch duplicates
                new_count += 1
            except Exception as e:
                logger.error(f"Failed to prepare job {job_data.external_id}: {e}")
                failed_count += 1

        if jobs_to_insert:
            session.add_all(jobs_to_insert)
            await session.flush()

        return (new_count, duplicate_count, failed_count)

    @staticmethod
    async def list_jobs(
        session: AsyncSession,
        source_id: int | None = None,
        company: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20
    ) -> tuple[list[Job], int]:
        """Lists jobs with optional filtering, search, and pagination."""
        stmt = select(Job).options(selectinload(Job.source))
        count_stmt = select(func.count(Job.id))

        if source_id:
            stmt = stmt.where(Job.source_id == source_id)
            count_stmt = count_stmt.where(Job.source_id == source_id)

        if company:
            stmt = stmt.where(Job.company.ilike(f"%{company}%"))
            count_stmt = count_stmt.where(Job.company.ilike(f"%{company}%"))

        if search:
            search_filter = or_(
                Job.title.ilike(f"%{search}%"),
                Job.company.ilike(f"%{search}%"),
                Job.location.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        # Count total matching
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * limit
        stmt = stmt.order_by(desc(Job.created_at)).offset(offset).limit(limit)
        result = await session.execute(stmt)
        jobs = list(result.scalars().all())

        return jobs, total

    @staticmethod
    async def create_ingestion_run(
        session: AsyncSession,
        source_id: int,
        trigger_type: str = "MANUAL"
    ) -> IngestionRun:
        run = IngestionRun(
            id=str(uuid.uuid4()),
            source_id=source_id,
            trigger_type=trigger_type,
            status="RUNNING",
            started_at=datetime.now(timezone.utc)
        )
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    async def complete_ingestion_run(
        session: AsyncSession,
        run_id: str,
        status: str,
        fetched_count: int,
        valid_count: int,
        invalid_count: int,
        new_count: int,
        duplicate_count: int,
        failed_count: int,
        fallback_source_id: int | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None
    ) -> IngestionRun:
        stmt = select(IngestionRun).options(selectinload(IngestionRun.source), selectinload(IngestionRun.fallback_source)).where(IngestionRun.id == run_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()

        if run:
            finished = datetime.now(timezone.utc)
            started = run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration_ms = max(0, int((finished - started).total_seconds() * 1000))
            
            run.status = status
            run.fallback_source_id = fallback_source_id
            run.finished_at = finished
            run.duration_ms = duration_ms
            run.fetched_count = fetched_count
            run.valid_count = valid_count
            run.invalid_count = invalid_count
            run.new_count = new_count
            run.duplicate_count = duplicate_count
            run.failed_count = failed_count
            run.error_message = error_message
            run.error_details = error_details
            await session.flush()
        return run

    @staticmethod
    async def list_recent_runs(session: AsyncSession, limit: int = 15) -> list[IngestionRun]:
        stmt = select(IngestionRun).options(selectinload(IngestionRun.source), selectinload(IngestionRun.fallback_source)).order_by(desc(IngestionRun.started_at)).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_dashboard_metrics(session: AsyncSession) -> dict[str, Any]:
        total_jobs_res = await session.execute(select(func.count(Job.id)))
        total_jobs = total_jobs_res.scalar() or 0

        total_runs_res = await session.execute(select(func.count(IngestionRun.id)))
        total_runs = total_runs_res.scalar() or 0

        recent_run_stmt = select(IngestionRun).order_by(desc(IngestionRun.started_at)).limit(1)
        recent_run_res = await session.execute(recent_run_stmt)
        last_run = recent_run_res.scalar_one_or_none()

        return {
            "total_jobs": total_jobs,
            "total_runs": total_runs,
            "last_run": last_run
        }
