# MongoDB Viva Guide — Resilient Job Ingestion Service

## 1. Problem and real-world relevance
Companies publish jobs on different Applicant Tracking Systems (Greenhouse, Lever). Each returns a different JSON shape.
This service fetches jobs, normalizes them, removes duplicates, and keeps an audit log of every run. Job aggregators and recruiting tools need exactly this.

## 2. Database and document design (5 collections)
| Collection | One document is... | `_id` |
|---|---|---|
| `sources` | an upstream source (greenhouse / lever) | source name |
| `jobs` | one normalized job posting | UUID string |
| `ingestion_runs` | one audit record of an ingestion run (`owner_id` = who started it) | UUID string |
| `users` | one account (name, unique email, password hash, role `user`/`admin`) | UUID string |
| `sessions` | one active login; `_id` is the SHA-256 of the cookie token; TTL index removes expired ones | token hash |

Why documents: postings differ per vendor and carry a variable `raw_payload`; a document holds this naturally, with no joins.
Why references: jobs and runs store `source_id` (the source name). Sources are few and rarely change, so a reference is better than copying them into every job.
Ownership: `jobs.owner_id` and `ingestion_runs.owner_id` reference `users._id`; every query filters by it, so users only see their own data.
Indexes: unique `(owner_id, source_id, external_id)` for per-user deduplication; unique `users.email`; TTL on `sessions.expires_at`; `company`, `created_at`, `posted_at`, `started_at`, `status` for fast filtering and sorting.

## 3. Validation rules (`app/database.py`)
`$jsonSchema` validators with `validationAction="error"` on every collection: required fields, types, `minLength`/`maxLength`,
URL `pattern`, `enum` for `source_id`, `status`, `trigger_type`, and `minimum` for counts. A second layer (Pydantic) validates data before it reaches MongoDB.

## 3b. Login and security
Passwords and security answers are salted scrypt hashes (never plain text). Login sets an HttpOnly, SameSite=Lax cookie (Secure in production).
After 5 wrong attempts an account locks for 10 minutes. Signup can only create role `user`; the admin comes from `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
Forgot password = email + security answer (a real product would send an email link instead).

## 4. CRUD (`app/services/repository.py`)
| Operation | PyMongo call | Where |
|---|---|---|
| Create | `insert_one`, `insert_many(ordered=False)` | ingestion, `insert_jobs_batch` |
| Read | `find`, `find_one`, `count_documents`, `sort/skip/limit`, `$regex` search | `list_jobs`, `get_job` |
| Update | `update_one` with `$set` (also sets/clears `applied_at` to track applications) | `update_job`, `complete_ingestion_run` |
| Delete | `delete_one`, `delete_many` with `$in` (bulk delete of selected jobs, always filtered by `owner_id`) | `delete_job`, `delete_jobs` |
Users CRUD: signup (create), `/api/me` (read/update name), password change, delete account (cascades to the user's jobs and runs). Admin: list users, delete user, clear one user's / everyone's ingestions.
REST: `GET/PATCH/DELETE /api/jobs/{id}`, `GET /api/jobs`, `POST /api/ingest`.

## 5. Aggregation pipelines (`app/services/analytics.py`, `GET /api/analytics`)
1. Jobs per company — `$group`, `$sort`, `$limit`, `$project`
2. Jobs per source with distinct companies — `$group`, `$addToSet`, `$size`
3. Top locations — `$group`, `$sort`
4. Run reliability by status — `$group`, `$avg`, `$sum`
5. Hiring trend per month — `$match`, `$dateToString`, `$group`
6. Admin: users with job and run counts, ingestions per user — `$group`, `$sum`, `$max`

## 6. PyMongo implementation
`MongoClient(uri, tz_aware=True)` in `app/database.py`. FastAPI is async and PyMongo is blocking, so calls run through `asyncio.to_thread` (`run_db`).

## 7. Showing the output
`python demo_mongodb.py` runs create, validation rejection, read, update, aggregation and delete and prints each result.
