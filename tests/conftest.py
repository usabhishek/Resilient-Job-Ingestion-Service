import mongomock
import pytest
from httpx import AsyncClient, ASGITransport
from app.database import get_db, setup_database
from app.main import app

# Test fixtures for mock payloads
GREENHOUSE_SAMPLE_PAYLOAD = {
    "jobs": [
        {
            "id": 1001,
            "title": "Senior Infrastructure Engineer",
            "content": "<p>Build high scale systems</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/1001",
            "location": {"name": "Austin, TX / Remote"},
            "updated_at": "2026-08-01T12:00:00Z"
        },
        {
            "id": 1002,
            "title": "Staff Security Engineer",
            "content": "<p>Protect distributed networks</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/1002",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-08-02T15:30:00Z"
        }
    ]
}

LEVER_SAMPLE_PAYLOAD = [
    {
        "id": "lever-uuid-2001",
        "text": "Senior Platform Engineer",
        "descriptionPlain": "Design and build core platform primitives.",
        "hostedUrl": "https://jobs.lever.co/netflix/lever-uuid-2001",
        "categories": {"location": "Los Gatos, CA", "team": "Core Platform"},
        "createdAt": 1722500000000
    },
    {
        "id": "lever-uuid-2002",
        "text": "Data Engineering Lead",
        "descriptionPlain": "Lead stream processing pipelines.",
        "hostedUrl": "https://jobs.lever.co/netflix/lever-uuid-2002",
        "categories": {"location": "Remote - US", "team": "Data Infrastructure"},
        "createdAt": 1722510000000
    }
]


@pytest.fixture
def db():
    """Fresh in-memory MongoDB (mongomock) with the same indexes and default sources as production."""
    database = mongomock.MongoClient(tz_aware=True)["test_job_ingestion"]
    setup_database(database)
    return database


@pytest.fixture
async def make_client(db):
    """Factory for independent browsers (each with its own cookies) talking to the app."""
    app.dependency_overrides[get_db] = lambda: db
    opened = []

    def factory() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        opened.append(client)
        return client

    yield factory
    for client in opened:
        await client.aclose()
    app.dependency_overrides.clear()


async def signup(client: AsyncClient, name="Asha", email="asha@example.com",
                 password="password123", answer="Springfield School"):
    return await client.post("/signup", data={"name": name, "email": email,
                                              "password": password, "answer": answer})


async def login(client: AsyncClient, email, password):
    return await client.post("/login", data={"email": email, "password": password})
