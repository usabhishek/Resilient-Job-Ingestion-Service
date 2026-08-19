from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.repository import JobRepository
from app.services.ingestion import shared_pipeline

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
pipeline = shared_pipeline

@router.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard_view(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Renders the operational Job Ingestion dashboard.
    """
    # Fetch metrics
    metrics = await JobRepository.get_dashboard_metrics(db)
    sources = await JobRepository.get_all_sources(db)
    recent_runs = await JobRepository.list_recent_runs(db, limit=10)
    jobs, total_jobs_count = await JobRepository.list_jobs(db, page=1, limit=15)

    # Cached, fast-fail health checks
    gh_health = await pipeline.get_health("greenhouse")
    lv_health = await pipeline.get_health("lever")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "metrics": metrics,
            "sources": sources,
            "recent_runs": recent_runs,
            "jobs": jobs,
            "total_jobs_count": total_jobs_count,
            "health": {
                "greenhouse": gh_health,
                "lever": lv_health
            }
        }
    )
