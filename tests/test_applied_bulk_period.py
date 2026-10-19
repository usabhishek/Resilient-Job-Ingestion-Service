import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from app.api.routes_api import pipeline as api_pipeline
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, signup


async def ingest(client, payload=GREENHOUSE_SAMPLE_PAYLOAD, **extra):
    with patch.object(api_pipeline.adapters["greenhouse"].http_client, "get_json",
                      AsyncMock(return_value=payload)):
        return await client.post("/api/ingest", json={"source": "greenhouse", "board_token": "cloudflare", **extra})


def payload_with_ages(*days_ago):
    """Greenhouse payload whose jobs were posted N days ago (None = no date at all)."""
    jobs = []
    for i, days in enumerate(days_ago):
        job = {"id": 5000 + i, "title": f"Job {i}", "content": "<p>x</p>",
               "absolute_url": f"https://boards.greenhouse.io/c/jobs/{5000 + i}",
               "location": {"name": "Remote"}}
        if days is not None:
            job["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        jobs.append(job)
    return {"jobs": jobs}


# ------------------------------------------------------------------ date window
@pytest.mark.asyncio
@pytest.mark.parametrize("window, saved", [(7, 1), (30, 1), (60, 2), (180, 3), (365, 3), (None, 5)])
async def test_period_filter_keeps_only_recent_jobs(make_client, window, saved):
    client = make_client()
    await signup(client)
    payload = payload_with_ages(3, 45, 120, 400, None)    # last one has no date
    body = (await ingest(client, payload, posted_within_days=window)).json()
    assert body["status"] == "SUCCESS" and body["new_count"] == saved
    assert body["skipped_old_count"] == (0 if window is None else 5 - saved)
    assert (await client.get("/api/jobs")).json()["total"] == saved


@pytest.mark.asyncio
async def test_everything_filtered_out_is_not_reported_as_failure(make_client):
    client = make_client()
    await signup(client)
    body = (await ingest(client, payload_with_ages(400, 500), posted_within_days=7)).json()
    assert body["status"] == "SUCCESS" and body["new_count"] == 0 and body["skipped_old_count"] == 2
    assert body["valid_count"] == 2


@pytest.mark.asyncio
async def test_period_filter_stops_old_deleted_jobs_from_coming_back(make_client):
    client = make_client()
    await signup(client)
    payload = payload_with_ages(3, 200)
    await ingest(client, payload)                                     # both saved
    jobs = (await client.get("/api/jobs")).json()["items"]
    old = next(j for j in jobs if j["title"] == "Job 1")
    await client.post("/api/jobs/bulk-delete", json={"ids": [old["id"]]})
    await ingest(client, payload, posted_within_days=30)             # re-fetch, last month only
    titles = {j["title"] for j in (await client.get("/api/jobs")).json()["items"]}
    assert titles == {"Job 0"}                                        # the deleted old job did not return


@pytest.mark.asyncio
async def test_invalid_period_is_rejected(make_client):
    client = make_client()
    await signup(client)
    assert (await ingest(client, posted_within_days=0)).status_code == 422
    assert (await ingest(client, posted_within_days=-5)).status_code == 422


# ---------------------------------------------------------------------- applied
@pytest.mark.asyncio
async def test_mark_applied_list_and_undo(make_client):
    client = make_client()
    await signup(client)
    await ingest(client)
    jobs = (await client.get("/api/jobs")).json()["items"]
    assert all(j["applied_at"] is None for j in jobs)
    assert (await client.get("/api/jobs?applied=true")).json()["total"] == 0

    first, second = jobs[0]["id"], jobs[1]["id"]
    r = await client.patch(f"/api/jobs/{first}", json={"applied": True})
    assert r.status_code == 200 and r.json()["applied_at"] is not None
    await client.patch(f"/api/jobs/{second}", json={"applied": True})

    applied = (await client.get("/api/jobs?applied=true")).json()
    assert applied["total"] == 2
    assert applied["items"][0]["id"] == second                     # most recently applied first
    assert (await client.get("/api/jobs?applied=false")).json()["total"] == 0

    r = await client.patch(f"/api/jobs/{second}", json={"applied": False})
    assert r.json()["applied_at"] is None
    assert [j["id"] for j in (await client.get("/api/jobs?applied=true")).json()["items"]] == [first]
    assert (await client.get("/api/jobs?applied=false")).json()["total"] == 1
    assert (await client.get("/api/jobs")).json()["total"] == 2   # "All jobs" still shows everything


@pytest.mark.asyncio
async def test_applied_jobs_are_private_to_each_user(make_client):
    a, b = make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    await ingest(a); await ingest(b)
    job_id = (await a.get("/api/jobs")).json()["items"][0]["id"]
    await a.patch(f"/api/jobs/{job_id}", json={"applied": True})
    assert (await b.patch(f"/api/jobs/{job_id}", json={"applied": True})).status_code == 404
    assert (await b.get("/api/jobs?applied=true")).json()["total"] == 0


@pytest.mark.asyncio
async def test_search_works_inside_applied_tab(make_client):
    client = make_client()
    await signup(client)
    await ingest(client)
    for job in (await client.get("/api/jobs")).json()["items"]:
        await client.patch(f"/api/jobs/{job['id']}", json={"applied": True})
    assert (await client.get("/api/jobs?applied=true&search=security")).json()["total"] == 1


# ------------------------------------------------------------------ bulk delete
@pytest.mark.asyncio
async def test_bulk_delete_selected_jobs(make_client):
    client = make_client()
    await signup(client)
    await ingest(client, payload_with_ages(*range(1, 8)))            # 7 jobs
    ids = [j["id"] for j in (await client.get("/api/jobs?limit=100")).json()["items"]]
    r = await client.post("/api/jobs/bulk-delete", json={"ids": ids[:3]})
    assert r.status_code == 200 and r.json() == {"deleted": 3}
    assert (await client.get("/api/jobs")).json()["total"] == 4
    again = await client.post("/api/jobs/bulk-delete", json={"ids": ids[:3]})
    assert again.json() == {"deleted": 0}                              # already gone


@pytest.mark.asyncio
async def test_bulk_delete_never_touches_other_users_jobs(make_client):
    a, b = make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    await ingest(a); await ingest(b)
    a_ids = [j["id"] for j in (await a.get("/api/jobs")).json()["items"]]
    b_ids = [j["id"] for j in (await b.get("/api/jobs")).json()["items"]]
    r = await b.post("/api/jobs/bulk-delete", json={"ids": a_ids + b_ids[:1]})
    assert r.json() == {"deleted": 1}                                  # only Ben's own job
    assert (await a.get("/api/jobs")).json()["total"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_validation_and_login(make_client):
    client = make_client()
    assert (await client.post("/api/jobs/bulk-delete", json={"ids": ["x"]})).status_code == 401
    await signup(client)
    assert (await client.post("/api/jobs/bulk-delete", json={"ids": []})).status_code == 422
    assert (await client.post("/api/jobs/bulk-delete", json={"ids": ["x"] * 101})).status_code == 422
    assert (await client.post("/api/jobs/bulk-delete", json={})).status_code == 422


# --------------------------------------------------------------------- the page
@pytest.mark.asyncio
async def test_user_page_has_period_tabs_and_bulk_controls(make_client):
    client = make_client()
    await signup(client)
    html = (await client.get("/")).text
    for label in ["Any time", "Last 7 days", "Last 1 month", "Last 2 months", "Last 6 months", "Last 1 year"]:
        assert label in html
    assert 'data-tab="all"' in html and 'data-tab="applied"' in html
    assert 'id="select-all"' in html and 'id="delete-selected"' in html and 'id="selected-count"' in html
