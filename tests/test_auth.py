import pytest
from app.services import users as user_service
from tests.conftest import signup, login


@pytest.mark.asyncio
async def test_signup_logs_in_and_shows_welcome_name(make_client, db):
    client = make_client()
    resp = await signup(client, name="Asha Rao")
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    page = await client.get("/")
    assert page.status_code == 200
    assert "Welcome, Asha Rao" in page.text
    assert "Log out" in page.text and "theme-toggle" in page.text
    stored = db.users.find_one({"email": "asha@example.com"})
    assert stored["role"] == "user"
    assert "password123" not in str(stored) and "springfield" not in str(stored).lower()   # only hashes stored


@pytest.mark.asyncio
async def test_signup_validation_and_duplicate_email(make_client):
    client = make_client()
    assert (await signup(client, password="short")).status_code == 400
    assert (await signup(client, email="bad-email")).status_code == 400
    assert (await signup(client, name="  ")).status_code == 400
    assert (await signup(client)).status_code == 303
    again = await signup(make_client())
    assert again.status_code == 400 and "already registered" in again.text


@pytest.mark.asyncio
async def test_login_logout(make_client):
    await signup(make_client())
    client = make_client()
    assert (await login(client, "asha@example.com", "wrong-password")).status_code == 401
    assert (await client.get("/api/me")).status_code == 401

    ok = await login(client, "ASHA@example.com", "password123")       # email is case-insensitive
    assert ok.status_code == 303
    assert (await client.get("/api/me")).json()["email"] == "asha@example.com"

    out = await client.post("/logout")
    assert out.status_code == 303
    assert (await client.get("/api/me")).status_code == 401


@pytest.mark.asyncio
async def test_new_user_dashboard_data_is_empty(make_client):
    client = make_client()
    await signup(client)
    jobs = (await client.get("/api/jobs")).json()
    assert jobs["total"] == 0 and jobs["items"] == []
    assert (await client.get("/api/runs")).json() == []


@pytest.mark.asyncio
async def test_account_locks_after_repeated_wrong_passwords(make_client):
    await signup(make_client())
    client = make_client()
    for _ in range(user_service.MAX_FAILED_ATTEMPTS):
        assert (await login(client, "asha@example.com", "nope")).status_code == 401
    locked = await login(client, "asha@example.com", "password123")      # even the right password
    assert locked.status_code == 401 and "Too many failed attempts" in locked.text


@pytest.mark.asyncio
async def test_forgot_password_flow(make_client):
    await signup(make_client())
    client = make_client()
    bad = await client.post("/forgot-password", data={"email": "asha@example.com", "answer": "wrong",
                                                      "new_password": "newpassword1"})
    assert bad.status_code == 400
    short = await client.post("/forgot-password", data={"email": "asha@example.com",
                                                        "answer": "springfield school", "new_password": "abc"})
    assert short.status_code == 400
    good = await client.post("/forgot-password", data={"email": "asha@example.com",
                                                       "answer": "  Springfield   SCHOOL ",
                                                       "new_password": "newpassword1"})
    assert good.status_code == 303 and good.headers["location"].startswith("/login")
    assert (await login(client, "asha@example.com", "password123")).status_code == 401
    assert (await login(client, "asha@example.com", "newpassword1")).status_code == 303


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_gives_same_message(make_client):
    client = make_client()
    resp = await client.post("/forgot-password", data={"email": "nobody@example.com", "answer": "x",
                                                       "new_password": "newpassword1"})
    assert resp.status_code == 400 and "Email or security answer is incorrect" in resp.text


@pytest.mark.asyncio
async def test_expired_session_is_rejected(make_client, db):
    client = make_client()
    await signup(client)
    from datetime import datetime, timedelta, timezone
    db.sessions.update_many({}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert (await client.get("/api/me")).status_code == 401
    assert db.sessions.count_documents({}) == 0


@pytest.mark.asyncio
async def test_signup_cannot_create_admin(make_client, db):
    client = make_client()
    await client.post("/signup", data={"name": "Evil", "email": "evil@example.com", "password": "password123",
                                       "answer": "x", "role": "admin"})
    assert db.users.find_one({"email": "evil@example.com"})["role"] == "user"
    assert (await client.get("/api/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_user_name_is_escaped_in_pages(make_client):
    client = make_client()
    await signup(client, name="<script>alert(1)</script>")
    html = (await client.get("/")).text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
