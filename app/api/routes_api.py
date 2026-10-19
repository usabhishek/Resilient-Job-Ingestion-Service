import math
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from pymongo.database import Database
from app.auth import require_user
from app.database import get_db, run_db
from app.schemas.run import IngestRequest, IngestionSummary, IngestionRunResponse
from app.schemas.job import JobResponse, JobListResponse
from app.services.repository import Doc, JobRepository, now
from app.services.analytics import all_analytics
from app.services.ingestion import shared_pipeline
from app.core.exceptions import PermanentSourceError

router = APIRouter()
pipeline = shared_pipeline


class JobUpdate(BaseModel):
    """Fields a client may change on an existing job."""
    title: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = None
    is_active: bool | None = None
    applied: bool | None = Field(default=None, description="true = mark as applied, false = undo")


class BulkDelete(BaseModel):
    """Several job ids to delete in one request."""
    ids: list[str] = Field(..., min_length=1, max_length=100)


def to_job_response(j) -> JobResponse:
    return JobResponse(
        id=j.id, source_id=j.source_id, source_name=j.source_id,
        external_id=j.external_id, title=j.title, company=j.company,
        location=j.location, description=j.description, job_url=j.job_url,
        posted_at=j.posted_at, applied_at=j.get("applied_at"), created_at=j.created_at, updated_at=j.updated_at,
    )


@router.get("/health", tags=["Health"])
async def health_check(db: Database = Depends(get_db)):
    """Public liveness check for hosting platforms (database status only)."""
    db_status = "healthy"
    try:
        await run_db(db.command, "ping")
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    return {"status": "ok" if db_status == "healthy" else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(), "database": db_status}


@router.post("/api/ingest", response_model=IngestionSummary, tags=["Ingestion"])
async def trigger_ingestion(request: IngestRequest, user: Doc = Depends(require_user),
                            db: Database = Depends(get_db)):
    """Fetch jobs for the logged-in user. Everything is saved under this user only."""
    try:
        summary = await pipeline.run_ingestion(
            db=db,
            owner_id=user.id,
            source_name=request.source,
            board_token=request.board_token,
            allow_fallback=request.allow_fallback,
            trigger_type="API",
            posted_within_days=request.posted_within_days,
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


# ------------------------------------------------------------------ JOBS (CRUD)
@router.get("/api/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_jobs(
    source_id: str | None = Query(None, description="Filter by source (greenhouse / lever)"),
    company: str | None = Query(None, description="Filter by company name"),
    search: str | None = Query(None, description="Search title / company / location"),
    applied: bool | None = Query(None, description="true = only jobs I applied to, false = not applied yet"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Jobs per page"),
    user: Doc = Depends(require_user),
    db: Database = Depends(get_db),
):
    """READ: my jobs, page by page. Use `page` to reach every record."""
    jobs, total = await run_db(JobRepository.list_jobs, db, user.id, source_id, company, search, page, limit, applied)
    pages = max(1, math.ceil(total / limit))
    return JobListResponse(items=[to_job_response(j) for j in jobs], total=total,
                           page=page, limit=limit, pages=pages)


@router.get("/api/jobs/{job_id}", response_model=JobResponse, tags=["Jobs"])
async def get_job(job_id: str, user: Doc = Depends(require_user), db: Database = Depends(get_db)):
    job = await run_db(JobRepository.get_job, db, user.id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return to_job_response(job)


@router.patch("/api/jobs/{job_id}", response_model=JobResponse, tags=["Jobs"])
async def update_job(job_id: str, body: JobUpdate, user: Doc = Depends(require_user),
                     db: Database = Depends(get_db)):
    """UPDATE: change title / location / is_active, or mark the job as applied (applied=true / false)."""
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "applied" in changes:                       # stored as the date of applying (null = not applied)
        changes["applied_at"] = now() if changes.pop("applied") else None
    if not await run_db(JobRepository.get_job, db, user.id, job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = await run_db(JobRepository.update_job, db, user.id, job_id, changes)
    return to_job_response(job)


@router.delete("/api/jobs/{job_id}", status_code=204, tags=["Jobs"])
async def delete_job(job_id: str, user: Doc = Depends(require_user), db: Database = Depends(get_db)):
    """DELETE: remove one of my jobs."""
    if not await run_db(JobRepository.delete_job, db, user.id, job_id):
        raise HTTPException(status_code=404, detail="Job not found")


@router.post("/api/jobs/bulk-delete", tags=["Jobs"])
async def bulk_delete_jobs(body: BulkDelete, user: Doc = Depends(require_user),
                           db: Database = Depends(get_db)):
    """DELETE several of my jobs at once (up to 100). Returns how many were deleted."""
    deleted = await run_db(JobRepository.delete_jobs, db, user.id, body.ids)
    return {"deleted": deleted}


# ----------------------------------------------------------------------- RUNS
@router.get("/api/runs", response_model=list[IngestionRunResponse], tags=["Ingestion"])
async def list_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user: Doc = Depends(require_user),
    db: Database = Depends(get_db),
):
    """My ingestion history, page by page."""
    runs, _ = await run_db(JobRepository.list_recent_runs, db, user.id, page, limit)
    return [to_run_response(r) for r in runs]


def to_run_response(r) -> IngestionRunResponse:
    return IngestionRunResponse(
        id=r.id, source_id=r.source_id, source_name=r.source_id,
        fallback_source_id=r.fallback_source_id, fallback_source_name=r.fallback_source_id,
        trigger_type=r.trigger_type, status=r.status, started_at=r.started_at,
        finished_at=r.finished_at, duration_ms=r.duration_ms,
        fetched_count=r.fetched_count, valid_count=r.valid_count,
        invalid_count=r.invalid_count, new_count=r.new_count,
        duplicate_count=r.duplicate_count, failed_count=r.failed_count,
        error_message=r.error_message, error_details=r.error_details,
        created_at=r.started_at,
    )


@router.get("/api/analytics", tags=["Analytics"])
async def analytics(user: Doc = Depends(require_user), db: Database = Depends(get_db)):
    """Aggregation pipeline results for MY data (admin sees everyone's)."""
    owner = None if user.role == "admin" else user.id
    return await run_db(all_analytics, db, owner)
