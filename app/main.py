import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.database import engine, Base
from app.api.routes_api import router as api_router
from app.api.routes_views import router as views_router
from app.models.source import Source
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize tables and seed default sources
    logger.info("Initializing database schema and default sources...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Check default sources
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source))
        sources = result.scalars().all()
        if not sources:
            logger.info("Seeding initial sources (greenhouse, lever)...")
            gh = Source(
                name="greenhouse",
                slug="greenhouse",
                base_url="https://boards-api.greenhouse.io/v1/boards",
                rate_limit_rps=2.0,
                is_active=True
            )
            lv = Source(
                name="lever",
                slug="lever",
                base_url="https://api.lever.co/v0/postings",
                rate_limit_rps=2.0,
                is_active=True
            )
            session.add_all([gh, lv])
            await session.commit()
            logger.info("Default sources seeded successfully.")

    yield
    # Shutdown: dispose DB connection pool
    logger.info("Disposing database connection pool...")
    await engine.dispose()

settings = get_settings()

app = FastAPI(
    title="Acdyon Job Ingestion Service",
    description="Resilient, source-abstracted job ingestion engine with rate pacing and exponential retry.",
    version="1.0.0",
    lifespan=lifespan
)

# Mount Static Assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register Routers
app.include_router(api_router)
app.include_router(views_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
