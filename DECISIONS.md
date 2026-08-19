# Architecture Decisions & Engineering Trade-Offs (DECISIONS.md)

**Project**: Acdyon Technologies Engineering Assessment (Part 1)  
**Author**: Engineering Candidate  
**Date**: August 2026  

---

## 1. What Makes Automated Ingestion Detectable?

Automated ingestion becomes detectable when an automated client behaves fundamentally differently from organic human users or legitimate API consumers. Key detection vectors include:

1. **Traffic Velocity and Request Spikes**: Sending dozens or hundreds of requests in sub-second bursts without pacing triggers heuristic rate limiters, WAFs, and anomaly detectors.
2. **Missing or Inconsistent Request Headers**: Absence of standard browser/client headers (e.g. `User-Agent`, `Accept`, `Accept-Language`) or using default Python client strings (e.g. `python-requests/2.31.0`, `curl/7.68`) immediately flags automated traffic.
3. **Deterministic Interval Signatures**: Fixed interval polling (e.g. exactly every 10.000 seconds) creates a periodic frequency signature easily flagged by machine learning anomaly filters.
4. **Behavioral Traversal**: Ingesting pages in strict sequential ID order (`/jobs/1`, `/jobs/2`, `/jobs/3`) rather than following natural navigational links.
5. **TLS/TCP Fingerprinting**: JA3/JA4 fingerprinting and HTTP/2 settings frames can expose non-browser TCP/TLS negotiation characteristics.

**How this system addresses detectability**:
- Operates strictly on **public, low-risk job board APIs/feeds** (Greenhouse and Lever) designed for programmatic ingestion.
- Implements a conservative **Token Bucket Rate Limiter** to ensure uniform request pacing without burst traffic.
- Uses configured custom `User-Agent` and `Accept` headers declaring legitimate service identity.
- Adds random **uniform jitter** to exponential backoff delays to prevent synchronized retries and stampeding herds.

---

## 2. How Does Request Pacing Work?

Request pacing in this service is decoupled from the source adapters and managed centrally via an async **Token Bucket Rate Limiter** (`app.core.rate_limiter.TokenBucketRateLimiter`):

- **Mechanism**: The bucket maintains a capacity $C$ and continuous refill rate $R$ (tokens/sec, default: 2.0 req/s).
- **Smooth Acquisition**: Before any HTTP call is dispatched, the HTTP client calls `await rate_limiter.acquire(1.0)`.
- **Refill Calculation**:
  $$\text{tokens} = \min\left(C, \text{tokens} + (\text{current\_time} - \text{last\_update}) \times R\right)$$
- If available tokens $< 1.0$, the client calculates the exact required sleep duration $\Delta t = \frac{1.0 - \text{tokens}}{R}$ and executes an asynchronous `asyncio.sleep(\Delta t)`.
- **Concurrency Protection**: An `asyncio.Lock()` guarantees thread-safe token deduction across concurrent coroutines.

---

## 3. How Does Retry/Backoff Work?

Retry logic is governed by `app.core.retry.RetryPolicy` and implemented in `ResilientHttpClient`:

