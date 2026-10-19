import pytest
from unittest.mock import AsyncMock, patch
from app.api.routes_api import pipeline as api_pipeline
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, signup


@pytest.mark.asyncio
async def test_api_requires_login(make_client):
    client = make_client()
    assert (await client.get("/api/jobs")).status_code == 401
    assert (await client.post("/api/ingest", json={"source": "greenhouse"})).status_code == 401
    assert (await client.get("/api/runs")).status_code == 401
    assert (await client.get("/api/admin/users")).status_code == 401


@pytest.mark.asyncio
async def test_ingest_then_list_jobs_and_runs(make_client):
    client = make_client()
    await signup(client)
    with patch.object(api_pipeline.adapters["greenhouse"].http_client, "get_json",
                      AsyncMock(return_value=GREENHOUSE_SAMPLE_PAYLOAD)):
        resp = await client.post("/api/ingest", json={"source": "greenhouse", "board_token": "cloudflare",
                                                      "allow_fallback": True})
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["status"] == "SUCCESS" and summary["new_count"] == 2

    jobs = (await client.get("/api/jobs?limit=10")).json()
    assert jobs["total"] == 2 and len(jobs["items"]) == 2
    assert jobs["items"][0]["company"] == "Cloudflare"

    runs = (await client.get("/api/runs")).json()
    assert len(runs) == 1 and runs[0]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_pages_redirect_to_login_when_logged_out(make_client):
    client = make_client()
    for path in ["/", "/admin", "/account"]:
        resp = await client.get(path)
        assert resp.status_code == 303 and resp.headers["location"] == "/login", path
