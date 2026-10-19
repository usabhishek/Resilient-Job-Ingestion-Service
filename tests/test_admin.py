import pytest
from unittest.mock import AsyncMock, patch
from app.api.routes_api import pipeline as api_pipeline
from app.api.routes_admin import shared_pipeline
from app.adapters.base import SourceHealthResult
from app.services import users as user_service
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, signup, login

ADMIN = ("admin@example.com", "adminpass123")


async def ingest(client):
    with patch.object(api_pipeline.adapters["greenhouse"].http_client, "get_json",
                      AsyncMock(return_value=GREENHOUSE_SAMPLE_PAYLOAD)):
        await client.post("/api/ingest", json={"source": "greenhouse", "board_token": "cloudflare"})


async def setup_world(make_client, db):
    """Two normal users with data plus a logged-in admin."""
    a, b, admin = make_client(), make_client(), make_client()
    await signup(a, "Asha", "asha@example.com")
    await signup(b, "Ben", "ben@example.com")
    await ingest(a); await ingest(b)
    assert user_service.seed_admin(db, *ADMIN) is True
    assert (await login(admin, *ADMIN)).status_code == 303
    return a, b, admin


@pytest.mark.asyncio
async def test_seed_admin_only_when_configured_and_only_once(db):
    assert user_service.seed_admin(db, None, None) is False
    assert user_service.seed_admin(db, *ADMIN) is True
    assert user_service.seed_admin(db, *ADMIN) is False
    assert db.users.count_documents({"role": "admin"}) == 1


@pytest.mark.asyncio
async def test_normal_users_cannot_use_admin_api_or_page(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    for path in ["/api/admin/summary", "/api/admin/users", "/api/admin/runs", "/api/admin/runs-per-user"]:
        assert (await a.get(path)).status_code == 403, path
    assert (await a.delete("/api/admin/ingestions")).status_code == 403
    assert (await a.delete("/api/admin/users/anything")).status_code == 403
    page = await a.get("/admin")
    assert page.status_code == 303 and page.headers["location"] == "/"
    assert db.jobs.count_documents({}) == 4                      # nothing was deleted


@pytest.mark.asyncio
async def test_admin_lands_on_admin_dashboard_with_health(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    home = await admin.get("/")
    assert home.status_code == 303 and home.headers["location"] == "/admin"
    html = (await admin.get("/admin")).text
    assert "Welcome, Admin" in html and "Clear all ingestions" in html and "theme-toggle" in html

    ok = SourceHealthResult(source_name="x", is_healthy=True, latency_ms=12.0, message="OK")
    with patch.object(shared_pipeline, "get_health", AsyncMock(return_value=ok)):
        s = (await admin.get("/api/admin/summary")).json()
    assert s["users"] == 3 and s["jobs"] == 4 and s["runs"] == 2
    assert s["sources"]["greenhouse"]["healthy"] is True


@pytest.mark.asyncio
async def test_admin_sees_users_and_all_ingestions(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    users = (await admin.get("/api/admin/users")).json()
    by_email = {u["email"]: u for u in users}
    assert by_email["asha@example.com"]["jobs"] == 2 and by_email["asha@example.com"]["runs"] == 1
    assert by_email["admin@example.com"]["jobs"] == 0
    assert "password_hash" not in str(users) and "recovery_hash" not in str(users)

    runs = (await admin.get("/api/admin/runs?limit=10")).json()
    assert runs["total"] == 2
    assert {r["user_name"] for r in runs["items"]} == {"Asha", "Ben"}
    per_user = (await admin.get("/api/admin/runs-per-user")).json()
    assert len(per_user) == 2 and all(p["runs"] == 1 for p in per_user)


@pytest.mark.asyncio
async def test_admin_clears_one_users_ingestions(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    uid = db.users.find_one({"email": "asha@example.com"})["_id"]
    r = await admin.delete(f"/api/admin/users/{uid}/ingestions")
    assert r.status_code == 200 and r.json() == {"detail": "Deleted 2 jobs and 1 ingestion runs.", "jobs": 2, "runs": 1}
    assert (await a.get("/api/jobs")).json()["total"] == 0
    assert (await a.get("/api/me")).status_code == 200            # account is still there
    assert (await b.get("/api/jobs")).json()["total"] == 2        # Ben untouched
    assert (await admin.delete("/api/admin/users/nope/ingestions")).status_code == 404


@pytest.mark.asyncio
async def test_admin_deletes_a_user_with_all_data(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    uid = db.users.find_one({"email": "asha@example.com"})["_id"]
    assert (await admin.delete(f"/api/admin/users/{uid}")).status_code == 200
    assert db.users.find_one({"_id": uid}) is None
    assert db.jobs.count_documents({"owner_id": uid}) == 0
    assert db.ingestion_runs.count_documents({"owner_id": uid}) == 0
    assert (await a.get("/api/me")).status_code == 401            # deleted user is logged out at once
    assert (await b.get("/api/jobs")).json()["total"] == 2
    assert (await admin.delete(f"/api/admin/users/{uid}")).status_code == 404


@pytest.mark.asyncio
async def test_admin_account_cannot_be_deleted(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    admin_id = db.users.find_one({"role": "admin"})["_id"]
    assert (await admin.delete(f"/api/admin/users/{admin_id}")).status_code == 400
    assert (await admin.post("/api/me/delete", json={"password": ADMIN[1]})).status_code == 400
    assert db.users.find_one({"_id": admin_id}) is not None


@pytest.mark.asyncio
async def test_admin_clears_all_ingestions_for_everyone(make_client, db):
    a, b, admin = await setup_world(make_client, db)
    r = await admin.delete("/api/admin/ingestions")
    assert r.status_code == 200 and r.json()["jobs"] == 4 and r.json()["runs"] == 2
    assert db.jobs.count_documents({}) == 0 and db.ingestion_runs.count_documents({}) == 0
    assert db.users.count_documents({}) == 3                      # accounts are kept
    assert (await a.get("/api/jobs")).json()["total"] == 0
