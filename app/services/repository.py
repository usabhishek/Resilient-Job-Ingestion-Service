"""Data access layer — all MongoDB (PyMongo) queries live here.

Collections:
  users           one document per account
  sessions        one document per active login
  sources         one document per upstream source (_id = source name)
  jobs            one document per job posting     (owner_id = the user who ingested it)
  ingestion_runs  one audit document per ingestion run (owner_id = the user who started it)

Every job/run query takes an owner_id, so a user can only ever see and change their own data.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from pymongo import DESCENDING
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from app.schemas.job import JobNormalized

logger = logging.getLogger("repository")

DUPLICATE_KEY_ERROR = 11000


class Doc(dict):
    """A MongoDB document that also allows attribute access (doc.title) and has 'id' instead of '_id'."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def to_doc(raw: dict | None) -> Doc | None:
    if raw is None:
        return None
    doc = Doc(raw)
    doc["id"] = doc.pop("_id")
    return doc


def now() -> datetime:
    return datetime.now(timezone.utc)


class JobRepository:

    # ------------------------------------------------------------ SOURCES
    @staticmethod
    def get_or_create_source(db: Database, name: str, slug: str, base_url: str,
                             rate_limit_rps: float = 2.0) -> Doc:
        source = db.sources.find_one({"_id": name})
        if not source:
            t = now()
            source = {"_id": name, "name": name, "base_url": base_url, "is_active": True,
                      "rate_limit_rps": float(rate_limit_rps), "created_at": t, "updated_at": t}
            db.sources.insert_one(source)
        return to_doc(source)

    @staticmethod
    def get_source_by_name(db: Database, name: str) -> Doc | None:
        return to_doc(db.sources.find_one({"_id": name}))

    # --------------------------------------------------------------- JOBS
    @staticmethod
    def insert_jobs_batch(db: Database, owner_id: str, source_id: str,
                          normalized_jobs: list[JobNormalized]) -> tuple[int, int, int]:
        """Insert jobs for one user. The unique index (owner_id, source_id, external_id) removes duplicates.
        Returns (new_count, duplicate_count, failed_count)."""
        if not normalized_jobs:
            return (0, 0, 0)

        t = now()
        docs = [{
            "_id": str(uuid.uuid4()),
            "owner_id": owner_id,
            "source_id": source_id,
            "external_id": j.external_id,
            "title": j.title,
            "company": j.company,
            "location": j.location,
            "description": j.description,
            "job_url": j.job_url,
            "posted_at": j.posted_at,
            "applied_at": None,
            "raw_payload": j.raw_payload,
            "is_active": True,
            "created_at": t,
            "updated_at": t,
        } for j in normalized_jobs]

        duplicates = failed = 0
        try:
            db.jobs.insert_many(docs, ordered=False)      # keep going after a duplicate
        except BulkWriteError as err:
            for e in err.details.get("writeErrors", []):
                if e.get("code") == DUPLICATE_KEY_ERROR:
                    duplicates += 1
                else:                                      # e.g. validation error (code 121)
                    failed += 1
                    logger.error(f"Job rejected by MongoDB: {e.get('errmsg')}")
        new = len(docs) - duplicates - failed
        return (new, duplicates, failed)

    @staticmethod
    def _job_filter(owner_id: str, source_id: str | None, company: str | None,
                    search: str | None, applied: bool | None = None) -> dict:
        query: dict[str, Any] = {"owner_id": owner_id}          # users only see their own jobs
        if applied is True:
            query["applied_at"] = {"$ne": None}                 # jobs the user applied to
        elif applied is False:
            query["applied_at"] = None
        if source_id:
            query["source_id"] = source_id
        if company:
            query["company"] = {"$regex": re.escape(company), "$options": "i"}
        if search:
            rx = {"$regex": re.escape(search), "$options": "i"}
            query["$or"] = [{"title": rx}, {"company": rx}, {"location": rx}]
        return query

    @staticmethod
    def list_jobs(db: Database, owner_id: str, source_id: str | None = None,
                  company: str | None = None, search: str | None = None,
                  page: int = 1, limit: int | None = None,
                  applied: bool | None = None) -> tuple[list[Doc], int]:
        """One user's jobs, newest first. limit=None returns every matching record."""
        query = JobRepository._job_filter(owner_id, source_id, company, search, applied)
        total = db.jobs.count_documents(query)
        sort_field = "applied_at" if applied is True else "created_at"   # applied list: latest first
        cursor = db.jobs.find(query).sort(sort_field, DESCENDING)
        if limit:
            cursor = cursor.skip((page - 1) * limit).limit(limit)
        jobs = [to_doc(j) for j in cursor]
        for j in jobs:
            j["source_name"] = j.source_id
        return jobs, total

    @staticmethod
    def get_job(db: Database, owner_id: str, job_id: str) -> Doc | None:
        job = to_doc(db.jobs.find_one({"_id": job_id, "owner_id": owner_id}))
        if job:
            job["source_name"] = job.source_id
        return job

    @staticmethod
    def update_job(db: Database, owner_id: str, job_id: str, changes: dict[str, Any]) -> Doc | None:
        """Update selected fields of one of the user's jobs (UPDATE in CRUD)."""
        changes["updated_at"] = now()
        db.jobs.update_one({"_id": job_id, "owner_id": owner_id}, {"$set": changes})
        return JobRepository.get_job(db, owner_id, job_id)

    @staticmethod
    def delete_job(db: Database, owner_id: str, job_id: str) -> bool:
        """Delete one of the user's jobs (DELETE in CRUD)."""
        return db.jobs.delete_one({"_id": job_id, "owner_id": owner_id}).deleted_count == 1

    @staticmethod
    def delete_jobs(db: Database, owner_id: str, job_ids: list[str]) -> int:
        """Delete several of the user's jobs at once. Ids that belong to someone else are ignored."""
        return db.jobs.delete_many({"_id": {"$in": job_ids}, "owner_id": owner_id}).deleted_count

    # --------------------------------------------------------------- RUNS
    @staticmethod
    def create_ingestion_run(db: Database, owner_id: str, source_id: str,
                             trigger_type: str = "MANUAL") -> Doc:
        run = {
            "_id": str(uuid.uuid4()), "owner_id": owner_id, "source_id": source_id,
            "fallback_source_id": None,
            "trigger_type": trigger_type, "status": "RUNNING", "started_at": now(),
            "finished_at": None, "duration_ms": None,
            "fetched_count": 0, "valid_count": 0, "invalid_count": 0,
            "new_count": 0, "duplicate_count": 0, "failed_count": 0,
            "error_message": None, "error_details": None,
        }
        db.ingestion_runs.insert_one(run)
        return to_doc(run)

    @staticmethod
    def complete_ingestion_run(db: Database, run_id: str, status: str, fetched_count: int,
                               valid_count: int, invalid_count: int, new_count: int,
                               duplicate_count: int, failed_count: int,
                               fallback_source_id: str | None = None,
                               error_message: str | None = None,
                               error_details: dict[str, Any] | None = None) -> Doc | None:
        run = db.ingestion_runs.find_one({"_id": run_id})
        if not run:
            return None
        finished = now()
        started = run["started_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        duration_ms = max(0, int((finished - started).total_seconds() * 1000))
        db.ingestion_runs.update_one({"_id": run_id}, {"$set": {
            "status": status, "fallback_source_id": fallback_source_id,
            "finished_at": finished, "duration_ms": duration_ms,
            "fetched_count": fetched_count, "valid_count": valid_count,
            "invalid_count": invalid_count, "new_count": new_count,
            "duplicate_count": duplicate_count, "failed_count": failed_count,
            "error_message": error_message, "error_details": error_details,
        }})
        return to_doc(db.ingestion_runs.find_one({"_id": run_id}))

    @staticmethod
    def list_recent_runs(db: Database, owner_id: str | None = None, page: int = 1,
                         limit: int | None = None) -> tuple[list[Doc], int]:
        """Runs newest first. owner_id=None means every user's runs (admin only).
        limit=None returns every run."""
        query = {"owner_id": owner_id} if owner_id else {}
        total = db.ingestion_runs.count_documents(query)
        cursor = db.ingestion_runs.find(query).sort("started_at", DESCENDING)
        if limit:
            cursor = cursor.skip((page - 1) * limit).limit(limit)
        runs = [to_doc(r) for r in cursor]
        for r in runs:
            r["source_name"] = r.source_id
            r["fallback_source_name"] = r.fallback_source_id
        return runs, total
