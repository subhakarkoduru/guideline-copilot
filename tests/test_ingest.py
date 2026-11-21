import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.index import InMemoryIndex
from app.ingest import ingest, main, read_last_ingest
from app.main import app


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("MODEL_NAME", raising=False)
    return str(tmp_path)


def test_default_model_name_when_env_unset(index_dir):
    body = TestClient(app).get("/health").json()
    assert body["model"] == "claude-sonnet-5-5"


def test_index_size_accumulates_across_ingests(index_dir):
    ingest(["a", "b"], InMemoryIndex(index_dir), index_dir)
    first = read_last_ingest(index_dir)
    ingest(["c"], InMemoryIndex(index_dir), index_dir)
    body = TestClient(app).get("/health").json()
    assert body["index_size"] == 3
    assert body["last_ingest_at"] >= first


def test_corrupt_index_file_resets_to_empty(index_dir):
    (open(f"{index_dir}/index.json", "w")).write("{not json")
    assert InMemoryIndex(index_dir).size() == 0
    body = TestClient(app).get("/health").json()
    assert body["index_size"] == 0


def test_corrupt_meta_file_reports_null_last_ingest(index_dir):
    (open(f"{index_dir}/meta.json", "w")).write("garbage")
    body = TestClient(app).get("/health").json()
    assert body["last_ingest_at"] is None


def test_meta_without_key_reports_null(index_dir):
    (open(f"{index_dir}/meta.json", "w")).write(json.dumps({"other": 1}))
    assert read_last_ingest(index_dir) is None


def test_last_ingest_is_utc_iso(index_dir):
    ingest(["x"], InMemoryIndex(index_dir), index_dir)
    ts = read_last_ingest(index_dir)
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_persisted_index_reloads_from_disk(index_dir):
    ingest(["p", "q"], InMemoryIndex(index_dir), index_dir)
    assert json.loads(open(f"{index_dir}/index.json").read()) == ["p", "q"]
    assert InMemoryIndex(index_dir).size() == 2


def test_cli_usage_error_returns_2(capsys):
    assert main(["app.ingest"]) == 2
    assert "usage" in capsys.readouterr().out


def test_cli_ingests_file_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "idx"))
    docs = tmp_path / "docs.txt"
    docs.write_text("one\n\ntwo\n   \nthree\n")
    assert main(["app.ingest", str(docs)]) == 0
    assert "ingested 3 docs" in capsys.readouterr().out
    assert InMemoryIndex(str(tmp_path / "idx")).size() == 3
