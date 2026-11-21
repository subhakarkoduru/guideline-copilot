from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.index import InMemoryIndex
from app.ingest import ingest
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_NAME", "test-model")
    return TestClient(app), str(tmp_path)


def test_health_empty(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "model": "test-model",
        "index_size": 0,
        "last_ingest_at": None,
    }


def test_health_after_ingest(client):
    c, d = client
    ingest(["a", "b", "c"], InMemoryIndex(d), d)
    body = c.get("/health").json()
    assert body["index_size"] == 3
    ts = datetime.fromisoformat(body["last_ingest_at"])
    assert datetime.now(timezone.utc) - ts < timedelta(minutes=1)


def test_model_env_override(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("MODEL_NAME", "other-model")
    assert c.get("/health").json()["model"] == "other-model"
