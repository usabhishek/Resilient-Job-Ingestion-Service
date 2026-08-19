import math
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.schemas.run import IngestRequest, IngestionSummary, IngestionRunResponse
from app.schemas.job import JobResponse, JobListResponse
from app.schemas.source import SourceResponse, SourceHealthResponse
from app.services.repository import JobRepository
from app.services.ingestion import shared_pipeline
from app.core.exceptions import PermanentSourceError

router = APIRouter()
pipeline = shared_pipeline

@router.get("/health", tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Service & Database Health Status endpoint.
    """
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Cached, fast-fail source health pings
    gh_health = await pipeline.get_health("greenhouse")
    lv_health = await pipeline.get_health("lever")

    is_overall_healthy = db_status == "healthy"

    return {
        "status": "ok" if is_overall_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "sources": {
            "greenhouse": {
                "healthy": gh_health.is_healthy,
                "latency_ms": gh_health.latency_ms,
                "message": gh_health.message
            },
            "lever": {
                "healthy": lv_health.is_healthy,
                "latency_ms": lv_health.latency_ms,
                "message": lv_health.message
            }
        }
    }

@router.post("/api/ingest", response_model=IngestionSummary, tags=["Ingestion"])
async def trigger_ingestion(
    request: IngestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers an on-demand job ingestion run.
    """
    try:
        summary = await pipeline.run_ingestion(
            session=db,
            source_name=request.source,
            board_token=request.board_token,
            allow_fallback=request.allow_fallback,
            trigger_type="API"
        )
        if summary.status == "FAILED" and summary.error_message and "permanent" in summary.error_message.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=summary.error_message)
        return summary
    except (ValueError, PermanentSourceError) as client_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(client_err))
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion failed: {str(err)}")

@router.get("/api/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_jobs(
    source_id: int | None = Query(None, description="Filter by Source ID"),
    company: str | None = Query(None, description="Filter by Company Name"),
    search: str | None = Query(None, description="Full search term for title/company/location"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves normalized job listings with filtering and pagination.
    """
    jobs, total = await JobRepository.list_jobs(
        session=db,
        source_id=source_id,
        company=company,
        search=search,
        page=page,
        limit=limit
    )

    items = [
        JobResponse(
            id=j.id,
            source_id=j.source_id,
            source_name=j.source.name if j.source else None,
            external_id=j.external_id,
            title=j.title,
            company=j.company,
            location=j.location,
            description=j.description,
            job_url=j.job_url,
            posted_at=j.posted_at,
            created_at=j.created_at,
            updated_at=j.updated_at
        )
        for j in jobs
    ]

    pages = math.ceil(total / limit) if total > 0 else 1

    return JobListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )

@router.get("/api/sources", response_model=list[SourceResponse], tags=["Sources"])
async def list_sources(db: AsyncSession = Depends(get_db)):
    """
    Retrieves all configured sources and their current status.
    """
    sources = await JobRepository.get_all_sources(db)
    response = []
    for s in sources:
        # Count total jobs for source
        jobs_count = len(s.jobs) if s.jobs else 0
        last_run = s.runs[0] if s.runs else None
        response.append(
            SourceResponse(
                id=s.id,
                name=s.name,
                slug=s.slug,
                base_url=s.base_url,
                is_active=s.is_active,
                rate_limit_rps=s.rate_limit_rps,
                created_at=s.created_at,
                updated_at=s.updated_at,
                total_jobs=jobs_count,
                last_run_status=last_run.status if last_run else None,
                last_run_at=last_run.started_at if last_run else None
            )
        )
    return response

@router.get("/api/runs", response_model=list[IngestionRunResponse], tags=["Ingestion"])
async def list_runs(
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves recent ingestion run logs.
    """
    runs = await JobRepository.list_recent_runs(db, limit=limit)
    return [
        IngestionRunResponse(
            id=r.id,
            source_id=r.source_id,
            source_name=r.source.name if r.source else None,
            fallback_source_id=r.fallback_source_id,
            fallback_source_name=r.fallback_source.name if r.fallback_source else None,
            trigger_type=r.trigger_type,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            duration_ms=r.duration_ms,
            fetched_count=r.fetched_count,
            valid_count=r.valid_count,
            invalid_count=r.invalid_count,
            new_count=r.new_count,
            duplicate_count=r.duplicate_count,
            failed_count=r.failed_count,
            error_message=r.error_message,
            error_details=r.error_details,
            created_at=r.created_at
        )
        for r in runs
    ]
