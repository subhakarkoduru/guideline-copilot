from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.index import InMemoryIndex
from app.ingest import ingest
from app.main import create_app


TOKEN = "k3J9xQ2mZ7vB1nL8wR4tY6uP0cD5aF_h"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    return TestClient(create_app()), str(tmp_path)


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
    c = TestClient(create_app())  # settings are read once, at startup
    assert c.get("/health", headers=AUTH).json()["model"] == "other-model"


def test_health_minimal_in_production_without_token(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("HEALTH_TOKEN", raising=False)
    assert TestClient(create_app()).get("/health").json() == {"status": "ok"}


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
    assert TestClient(create_app()).get("/health", headers={"Authorization": "Bearer "}).json() == {"status": "ok"}


def _bad(monkeypatch, value):
    from app.config import SettingsError, get_settings

    monkeypatch.setenv("HEALTH_TOKEN", value)
    with pytest.raises(SettingsError) as ei:
        get_settings()
    return ei.value


def test_short_health_token_rejected(monkeypatch):
    from app.config import get_settings

    err = _bad(monkeypatch, "x" * 31)
    assert "at least 32" in str(err)
    ok = "k3J9xQ2mZ7vB1nL8wR4tY6uP0cD5aF_h"
    monkeypatch.setenv("HEALTH_TOKEN", ok)
    assert get_settings().health_token_value() == ok


def test_bad_token_fails_at_startup_not_per_request(monkeypatch):
    from app.config import SettingsError

    monkeypatch.setenv("HEALTH_TOKEN", "short")
    with pytest.raises(SettingsError, match="HEALTH_TOKEN"):
        create_app()  # fail fast, before any request can exist


def test_env_change_after_startup_cannot_cause_500(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    c = TestClient(create_app())
    monkeypatch.setenv("HEALTH_TOKEN", "bad")  # settings are not re-read per request
    assert c.get("/health").status_code == 200
    assert c.get("/health", headers=AUTH).status_code == 200


@pytest.mark.parametrize("v", [" " * 32, "x" * 32 + " ", " " + "x" * 32, "\t" * 32])
def test_padded_or_blank_health_token_rejected(monkeypatch, v):
    _bad(monkeypatch, v)


@pytest.mark.parametrize(
    "v",
    [
        "k3J9xQ2mZ7vB1nL8wR4tY6u\nP0cD5aF_h",
        "k3J9xQ2mZ7vB1nL8wR4tY6u\tP0cD5aF_h",
        "k3J9xQ2mZ7vB1nL8wR4tY6u P0cD5aF_h",
        "k3J9xQ2mZ7vB1nL8wR4tY6u\u00e9P0cD5aF_h",
    ],
)
def test_health_token_with_internal_control_chars_rejected(monkeypatch, v):
    _bad(monkeypatch, v)


def test_token_not_in_error_string_or_errors_list(monkeypatch):
    import json

    from pydantic import ValidationError

    from app.config import Settings, SettingsError, get_settings

    for secret in ["SuperSecret123", " secretvalue" + "z" * 30 + " ", "abcdefgh" * 4]:
        monkeypatch.setenv("HEALTH_TOKEN", secret)
        with pytest.raises(SettingsError) as ei:
            get_settings()
        e = ei.value
        for text in (str(e), repr(e), repr(e.args), repr(e.__cause__), repr(e.__context__)):
            assert secret.strip() not in text
        assert not isinstance(e, ValidationError)  # no .errors() carrying the input
    # the raw Settings object masks the secret too
    monkeypatch.setenv("HEALTH_TOKEN", "SuperSecret123")
    s = Settings()
    assert "SuperSecret123" not in repr(s) and "SuperSecret123" not in str(s)
    # other-field validation errors cannot carry the token either
    monkeypatch.setenv("MAX_INGEST_BYTES", "notanint")
    with pytest.raises(ValidationError) as ei:
        Settings()
    assert "SuperSecret123" not in str(ei.value)
    assert "SuperSecret123" not in json.dumps(ei.value.errors(), default=str)


@pytest.mark.parametrize(
    "v",
    [
        "x" * 32,
        "ab" * 16,
        "abc" * 11,
        "abcdefgh" * 4,  # 8 distinct, periodic
        "xY9#kL2@" * 4,
        "xY9#kL2@pQ" * 4,
        "abcdefghijklmnopqrstuvwxyz012345",  # sequential
        "0123456789abcdef" * 2,
        "a" * 14 + "k3J9xQ2mZ7vB1nL8wR",  # one char dominates
        "k3J9xQ2mZ7vB1nL8wR4tY6u" * 2 + "k3J9",  # repeated block with a ragged tail
    ],
)
def test_weak_tokens_rejected(monkeypatch, v):
    assert "too weak" in str(_bad(monkeypatch, v))


def test_realistic_tokens_accepted():
    import base64
    import os

    from app.config import health_token_problem

    for _ in range(3000):
        for tok in (
            os.urandom(32).hex(),
            os.urandom(16).hex(),  # 32 hex chars, the shortest allowed
            base64.b64encode(os.urandom(32)).decode(),
            base64.urlsafe_b64encode(os.urandom(32)).decode(),
        ):
            assert health_token_problem(tok) is None, tok
    assert health_token_problem(TOKEN) is None


def test_bearer_scheme_case_insensitive(client):
    c, _ = client
    for scheme in ["bearer", "BEARER", "BeArEr"]:
        r = c.get("/health", headers={"Authorization": f"{scheme} {TOKEN}"})
        assert r.json()["model"] == "test-model"
    assert c.get("/health", headers={"Authorization": f"bearer {TOKEN}x"}).json() == {"status": "ok"}
    assert c.get("/health", headers={"Authorization": f"Basic {TOKEN}"}).json() == {"status": "ok"}
