import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import logging
from sqlalchemy import text
from app.database import engine, Base
from app.config import get_settings
import app.models # Register all models to Base.metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrations")

async def run_migrations():
    settings = get_settings()
    logger.info(f"Running database migrations for target: {settings.ENVIRONMENT}")
    
    async with engine.begin() as conn:
        # Create all tables defined in SQLAlchemy ORM models
        logger.info("Synchronizing ORM schema...")
        await conn.run_sync(Base.metadata.create_all)
        
        # Seed default sources if they don't exist
        logger.info("Seeding default sources...")
        from app.models.source import Source
        # Check if sources exist
        result = await conn.execute(text("SELECT COUNT(*) FROM sources"))
        count = result.scalar()
        if count == 0:
            await conn.execute(
                text("""
                INSERT INTO sources (name, slug, base_url, rate_limit_rps, is_active, created_at, updated_at)
                VALUES 
                    ('greenhouse', 'greenhouse', 'https://boards-api.greenhouse.io/v1/boards', 2.0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('lever', 'lever', 'https://api.lever.co/v0/postings', 2.0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """)
            )
            logger.info("Default sources seeded successfully (greenhouse, lever).")
        else:
            logger.info(f"Sources table already contains {count} sources.")
            
    logger.info("Migrations completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_migrations())
