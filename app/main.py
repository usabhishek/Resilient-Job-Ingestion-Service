import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.database import get_client, get_database, setup_database, run_db
from app.services.users import seed_admin
from app.api.routes_api import router as api_router
from app.api.routes_views import router as views_router
from app.api.routes_auth import router as auth_router
from app.api.routes_admin import router as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create collections, validation rules, indexes and seed default sources
    logger.info("Connecting to MongoDB and preparing collections...")
    db = get_database()
    await run_db(setup_database, db)
    cfg = get_settings()
    if await run_db(seed_admin, db, cfg.ADMIN_EMAIL, cfg.ADMIN_PASSWORD):
        logger.info("Admin account created for %s", cfg.ADMIN_EMAIL)
    elif not cfg.ADMIN_EMAIL:
        logger.warning("ADMIN_EMAIL / ADMIN_PASSWORD not set - no admin account exists.")
    yield
    # Shutdown: close MongoDB connection
    logger.info("Closing MongoDB connection...")
    get_client().close()


settings = get_settings()

app = FastAPI(
    title="Acdyon Job Ingestion Service",
    description="Resilient, source-abstracted job ingestion engine (FastAPI + PyMongo + MongoDB).",
    version="3.0.0",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_router)
app.include_router(views_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
