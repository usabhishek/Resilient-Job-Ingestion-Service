import pytest
from unittest.mock import AsyncMock, patch
from app.api.routes_api import pipeline as api_pipeline
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, signup, login


async def ingest(client):
    with patch.object(api_pipeline.adapters["greenhouse"].http_client, "get_json",
                      AsyncMock(return_value=GREENHOUSE_SAMPLE_PAYLOAD)):
        return await client.post("/api/ingest", json={"source": "greenhouse", "board_token": "cloudflare"})


@pytest.mark.asyncio
async def test_two_users_have_separate_data_even_for_the_same_company(make_client):
    a, b = make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    assert (await ingest(a)).json()["new_count"] == 2
    assert (await ingest(b)).json()["new_count"] == 2            # not treated as duplicates of Asha's
    assert (await ingest(a)).json()["duplicate_count"] == 2      # but Asha's own repeat is

    a_jobs = (await a.get("/api/jobs")).json()
    b_jobs = (await b.get("/api/jobs")).json()
    assert a_jobs["total"] == 2 and b_jobs["total"] == 2
    assert {j["id"] for j in a_jobs["items"]}.isdisjoint({j["id"] for j in b_jobs["items"]})
    assert len((await a.get("/api/runs")).json()) == 2
    assert len((await b.get("/api/runs")).json()) == 1


@pytest.mark.asyncio
async def test_user_cannot_touch_another_users_job(make_client):
    a, b = make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    await ingest(a)
    job_id = (await a.get("/api/jobs")).json()["items"][0]["id"]
    assert (await b.get(f"/api/jobs/{job_id}")).status_code == 404
    assert (await b.patch(f"/api/jobs/{job_id}", json={"title": "x"})).status_code == 404
    assert (await b.delete(f"/api/jobs/{job_id}")).status_code == 404
    assert (await a.get(f"/api/jobs/{job_id}")).status_code == 200


@pytest.mark.asyncio
async def test_job_crud_and_search_and_paging_via_api(make_client):
    client = make_client()
    await signup(client)
    await ingest(client)
    assert (await client.get("/api/jobs?search=security")).json()["total"] == 1
    page1 = (await client.get("/api/jobs?limit=1&page=1")).json()
    page2 = (await client.get("/api/jobs?limit=1&page=2")).json()
    assert page1["pages"] == 2 and page1["items"][0]["id"] != page2["items"][0]["id"]

    job_id = page1["items"][0]["id"]
    patched = await client.patch(f"/api/jobs/{job_id}", json={"title": "Renamed"})
    assert patched.status_code == 200 and patched.json()["title"] == "Renamed"
    assert (await client.patch(f"/api/jobs/{job_id}", json={})).status_code == 400
    assert (await client.delete(f"/api/jobs/{job_id}")).status_code == 204
    assert (await client.get(f"/api/jobs/{job_id}")).status_code == 404
    assert (await client.get("/api/jobs")).json()["total"] == 1


@pytest.mark.asyncio
async def test_user_dashboard_is_lean_and_has_no_api_health(make_client):
    client = make_client()
    await signup(client, name="Asha Rao")
    html = (await client.get("/")).text
    assert "Welcome, Asha Rao" in html
    assert 'id="fallback"' in html                    # fallback checkbox
    assert 'id="search"' in html and 'id="prev"' in html and 'id="next"' in html
    low = html.lower()
    assert "health" not in low and "latency" not in low and "audit" not in low
    assert "greenhouse" in low                        # only as a source choice
    assert (await client.get("/api/analytics")).status_code == 200      # API exists, UI does not show it


@pytest.mark.asyncio
async def test_update_name_and_change_password(make_client):
    client = make_client()
    await signup(client)
    me = (await client.patch("/api/me", json={"name": "Asha R"})).json()
    assert me["name"] == "Asha R"
    assert "Welcome, Asha R" in (await client.get("/")).text

    other = make_client()                                  # a second logged-in browser
    await login(other, "asha@example.com", "password123")

    wrong = await client.post("/api/me/password", json={"current_password": "bad", "new_password": "newpassword1"})
    assert wrong.status_code == 400
    weak = await client.post("/api/me/password", json={"current_password": "password123", "new_password": "x"})
    assert weak.status_code == 422
    ok = await client.post("/api/me/password", json={"current_password": "password123",
                                                     "new_password": "newpassword1"})
    assert ok.status_code == 200
    assert (await client.get("/api/me")).status_code == 200      # this browser stays logged in
    assert (await other.get("/api/me")).status_code == 401       # other sessions are logged out
    assert (await login(make_client(), "asha@example.com", "newpassword1")).status_code == 303


@pytest.mark.asyncio
async def test_user_can_delete_own_account_and_all_data(make_client, db):
    a, b = make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    await ingest(a); await ingest(b)

    assert (await a.post("/api/me/delete", json={"password": "wrong"})).status_code == 400
    assert (await a.post("/api/me/delete", json={"password": "password123"})).status_code == 200

    assert db.users.find_one({"email": "asha@example.com"}) is None
    assert db.jobs.count_documents({"owner_id": {"$exists": True}}) == 2          # only Ben's remain
    assert db.ingestion_runs.count_documents({}) == 1
    assert (await a.get("/api/me")).status_code == 401
    assert (await login(make_client(), "asha@example.com", "password123")).status_code == 401
    assert (await b.get("/api/jobs")).json()["total"] == 2
