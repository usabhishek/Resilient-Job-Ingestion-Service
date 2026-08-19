# AI Engineering Master Prompt — Acdyon Technologies Part 1

You are working on a one-day engineering assessment for Acdyon Technologies.

## 1. Objective

Build a small but production-minded job ingestion system that demonstrates:

* source abstraction
* reliable HTTP ingestion
* rate limiting / pacing
* retry and exponential backoff
* timeout handling
* source failure detection
* fallback source strategy
* schema validation
* normalization
* deduplication
* persistence
* observability
* resilience to source/API changes
* clear engineering trade-offs
* safe handling of platform Terms of Service

The live demo MUST use a low-risk public job source such as a public job-board API/feed. Do NOT use a real LinkedIn account, CAPTCHA bypass, stealth browser, credential automation, or techniques intended to evade anti-bot controls.

The architecture should demonstrate how the same ingestion system could support a more restrictive source through a separate adapter without implementing prohibited or risky bypass mechanisms.

## 2. Technology Stack

Use:

* Python 3.12+
* FastAPI
* httpx
* Pydantic
* SQLAlchemy
* PostgreSQL through Supabase
* Jinja2
* HTML/CSS/vanilla JavaScript
* pytest
* python-dotenv or equivalent environment configuration

Do NOT introduce React, Next.js, Redis, Celery, Kafka, RabbitMQ, Kubernetes, microservices, or other infrastructure unless there is a demonstrated requirement.

The project has a one-day implementation constraint. Prefer simplicity, reliability, and explainability.

## 3. Backend Architecture

Use the following conceptual architecture:

Source Adapter
↓
HTTP Fetcher
↓
Rate Limiter
↓
Retry / Backoff
↓
Raw Response
↓
Normalizer
↓
Pydantic Validation
↓
Deduplication
↓
Repository
↓
Supabase PostgreSQL

Keep source-specific logic inside source adapters.

The ingestion pipeline MUST NOT depend directly on Greenhouse-specific fields or URLs.

Create an abstract source interface similar to:

JobSource
- fetch_jobs()
- health_check()
- source_name()

Implement:

* GreenhouseSource as primary source
* LeverSource as fallback source, if the public API/feed can be implemented reliably within the time limit

If the fallback source cannot be completed safely within the time limit, implement the fallback abstraction and document the limitation rather than creating unreliable code.

## 4. Database

Use Supabase PostgreSQL.

Create migrations rather than relying on manually created production tables.

Core tables:

sources
jobs
ingestion_runs

The jobs table must support source-specific external IDs.

Use a uniqueness constraint on:

(source_id, external_id)

Do not depend only on job title/company for deduplication.

Store raw source data when useful for debugging, but avoid storing unnecessary sensitive information.

## 5. HTTP Client

Use httpx.

Every external request MUST have:

* explicit timeout
* controlled request headers
* error handling
* status-code handling
* logging
* retry policy where appropriate

Do not create infinite retries.

Do not retry every HTTP status blindly.

Treat retryable and non-retryable failures differently.

At minimum consider:

* timeout
* connection errors
* 429
* 500
* 502
* 503
* 504

Do not retry obvious client errors such as 400 or 404 unless there is a specific reason.

## 6. Retry Strategy

Implement bounded exponential backoff.

Example conceptual behavior:

attempt 1
→ wait approximately 1 second

attempt 2
→ wait approximately 2 seconds

attempt 3
→ wait approximately 4 seconds

Use a maximum retry count and maximum delay.

Respect Retry-After when the source provides it and doing so is appropriate.

Never create infinite retry loops.

## 7. Rate Limiting

Implement a small reusable rate-limiter component.

The source adapter should not independently manage arbitrary sleeps.

The ingestion layer should control request pacing.

The implementation should be conservative for public APIs.

Do not implement proxy rotation, CAPTCHA solving, fingerprint spoofing, stealth browser automation, or other anti-bot evasion techniques.

## 8. Source Failure

The system must distinguish:

* successful ingestion
* temporary source failure
* permanent source failure
* empty response
* malformed response
* validation failure

An empty response must NOT automatically be treated as successful ingestion.

Log enough information to diagnose the problem.

Do not silently discard errors.

## 9. Fallback

The architecture should support:

Primary Source
↓
failure
↓
Fallback Source
↓
successful ingestion

Fallback should only occur for appropriate source failures.

Do not switch sources simply because zero new jobs were found.

Record which source actually performed the ingestion.

## 10. Schema Validation

Normalize every source into a common Job model.

Minimum normalized fields:

* external_id
* source
* title
* company
* location
* description
* job_url
* posted_at

