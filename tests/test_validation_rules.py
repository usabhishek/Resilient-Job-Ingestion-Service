"""Checks the MongoDB $jsonSchema validation rules.

mongomock cannot enforce server-side validators, so a small checker applies the SAME schema
dictionaries (app.database.*_SCHEMA) that are sent to MongoDB. Against a real MongoDB
server the rules are enforced by the database itself (see demo_mongodb.py).
"""
import re
from datetime import datetime, timezone
from app.database import JOBS_SCHEMA, SOURCES_SCHEMA, RUNS_SCHEMA, USERS_SCHEMA, SESSIONS_SCHEMA

PY_TYPES = {"string": str, "bool": bool, "date": datetime, "object": dict, "array": list,
            "int": int, "long": int, "double": float, "null": type(None)}


def violations(schema: dict, doc: dict) -> list[str]:
    errors = [f"missing '{k}'" for k in schema["required"] if k not in doc]
    for key, rule in schema["properties"].items():
        if key not in doc:
            continue
        value = doc[key]
        types = rule.get("bsonType")
        if types:
            types = [types] if isinstance(types, str) else types
            ok = any(isinstance(value, PY_TYPES[t]) and not (t in ("int", "long", "double") and isinstance(value, bool))
                     for t in types)
            if not ok:
                errors.append(f"'{key}' has wrong type")
                continue
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"'{key}' not in enum")
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", 10**9):
                errors.append(f"'{key}' bad length")
            if "pattern" in rule and not re.search(rule["pattern"], value):
                errors.append(f"'{key}' bad pattern")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < rule.get("minimum", float("-inf")) or value > rule.get("maximum", float("inf")):
                errors.append(f"'{key}' out of range")
    return errors


NOW = datetime.now(timezone.utc)


def good_job(**over):
    doc = {"_id": "1", "owner_id": "u1", "source_id": "greenhouse", "external_id": "101", "title": "Engineer",
           "company": "Cloudflare", "location": "Remote", "description": None,
           "job_url": "https://x.com/1", "posted_at": None, "raw_payload": None,
           "is_active": True, "created_at": NOW, "updated_at": NOW}
    doc.update(over)
    return doc


def test_valid_job_passes():
    assert violations(JOBS_SCHEMA, good_job()) == []
    assert violations(JOBS_SCHEMA, good_job(posted_at=NOW, raw_payload={"a": 1}, description="x")) == []
    assert violations(JOBS_SCHEMA, good_job(applied_at=NOW)) == []          # applied
    assert violations(JOBS_SCHEMA, good_job(applied_at=None)) == []         # not applied
    assert violations(JOBS_SCHEMA, good_job(applied_at="yesterday"))        # must be a date


def test_invalid_jobs_rejected():
    assert violations(JOBS_SCHEMA, good_job(title=""))
    assert violations(JOBS_SCHEMA, good_job(job_url="not-a-url"))
    assert violations(JOBS_SCHEMA, good_job(source_id="linkedin"))
    assert violations(JOBS_SCHEMA, good_job(is_active="yes"))
    bad = good_job(); del bad["owner_id"]
    assert violations(JOBS_SCHEMA, bad)                 # every job must belong to a user
    bad = good_job(); del bad["company"]
    assert violations(JOBS_SCHEMA, bad)


def test_source_rules():
    ok = {"_id": "lever", "name": "lever", "base_url": "https://api.lever.co", "is_active": True,
          "rate_limit_rps": 2.0, "created_at": NOW}
    assert violations(SOURCES_SCHEMA, ok) == []
    assert violations(SOURCES_SCHEMA, {**ok, "rate_limit_rps": 0})
    assert violations(SOURCES_SCHEMA, {**ok, "base_url": "ftp://x"})


def test_run_rules():
    ok = {"_id": "r", "owner_id": "u1", "source_id": "greenhouse", "trigger_type": "API", "status": "SUCCESS",
          "started_at": NOW, "fetched_count": 2, "valid_count": 2, "invalid_count": 0,
          "new_count": 2, "duplicate_count": 0, "failed_count": 0}
    assert violations(RUNS_SCHEMA, ok) == []
    assert violations(RUNS_SCHEMA, {**ok, "status": "BROKEN"})
    assert violations(RUNS_SCHEMA, {**ok, "new_count": -1})


def test_user_rules():
    ok = {"_id": "u", "name": "Asha", "email": "asha@example.com", "password_hash": "x$y",
          "recovery_hash": "x$y", "role": "user", "failed_attempts": 0, "locked_until": None,
          "last_login_at": None, "created_at": NOW, "updated_at": NOW}
    assert violations(USERS_SCHEMA, ok) == []
    assert violations(USERS_SCHEMA, {**ok, "email": "not-an-email"})
    assert violations(USERS_SCHEMA, {**ok, "role": "superuser"})
    assert violations(USERS_SCHEMA, {**ok, "name": ""})
    assert violations(SESSIONS_SCHEMA, {"_id": "t", "user_id": "u", "created_at": NOW, "expires_at": NOW}) == []


def test_real_documents_written_by_repository_satisfy_schema(db):
    """Documents produced by the repository code must pass the schema."""
    from app.services.repository import JobRepository
    from app.schemas.job import JobNormalized
    JobRepository.insert_jobs_batch(db, "u1", "greenhouse", [
        JobNormalized(external_id="e1", source="greenhouse", title="T", company="C",
                      job_url="https://a.b/1", posted_at=NOW, raw_payload={"k": "v"})])
    run = JobRepository.create_ingestion_run(db, "u1", "greenhouse", "API")
    JobRepository.complete_ingestion_run(db, run.id, "SUCCESS", 1, 1, 0, 1, 0, 0)
    for job in db.jobs.find():
        assert violations(JOBS_SCHEMA, job) == [], job
    for r in db.ingestion_runs.find():
        assert violations(RUNS_SCHEMA, r) == [], r
    for s in db.sources.find():
        assert violations(SOURCES_SCHEMA, s) == [], s
    from app.services import users
    users.create_user(db, "Asha", "asha@example.com", "password123", "School")
    from app.auth import create_session
    create_session(db, "u")
    for u in db.users.find():
        assert violations(USERS_SCHEMA, u) == [], u
    for sess in db.sessions.find():
        assert violations(SESSIONS_SCHEMA, sess) == [], sess
