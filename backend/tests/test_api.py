"""API tests with a fake resolver and a real temporary SQLite database."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from kora.api.app import create_app, get_aggregator
from kora.storage.database import Settings


class FakeAggregator:
    def __init__(self, profile):
        self.profile = profile
        self.calls = []

    async def build_profile(self, query, pick=0, include_about=True):
        self.calls.append((query, pick, include_about))
        if "nobody" in query.casefold():
            return None
        return self.profile


@pytest.fixture
def client(tmp_path, sample_profile):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api-test.db'}",
        auto_create_schema=True,
        cache_dir=None,
    )
    app = create_app(settings)
    fake = FakeAggregator(sample_profile)
    app.dependency_overrides[get_aggregator] = lambda: fake
    with TestClient(app) as test_client:
        test_client.fake_aggregator = fake
        yield test_client


def test_health_and_resolve_persist_roundtrip(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"

    response = client.post("/v1/profiles/resolve", json={"query": "Chinua Achebe"})
    assert response.status_code == 200
    body = response.json()
    assert body["stored"] is True
    assert body["scholar_id"] == 1
    assert body["person"]["display_name"] == "Chinua Achebe"
    assert {work["title"] for work in body["works"]} >= {
        "Things Fall Apart",
        "Winds of Change",
        "Tapestry",
        "Conversations with Chinua Achebe",
    }
    assert body["flagged"][0]["title"] == "A Future Book"

    listing = client.get("/v1/scholars")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["display_name"] == "Chinua Achebe"
    assert rows[0]["birth_year"] == 1930
    assert rows[0]["death_year"] == 2013
    assert rows[0]["description"] == "Nigerian writer"
    assert rows[0]["work_count"] == 3
    assert rows[0]["about_count"] == 1
    assert rows[0]["updated_at"]

    stored = client.get("/v1/scholars/1")
    assert stored.status_code == 200
    stored_body = stored.json()
    assert stored_body["stored"] is True
    assert stored_body["query"] == "Chinua Achebe"
    assert len(stored_body["works"]) == 4
    assert stored_body["bio"] == "Chinua Achebe was a Nigerian novelist."
    assert stored_body["source_status"]["openlibrary.by"].startswith("ok")
    things = next(w for w in stored_body["works"] if w["title"] == "Things Fall Apart")
    assert things["role"] == "author"
    assert len(things["records"]) == 2
    assert things["sources"] == ["openalex", "openlibrary"]
    about = next(
        w for w in stored_body["works"] if w["title"] == "Conversations with Chinua Achebe"
    )
    assert about["relation"] == "about"

    assert client.get("/v1/scholars/999").status_code == 404


def test_live_profile_and_not_found(client):
    live = client.get("/v1/profiles/Wole Soyinka")
    assert live.status_code == 200
    assert live.json()["stored"] is False
    assert live.json()["scholar_id"] is None
    assert client.fake_aggregator.calls[-1] == ("Wole Soyinka", 0, True)

    missing = client.post("/v1/profiles/resolve", json={"query": "Nobody"})
    assert missing.status_code == 404


def test_persist_false_does_not_write(client):
    response = client.post(
        "/v1/profiles/resolve",
        json={"query": "Chinua Achebe", "persist": False, "include_about": False},
    )
    assert response.status_code == 200
    assert response.json()["stored"] is False
    assert response.json()["scholar_id"] is None
    assert client.get("/v1/scholars").json() == []
    assert client.fake_aggregator.calls[-1] == ("Chinua Achebe", 0, False)