Use Pydantic validation.

If required fields are missing:

* record the validation error
* do not silently insert malformed data
* continue processing other valid records where safe

## 11. Deduplication

Deduplicate using:

source_id + external_id

Use database constraints as the final source of truth.

Do not rely only on in-memory deduplication.

The ingestion result should report:

* fetched
* valid
* invalid
* new
* duplicate
* failed

## 12. Observability

Implement structured, readable application logging.

Each ingestion run should have:

* source
* start time
* end time
* status
* fetched count
* new count
* duplicate count
* failed count
* error information

Create a health endpoint:

GET /health

Create an ingestion endpoint:

POST /api/ingest

Create a jobs endpoint:

GET /api/jobs

Create a source/status endpoint:

GET /api/sources

Keep API design simple.

## 13. Dashboard

Build a minimal but professional server-rendered dashboard.

Display:

* source health
* last ingestion
* total jobs
* jobs fetched in last run
* new jobs
* duplicates
* failures
* recent ingestion runs
* recent jobs

The dashboard should be functional rather than visually elaborate.

Do not spend excessive implementation time on animations.

## 14. Security

Never hardcode:

* Supabase credentials
* database passwords
* API keys
* secrets

Use environment variables.

Never expose Supabase secret/service-role credentials to browser code.

Use the least privileged credential appropriate for each operation.

Do not commit .env files.

Create a .env.example.

## 15. Supabase

Use Supabase primarily as managed PostgreSQL.

Do not move the entire ingestion pipeline into Supabase Edge Functions.

The main ingestion service remains Python/FastAPI.

Use Supabase MCP only when it helps inspect or manage the database/project.

Prefer migrations and version-controlled SQL over manual production-only changes.

## 16. Testing

Create focused pytest tests for:

* valid source response
* malformed source response
* empty response
* validation failure
* timeout
* 429
* 5xx
* retry exhaustion
* deduplication
* normalization
* fallback behavior

Mock external HTTP calls in unit tests.

Tests must not depend on live external services.

## 17. AI Coding Rules

You are an implementation assistant, not the owner of architectural decisions.

Before making a large architectural change:

1. explain the change
2. identify affected files
3. identify risks
4. implement only after the architecture remains consistent

Never rewrite the entire project to solve a localized bug.

Never delete working code without explaining why.

Never introduce a new dependency unless necessary.

Never change the database schema without updating migrations and affected application code.

Never change API contracts casually.

Never modify multiple unrelated subsystems while fixing one bug.

## 18. Recovery Protocol

If tests fail after a change:

1. stop
2. inspect git diff
3. identify the first failing test/error
4. determine the root cause
5. make the smallest corrective change
6. rerun the relevant tests
7. rerun the full test suite
8. only then continue

If a change causes widespread failures, do not continue modifying the code blindly.

Return to the last known-good git checkpoint if necessary.

## 19. Git Discipline

Work incrementally.

Create commits after stable milestones:

* initial project
* database schema
* source adapter
* ingestion pipeline
* retry/rate limiting
* validation/deduplication
* fallback
* dashboard
* tests
* deployment

Never perform a destructive repository-wide rewrite without explicit approval.

## 20. One-Day Constraint

Optimize for:

1. correctness
2. reliability
3. explainability
4. deployment
5. tests
6. documentation
7. UI polish

Do not optimize for architectural complexity.

A smaller system that works reliably is preferable to a sophisticated system that cannot be explained or deployed.

## 21. Assignment Alignment

The final implementation must allow me to explain:

1. What makes automated ingestion detectable?
2. How does request pacing work?
3. How does retry/backoff work?
4. What happens after rate limiting?
5. What happens if the source changes?
6. What happens if the source returns empty data?
7. What happens if the primary source fails?
8. How is duplicate data handled?
9. Where is the technical/ToS boundary?
10. Why was this architecture chosen?
11. What trade-off was made because of the one-day constraint?
12. Where did AI assist and what was manually verified?

## 22. Important

Do not claim that the system bypasses LinkedIn, Indeed, Naukri, or other anti-bot protections.

Do not implement CAPTCHA bypassing.

Do not implement credential theft or account automation.

Do not implement stealth techniques intended to evade platform enforcement.

The live demo should remain within the assignment's explicit low-risk-source scope.

The final project must be understandable by a developer who did not generate it.

Before declaring the project complete:

* run tests
* verify environment variables
* verify database migrations
* verify API endpoints
* verify ingestion
* verify fallback behavior
* verify dashboard
* verify deployment
* verify Git status
* produce README
* produce DECISIONS.md
