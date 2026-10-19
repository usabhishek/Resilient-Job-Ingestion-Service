"""Demo: validation, CRUD and aggregation on the job ingestion database.

  python demo_mongodb.py          # uses MONGODB_URI from .env (real MongoDB / Atlas)
  python demo_mongodb.py --mock   # uses an in-memory mock (no MongoDB needed; validation not enforced)
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pymongo.errors import DuplicateKeyError, WriteError
from app.database import get_database, setup_database
from app.services import analytics


def show(title, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2, default=str))


def main():
    mock = "--mock" in sys.argv
    if mock:
        import mongomock
        db = mongomock.MongoClient(tz_aware=True)["demo_job_ingestion"]
        print("Using in-memory mock database (validation rules are NOT enforced in mock mode).")
    else:
        db = get_database()
    setup_database(db)
    now = datetime.now(timezone.utc)

    def job(i, source, company, location, title, days_ago):
        return {"_id": f"demo-{i}", "owner_id": "demo-user", "source_id": source, "external_id": f"ext-{i}", "title": title,
                "company": company, "location": location, "description": None,
                "job_url": f"https://jobs.example.com/{i}", "posted_at": now - timedelta(days=days_ago),
                "raw_payload": None, "is_active": True, "created_at": now, "updated_at": now}

    db.jobs.delete_many({"_id": {"$regex": "^demo-"}})
    db.ingestion_runs.delete_many({"_id": {"$regex": "^demo-"}})

    def run(i, status, duration, new, dup):
        return {"_id": f"demo-run-{i}", "owner_id": "demo-user", "source_id": "greenhouse", "fallback_source_id": None,
                "trigger_type": "API", "status": status, "started_at": now, "finished_at": now,
                "duration_ms": duration, "fetched_count": new + dup, "valid_count": new + dup,
                "invalid_count": 0, "new_count": new, "duplicate_count": dup, "failed_count": 0,
                "error_message": None, "error_details": None}
    db.ingestion_runs.insert_many([run(1, "SUCCESS", 700, 42, 0), run(2, "SUCCESS", 520, 3, 39),
                                   run(3, "FAILED", 1500, 0, 0)])

    # ---------------- CREATE
    docs = [job(1, "greenhouse", "Cloudflare", "Austin, TX", "Senior Infrastructure Engineer", 5),
            job(2, "greenhouse", "Cloudflare", "Remote", "Security Engineer", 20),
            job(3, "greenhouse", "Stripe", "Remote", "Backend Engineer", 35),
            job(4, "lever", "Netflix", "Los Gatos, CA", "Data Engineering Lead", 10),
            job(5, "lever", "Netflix", "Remote", "Platform Engineer", 45)]
    res = db.jobs.insert_many(docs)
    show("CREATE  insert_many -> inserted ids", res.inserted_ids)

    # ---------------- VALIDATION + UNIQUE INDEX
    print("\n=== VALIDATION RULES ===")
    try:
        db.jobs.insert_one(job(6, "greenhouse", "Acme", "Remote", "", 1))     # empty title
        print("Invalid job (empty title) was accepted  -> validator not enforced (mock mode)")
        db.jobs.delete_one({"_id": "demo-6"})
    except WriteError as e:
        print("Rejected by validator (empty title):", e.details.get("errmsg"))
    try:
        db.jobs.insert_one({**job(7, "greenhouse", "Acme", "Remote", "Dup", 1), "external_id": "ext-1"})
    except DuplicateKeyError:
        print("Rejected by unique index (source_id + external_id already exists): duplicate job blocked")

    # ---------------- READ
    show("READ  find_one", db.jobs.find_one({"_id": "demo-1"}, {"title": 1, "company": 1, "location": 1}))
    show("READ  find (company regex 'net', sorted by title)",
         list(db.jobs.find({"company": {"$regex": "net", "$options": "i"}},
                           {"title": 1, "company": 1}).sort("title", 1)))
    show("READ  count remote jobs", db.jobs.count_documents({"location": "Remote"}))

    # ---------------- UPDATE
    r = db.jobs.update_one({"_id": "demo-2"}, {"$set": {"title": "Staff Security Engineer", "updated_at": now}})
    show("UPDATE  update_one (matched, modified)", [r.matched_count, r.modified_count])
    r = db.jobs.update_many({"source_id": "lever"}, {"$set": {"is_active": False}})
    show("UPDATE  update_many lever jobs inactive (modified)", r.modified_count)

    # ---------------- AGGREGATION
    show("AGGREGATION 1: jobs per company ($group, $sort, $limit)", analytics.jobs_per_company(db))
    show("AGGREGATION 2: jobs per source ($group, $addToSet, $size)", analytics.jobs_per_source(db))
    show("AGGREGATION 3: top locations ($group, $sort)", analytics.top_locations(db))
    show("AGGREGATION 4: jobs posted per month ($match, $dateToString)", analytics.jobs_posted_per_month(db))
    show("AGGREGATION 5: ingestion run statistics ($group, $avg)", analytics.run_statistics_by_status(db))

    # ---------------- USERS (login system)
    from app.services import users as user_service
    db.users.delete_many({"email": "demo@example.com"})
    u = user_service.create_user(db, "Demo User", "demo@example.com", "password123", "my school")
    show("USERS  create (password stored only as a salted hash)",
         {k: (v if k in ("name", "email", "role") else "<hidden>") for k, v in db.users.find_one({"_id": u.id}).items()
          if k in ("name", "email", "role", "password_hash")})
    user_service.update_name(db, u.id, "Demo Renamed")
    show("USERS  update name", db.users.find_one({"_id": u.id})["name"])
    show("USERS  admin view: users with job/run counts", [
        {k: x[k] for k in ("name", "email", "jobs", "runs")} for x in user_service.users_with_counts(db)])
    user_service.delete_user_and_data(db, u.id)
    show("USERS  delete account (also removes the user's jobs/runs)",
         db.users.count_documents({"email": "demo@example.com"}))

    # ---------------- DELETE
    r = db.jobs.delete_one({"_id": "demo-5"})
    show("DELETE  delete_one (deleted)", r.deleted_count)
    r = db.jobs.delete_many({"_id": {"$regex": "^demo-"}})
    db.ingestion_runs.delete_many({"_id": {"$regex": "^demo-"}})
    show("DELETE  delete_many cleanup (deleted)", r.deleted_count)


if __name__ == "__main__":
    main()
