"""MongoDB connection (PyMongo) + collection setup (validation rules and indexes)."""
import asyncio
import logging
from functools import lru_cache
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.database import Database
from app.config import get_settings

logger = logging.getLogger("database")

# --------------------------------------------------------------------------
# Validation rules ($jsonSchema). MongoDB rejects any insert/update that
# breaks these rules (validationAction = "error").
# --------------------------------------------------------------------------
SOURCES_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "name", "base_url", "is_active", "rate_limit_rps", "created_at"],
    "properties": {
        "_id": {"bsonType": "string", "minLength": 1},
        "name": {"bsonType": "string", "minLength": 1, "maxLength": 50},
        "base_url": {"bsonType": "string", "pattern": "^https?://"},
        "is_active": {"bsonType": "bool"},
        "rate_limit_rps": {"bsonType": ["double", "int"], "minimum": 0.1, "maximum": 100},
        "created_at": {"bsonType": "date"},
        "updated_at": {"bsonType": "date"},
    },
}

JOBS_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "owner_id", "source_id", "external_id", "title", "company",
                 "location", "job_url", "is_active", "created_at"],
    "properties": {
        "_id": {"bsonType": "string"},
        "owner_id": {"bsonType": "string", "minLength": 1},
        "source_id": {"enum": ["greenhouse", "lever"]},
        "external_id": {"bsonType": "string", "minLength": 1},
        "title": {"bsonType": "string", "minLength": 1, "maxLength": 255},
        "company": {"bsonType": "string", "minLength": 1, "maxLength": 100},
        "location": {"bsonType": "string"},
        "description": {"bsonType": ["string", "null"]},
        "job_url": {"bsonType": "string", "pattern": "^https?://"},
        "posted_at": {"bsonType": ["date", "null"]},
        "applied_at": {"bsonType": ["date", "null"]},
        "raw_payload": {"bsonType": ["object", "array", "null"]},
        "is_active": {"bsonType": "bool"},
        "created_at": {"bsonType": "date"},
        "updated_at": {"bsonType": "date"},
    },
}

RUNS_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "owner_id", "source_id", "trigger_type", "status", "started_at",
                 "fetched_count", "valid_count", "invalid_count",
                 "new_count", "duplicate_count", "failed_count"],
    "properties": {
        "_id": {"bsonType": "string"},
        "owner_id": {"bsonType": "string", "minLength": 1},
        "source_id": {"bsonType": "string"},
        "fallback_source_id": {"bsonType": ["string", "null"]},
        "trigger_type": {"enum": ["MANUAL", "API", "SCHEDULED"]},
        "status": {"enum": ["RUNNING", "SUCCESS", "FALLBACK_SUCCESS",
                            "PARTIAL", "FAILED", "EMPTY_RESPONSE"]},
        "started_at": {"bsonType": "date"},
        "finished_at": {"bsonType": ["date", "null"]},
        "duration_ms": {"bsonType": ["int", "long", "null"], "minimum": 0},
        "fetched_count": {"bsonType": ["int", "long"], "minimum": 0},
        "valid_count": {"bsonType": ["int", "long"], "minimum": 0},
        "invalid_count": {"bsonType": ["int", "long"], "minimum": 0},
        "new_count": {"bsonType": ["int", "long"], "minimum": 0},
        "duplicate_count": {"bsonType": ["int", "long"], "minimum": 0},
        "failed_count": {"bsonType": ["int", "long"], "minimum": 0},
        "error_message": {"bsonType": ["string", "null"]},
        "error_details": {"bsonType": ["object", "null"]},
    },
}

USERS_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "name", "email", "password_hash", "recovery_hash", "role", "created_at"],
    "properties": {
        "_id": {"bsonType": "string"},
        "name": {"bsonType": "string", "minLength": 1, "maxLength": 60},
        "email": {"bsonType": "string", "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"},
        "password_hash": {"bsonType": "string"},
        "recovery_hash": {"bsonType": "string"},
        "role": {"enum": ["user", "admin"]},
        "failed_attempts": {"bsonType": ["int", "long"], "minimum": 0},
        "locked_until": {"bsonType": ["date", "null"]},
        "last_login_at": {"bsonType": ["date", "null"]},
        "created_at": {"bsonType": "date"},
        "updated_at": {"bsonType": "date"},
    },
}

SESSIONS_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "user_id", "created_at", "expires_at"],
    "properties": {
        "_id": {"bsonType": "string"},
        "user_id": {"bsonType": "string"},
        "created_at": {"bsonType": "date"},
        "expires_at": {"bsonType": "date"},
    },
}

SCHEMAS = {"sources": SOURCES_SCHEMA, "jobs": JOBS_SCHEMA, "ingestion_runs": RUNS_SCHEMA,
           "users": USERS_SCHEMA, "sessions": SESSIONS_SCHEMA}

DEFAULT_SOURCES = [
    {"_id": "greenhouse", "name": "greenhouse", "base_url": "https://boards-api.greenhouse.io/v1/boards"},
    {"_id": "lever", "name": "lever", "base_url": "https://api.lever.co/v0/postings"},
]


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------
@lru_cache()
def get_client() -> MongoClient:
    s = get_settings()
    # tz_aware=True -> datetimes come back timezone-aware (UTC)
    return MongoClient(s.MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=5000)


def get_database() -> Database:
    return get_client()[get_settings().MONGODB_DB]


def get_db() -> Database:
    """FastAPI dependency."""
    return get_database()


async def run_db(func, *args, **kwargs):
    """Run a blocking PyMongo call in a worker thread so the event loop is never blocked."""
    return await asyncio.to_thread(func, *args, **kwargs)


# --------------------------------------------------------------------------
# Setup: collections + validators + indexes + default sources
# --------------------------------------------------------------------------
def setup_database(db: Database) -> None:
    from datetime import datetime, timezone

    existing = db.list_collection_names()
    for name, schema in SCHEMAS.items():
        validator = {"$jsonSchema": schema}
        try:
            if name in existing:
                db.command("collMod", name, validator=validator, validationAction="error")
            else:
                db.create_collection(name, validator=validator, validationAction="error")
        except NotImplementedError:
            # In-memory test double (mongomock) has no server-side validation.
            if name not in existing:
                db.create_collection(name)

    # Indexes
    db.sources.create_index("name", unique=True)
    try:                                   # old single-user index from the previous version
        db.jobs.drop_index("uq_source_external_id")
    except Exception:
        pass
    # Deduplication is per user: the same job may exist for two different users
    db.jobs.create_index([("owner_id", ASCENDING), ("source_id", ASCENDING), ("external_id", ASCENDING)],
                         unique=True, name="uq_owner_source_external")
    db.jobs.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    db.jobs.create_index([("posted_at", DESCENDING)])
    db.jobs.create_index([("owner_id", ASCENDING), ("applied_at", DESCENDING)])
    db.ingestion_runs.create_index([("owner_id", ASCENDING), ("started_at", DESCENDING)])
    db.ingestion_runs.create_index([("started_at", DESCENDING)])
    db.ingestion_runs.create_index([("status", ASCENDING)])
    db.users.create_index("email", unique=True)
    db.sessions.create_index("user_id")
    db.sessions.create_index("expires_at", expireAfterSeconds=0)   # MongoDB deletes expired sessions

    # Seed default sources
    if db.sources.count_documents({}) == 0:
        now = datetime.now(timezone.utc)
        db.sources.insert_many([
            {**s, "is_active": True, "rate_limit_rps": 2.0, "created_at": now, "updated_at": now}
            for s in DEFAULT_SOURCES
        ])
        logger.info("Seeded default sources (greenhouse, lever).")
