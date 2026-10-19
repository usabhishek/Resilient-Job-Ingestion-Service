"""Admin dashboard and admin-only API: users, everyone's ingestions, bulk deletes."""
import math
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo.database import Database
from app.auth import current_user_or_none, require_admin
from app.database import get_db, run_db
from app.services import users as user_service
from app.services.analytics import runs_per_user
from app.services.ingestion import shared_pipeline
from app.services.repository import Doc, JobRepository
from fastapi import Request

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(request: Request, user: Doc | None = Depends(current_user_or_none)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role != "admin":
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_dashboard.html",
                                      context={"user": user})


@router.get("/api/admin/summary", tags=["Admin"])
async def summary(admin: Doc = Depends(require_admin), db: Database = Depends(get_db)):
    """Totals plus the health of the upstream job APIs (admin only)."""
    gh = await shared_pipeline.get_health("greenhouse")
    lv = await shared_pipeline.get_health("lever")
    return {
        "users": await run_db(db.users.count_documents, {}),
        "jobs": await run_db(db.jobs.count_documents, {}),
        "runs": await run_db(db.ingestion_runs.count_documents, {}),
        "sources": {
            "greenhouse": {"healthy": gh.is_healthy, "latency_ms": gh.latency_ms, "message": gh.message},
            "lever": {"healthy": lv.is_healthy, "latency_ms": lv.latency_ms, "message": lv.message},
        },
    }


@router.get("/api/admin/users", tags=["Admin"])
async def list_users(admin: Doc = Depends(require_admin), db: Database = Depends(get_db)):
    """READ: all users with their job and ingestion counts."""
    return await run_db(user_service.users_with_counts, db)


@router.delete("/api/admin/users/{user_id}", tags=["Admin"])
async def delete_user(user_id: str, admin: Doc = Depends(require_admin), db: Database = Depends(get_db)):
    """DELETE a user together with all of their jobs, runs and sessions."""
    target = await run_db(user_service.get_by_id, db, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted here.")
    await run_db(user_service.delete_user_and_data, db, user_id)
    return {"detail": f"Deleted {target.email} and all of their data."}


@router.delete("/api/admin/users/{user_id}/ingestions", tags=["Admin"])
async def clear_user_ingestions(user_id: str, admin: Doc = Depends(require_admin),
                                db: Database = Depends(get_db)):
    """Delete every job and ingestion run of ONE user (the account stays)."""
    if not await run_db(user_service.get_by_id, db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    jobs, runs = await run_db(user_service.clear_ingestions, db, user_id)
    return {"detail": f"Deleted {jobs} jobs and {runs} ingestion runs.", "jobs": jobs, "runs": runs}


@router.delete("/api/admin/ingestions", tags=["Admin"])
async def clear_all_ingestions(admin: Doc = Depends(require_admin), db: Database = Depends(get_db)):
    """Delete every job and ingestion run of EVERYONE (accounts stay)."""
    jobs, runs = await run_db(user_service.clear_ingestions, db, None)
    return {"detail": f"Deleted {jobs} jobs and {runs} ingestion runs for everyone.",
            "jobs": jobs, "runs": runs}


@router.get("/api/admin/runs", tags=["Admin"])
async def list_all_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    admin: Doc = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Every user's ingestion runs, page by page, with the user's name."""
    runs, total = await run_db(JobRepository.list_recent_runs, db, None, page, limit)
    owners = {u["_id"]: u for u in await run_db(
        lambda: list(db.users.find({"_id": {"$in": list({r.owner_id for r in runs})}})))}
    items = [{
        "id": r.id, "user_name": owners.get(r.owner_id, {}).get("name", "(deleted user)"),
        "user_email": owners.get(r.owner_id, {}).get("email", ""),
        "source": r.source_id, "fallback_source": r.fallback_source_id,
        "status": r.status, "fetched": r.fetched_count, "new": r.new_count,
        "duplicates": r.duplicate_count, "failed": r.failed_count,
        "duration_ms": r.duration_ms, "started_at": r.started_at,
    } for r in runs]
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, math.ceil(total / limit))}


@router.get("/api/admin/runs-per-user", tags=["Admin"])
async def runs_by_user(admin: Doc = Depends(require_admin), db: Database = Depends(get_db)):
    """Aggregation: ingestions per user."""
    return await run_db(runs_per_user, db)