- **Classification First**: Only retryable errors trigger backoff:
  - Network timeouts (`ConnectTimeout`, `ReadTimeout`, `WriteTimeout`)
  - Connection failures (`ConnectError`, `NetworkError`)
  - HTTP status codes: `429 Too Many Requests`, `500 Internal Server Error`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`.
  - Non-retryable client errors (`400`, `401`, `403`, `404`) fail fast immediately.
- **Bounded Exponential Formula**:
  $$\text{delay} = \min\left(\text{max\_backoff}, \text{initial\_backoff} \times (\text{factor})^{\text{attempt} - 1}\right) \pm \text{jitter}$$
- **Retry-After Header**: When upstream returns HTTP 429 or 503 with a `Retry-After` header (either in integer seconds or RFC 7231 / RFC 2822 HTTP date), the policy parses and respects the upstream-requested wait time up to `max_backoff`.
- **Finite Bounds**: Maximum retries is strictly capped (default: 3 attempts) to prevent infinite retry loops.

---

## 4. What Happens After Rate Limiting?

When rate limited (HTTP 429):
1. The client intercepts the 429 status code.
2. It parses the `Retry-After` header. If absent, it computes exponential backoff with jitter.
3. The worker logs a warning and sleeps asynchronously for the computed backoff window.
4. If the rate limit persists across all retry attempts, `RateLimitExceededError` is raised.
5. The ingestion orchestrator intercepts `RateLimitExceededError` as a qualifying temporary source failure, records the event in `ingestion_runs`, and triggers the **fallback source adapter** (Lever) if fallback is enabled.

---

## 5. What Happens if the Source Changes?

Upstream APIs and HTML layouts frequently experience schema drift. The system mitigates this through:

1. **Source Adapter Isolation**: Each source has a dedicated adapter (`GreenhouseSource`, `LeverSource`) inheriting from the `JobSource` abstract base class. Upstream API changes only require editing one adapter file without touching the ingestion orchestrator, database repository, or API routes.
2. **Schema Normalization Layer**: Adapters transform raw dictionaries into a unified Pydantic model `JobNormalized`.
3. **Pydantic Validation Tolerance**: If a single job in a batch has missing or corrupted fields, the validator raises `SchemaValidationError`. The orchestrator logs the corrupted item and increments `invalid_count += 1`, allowing all remaining valid jobs in the batch to be normalized and persisted without failing the entire run.
4. **Raw Payload Preservation**: The `jobs.raw_payload` JSON column stores the original source response for post-mortem debugging and schema drift analysis.

---

## 6. What Happens if the Source Returns Empty Data?

An HTTP 200 response with zero jobs (`[]` or `{"jobs": []}`) is **NOT** automatically treated as a successful ingestion.
- The pipeline explicitly evaluates `if fetched_count == 0`.
- The run is classified with status **`EMPTY_RESPONSE`**.
- A warning is logged and persisted in `ingestion_runs` with details regarding the requested board token.
- This prevents silent data loss or false-positive operational alerts while avoiding unnecessary fallback triggers on legitimately empty boards.

---

## 7. What Happens if the Primary Source Fails?

When `GreenhouseSource` encounters a transient failure (network timeout, 5xx server error, or exhausted 429 retries):
1. The `IngestionPipeline` catches `TemporarySourceError` / `HttpTimeoutError` / `RateLimitExceededError`.
2. It checks `allow_fallback=True`.
3. It dynamically resolves the configured fallback adapter (`LeverSource`) and the corresponding database source record.
4. It executes ingestion against the fallback source.
5. The audit run in `ingestion_runs` is marked as **`FALLBACK_SUCCESS`**, recording both `source_id` and `fallback_source_id` to maintain full operational lineage.
6. If both primary and fallback sources fail, the run status is marked **`FAILED`** and both error messages are recorded in `error_details`.

---

## 8. How is Duplicate Data Handled?

Deduplication operates across two coordinated tiers:

1. **In-Memory Batch Deduplication**: When normalizing an ingestion batch, `existing_ids` are tracked in a set to prevent duplicate entries within the same payload from generating redundant database queries.
2. **Database Unique Constraint (Final Source of Truth)**:
   $$\text{CONSTRAINT } \texttt{uq\_source\_external\_id} \text{ UNIQUE (source\_id, external\_id)}$$
   - Deduplication is strictly scoped per source: `(source_id, external_id)`.
   - `JobRepository.insert_jobs_batch()` compares incoming `external_id`s against existing records in PostgreSQL in a single indexed query.
   - New jobs are inserted; existing jobs are counted as duplicates.
   - The final audit log reports exact metrics: `fetched_count`, `valid_count`, `new_count`, `duplicate_count`, and `failed_count`.

---

## 9. Where is the Technical and Terms of Service (ToS) Boundary?

- **Compliant Scope**:
  - Exclusively consuming official, low-risk public APIs and public JSON feeds provided by ATS vendors (Greenhouse Job Board API and Lever Postings API).
  - Respecting vendor request pacing and HTTP status conventions.
  - Transparent custom User-Agent identifying the client.
- **Prohibited & Risky Techniques (Strictly Excluded)**:
  - No scraping behind authenticated login walls (e.g. LinkedIn, Indeed).
  - No credential sharing, session hijacking, or automated cookie extraction.
  - No anti-bot evasion techniques (CAPTCHA solvers, residential proxy rotation, browser fingerprint spoofing, stealth Puppeteer/Playwright patches).
  - No intentional circumvention of technological access controls.

---

## 10. Why Was This Architecture Chosen?

1. **Decoupled Adapter Pattern**: New sources (e.g. Ashby, Workday) can be integrated by simply implementing `JobSource` without modifying the core pipeline.
2. **Unidirectional Processing**: `Adapter -> Transport -> RateLimiter -> Normalizer -> Pydantic -> Repository -> DB` ensures single-responsibility and effortless testability.
3. **Async-First Concurrency**: `httpx` + `FastAPI` + `SQLAlchemy 2.0 (asyncpg/aiosqlite)` enables high I/O throughput with minimal memory footprint.
4. **Auditability & Observability**: Every run is persisted as an immutable record in `ingestion_runs`, providing immediate visibility into yields, duplicate rates, and latency.

---

## 11. What Trade-offs Were Made for the 1-Day Constraint?

| Decision | Chosen Approach | Alternative (Deferred) | Rationale |
|---|---|---|---|
| **Task Queue** | FastAPI BackgroundTasks & in-process async coroutines | Celery + Redis / RabbitMQ | Avoids heavy distributed broker infrastructure; fulfills all assessment requirements reliably. |
| **Frontend** | Jinja2 Server-Rendered HTML + Vanilla CSS/JS | React / Next.js SPA | Zero build step overhead; instantly responsive; lightweight single-binary deployment. |
| **Rate Limiting** | In-memory Token Bucket | Redis distributed token bucket | Single-node service requires zero external caching dependencies. |
| **Database** | Supabase PostgreSQL with local SQLite auto-fallback | Multi-node clustered PostgreSQL | Seamless local development & zero-friction automated testing alongside Supabase production support. |

---

## 12. Where Did AI Assist and What Was Manually Verified?

- **AI Assistance**:
  - Scaffolding baseline boilerplate for models, schemas, and routes.
  - Generating initial CSS tokens and layout structure.
  - Composing comprehensive pytest test cases for failure matrix edge cases.
- **Manual Engineering Verification**:
  - Validated async greenlet and SQLAlchemy 2.0 relationship loading patterns (`selectinload`).
  - Verified Starlette 0.38+ `TemplateResponse` keyword signature.
  - Verified exact mathematical bounds on exponential backoff and jitter calculations.
  - Verified database constraint definitions and indexing strategy.
  - Verified 100% test pass rate across 31 isolated unit and integration tests.
