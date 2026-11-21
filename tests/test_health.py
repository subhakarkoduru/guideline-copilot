from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.index import InMemoryIndex
from app.ingest import ingest
from app.main import app, create_app


TOKEN = "tttttttttttttttttttttttttttttttt"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    return TestClient(app), str(tmp_path)


def test_health_empty(client):
    c, _ = client
    r = c.get("/health", headers=AUTH)
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
    body = c.get("/health", headers=AUTH).json()
    assert body["index_size"] == 3
    ts = datetime.fromisoformat(body["last_ingest_at"])
    assert datetime.now(timezone.utc) - ts < timedelta(minutes=1)


def test_model_env_override(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("MODEL_NAME", "other-model")
    assert c.get("/health", headers=AUTH).json()["model"] == "other-model"


def test_health_minimal_in_production_without_token(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("HEALTH_TOKEN", raising=False)
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_health_token_gates_details(client):
    c, d = client
    ingest(["a"], InMemoryIndex(d), d)
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/health", headers={"Authorization": "Bearer wrong"}).json() == {"status": "ok"}
    assert c.get("/health", headers={"Authorization": TOKEN}).json() == {"status": "ok"}
    body = c.get("/health", headers=AUTH).json()
    assert body["model"] == "test-model"
    assert body["index_size"] == 1
    assert body["last_ingest_at"]


def test_health_does_not_load_index(client, monkeypatch):
    c, d = client
    ingest(["a", "b"], InMemoryIndex(d), d)

    def boom(*a, **k):
        raise AssertionError("index loaded")

    monkeypatch.setattr("app.index.InMemoryIndex.__init__", boom)
    assert c.get("/health", headers=AUTH).json()["index_size"] == 2


def test_docs_disabled_in_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    c = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_docs_enabled_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    c = TestClient(create_app())
    assert c.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("env", ["development", "production", None])
def test_no_token_always_minimal_even_in_development(tmp_path, monkeypatch, env):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("HEALTH_TOKEN", raising=False)
    if env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", env)
    c = TestClient(create_app())
    assert c.get("/health").json() == {"status": "ok"}
    # a bearer header with no configured token must not unlock anything
    assert c.get("/health", headers={"Authorization": "Bearer anything"}).json() == {"status": "ok"}


def test_empty_token_treated_as_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HEALTH_TOKEN", "")
    assert TestClient(app).get("/health", headers={"Authorization": "Bearer "}).json() == {"status": "ok"}


def test_short_health_token_rejected(monkeypatch):
    from pydantic import ValidationError

    from app.config import get_settings

    monkeypatch.setenv("HEALTH_TOKEN", "x" * 31)
    with pytest.raises(ValidationError, match="at least 32"):
        get_settings()
    with pytest.raises(ValidationError):
        create_app()
    monkeypatch.setenv("HEALTH_TOKEN", "x" * 32)
    assert get_settings().health_token == "x" * 32
