"""Aggregation pipelines — meaningful insights from the data."""
from pymongo.database import Database


def _scope(owner_id: str | None) -> list[dict]:
    """First pipeline stage: restrict to one user's data (admin passes None = everyone)."""
    return [{"$match": {"owner_id": owner_id}}] if owner_id else []


def jobs_per_company(db: Database, owner_id: str | None = None, top: int = 10) -> list[dict]:
    """Which companies have the most openings?"""
    pipeline = _scope(owner_id) + [
        {"$group": {"_id": "$company", "total_jobs": {"$sum": 1}}},
        {"$sort": {"total_jobs": -1}},
        {"$limit": top},
        {"$project": {"_id": 0, "company": "$_id", "total_jobs": 1}},
    ]
    return list(db.jobs.aggregate(pipeline))


def jobs_per_source(db: Database, owner_id: str | None = None) -> list[dict]:
    """How many jobs came from each source, and how many companies does it cover?"""
    pipeline = _scope(owner_id) + [
        {"$group": {"_id": "$source_id", "total_jobs": {"$sum": 1},
                    "companies": {"$addToSet": "$company"}}},
        {"$project": {"_id": 0, "source": "$_id", "total_jobs": 1,
                      "company_count": {"$size": "$companies"}}},
        {"$sort": {"total_jobs": -1}},
    ]
    return list(db.jobs.aggregate(pipeline))


def top_locations(db: Database, owner_id: str | None = None, top: int = 10) -> list[dict]:
    """Most common job locations."""
    pipeline = _scope(owner_id) + [
        {"$group": {"_id": "$location", "total_jobs": {"$sum": 1}}},
        {"$sort": {"total_jobs": -1}},
        {"$limit": top},
        {"$project": {"_id": 0, "location": "$_id", "total_jobs": 1}},
    ]
    return list(db.jobs.aggregate(pipeline))


def run_statistics_by_status(db: Database, owner_id: str | None = None) -> list[dict]:
    """Ingestion reliability: runs per status with average duration and totals."""
    pipeline = _scope(owner_id) + [
        {"$group": {"_id": "$status", "runs": {"$sum": 1},
                    "avg_duration_ms": {"$avg": "$duration_ms"},
                    "total_new_jobs": {"$sum": "$new_count"},
                    "total_duplicates": {"$sum": "$duplicate_count"}}},
        {"$project": {"_id": 0, "status": "$_id", "runs": 1,
                      "avg_duration_ms": 1, "total_new_jobs": 1, "total_duplicates": 1}},
        {"$sort": {"runs": -1}},
    ]
    rows = list(db.ingestion_runs.aggregate(pipeline))
    for row in rows:                       # tidy the average for display
        row["avg_duration_ms"] = round(row["avg_duration_ms"] or 0)
    return rows


def jobs_posted_per_month(db: Database, owner_id: str | None = None) -> list[dict]:
    """Hiring trend: jobs per posting month (only jobs that have a posted_at date)."""
    pipeline = _scope(owner_id) + [
        {"$match": {"posted_at": {"$ne": None}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$posted_at"}},
                    "total_jobs": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "month": "$_id", "total_jobs": 1}},
    ]
    return list(db.jobs.aggregate(pipeline))


def runs_per_user(db: Database) -> list[dict]:
    """Admin view: how many ingestions each user made and what they produced."""
    pipeline = [
        {"$group": {"_id": "$owner_id", "runs": {"$sum": 1},
                    "new_jobs": {"$sum": "$new_count"}, "last_run": {"$max": "$started_at"}}},
        {"$sort": {"runs": -1}},
    ]
    return list(db.ingestion_runs.aggregate(pipeline))


def all_analytics(db: Database, owner_id: str | None = None) -> dict:
    return {
        "jobs_per_company": jobs_per_company(db, owner_id),
        "jobs_per_source": jobs_per_source(db, owner_id),
        "top_locations": top_locations(db, owner_id),
        "run_statistics_by_status": run_statistics_by_status(db, owner_id),
        "jobs_posted_per_month": jobs_posted_per_month(db, owner_id),
    }
