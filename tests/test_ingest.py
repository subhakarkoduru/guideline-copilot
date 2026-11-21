import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.index import IndexCorruptError, InMemoryIndex
from app.ingest import ingest, main, read_last_ingest
from app.main import app


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
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


def test_corrupt_index_raises_and_is_not_overwritten(index_dir):
    p = f"{index_dir}/index.json"
    open(p, "w").write("{not json")
    with pytest.raises(IndexCorruptError):
        InMemoryIndex(index_dir)
    # health does not touch the index, so it still works
    assert TestClient(app).get("/health").status_code == 200
    assert open(p).read() == "{not json"


def test_cli_corrupt_index_fails_without_overwrite(index_dir, tmp_path, capsys):
    p = f"{index_dir}/index.json"
    open(p, "w").write("{not json")
    docs = tmp_path / "d.txt"
    docs.write_text("x\n")
    assert main(["app.ingest", str(docs)]) == 1
    assert "error" in capsys.readouterr().err
    assert open(p).read() == "{not json"


def test_write_is_atomic_no_temp_files_left(index_dir, monkeypatch):
    ingest(["a"], InMemoryIndex(index_dir), index_dir)
    import os
    assert sorted(os.listdir(index_dir)) == ["index.json", "meta.json"]
    idx = InMemoryIndex(index_dir)

    def fail(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr("app.index.os.replace", fail)
    with pytest.raises(OSError):
        idx.add(["b"])
    monkeypatch.undo()
    assert InMemoryIndex(index_dir).size() == 1
    assert [f for f in os.listdir(index_dir) if f.endswith(".tmp")] == []


def test_cli_missing_file(index_dir, capsys):
    assert main(["app.ingest", "/nonexistent/file.txt"]) == 1
    assert "not found" in capsys.readouterr().err


def test_empty_input_does_not_update_last_ingest(index_dir, tmp_path, capsys):
    ingest(["a"], InMemoryIndex(index_dir), index_dir)
    before = open(f"{index_dir}/meta.json").read()
    empty = tmp_path / "empty.txt"
    empty.write_text("\n  \n")
    assert main(["app.ingest", str(empty)]) == 0
    assert open(f"{index_dir}/meta.json").read() == before


def test_cli_rejects_oversized_file(index_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAX_INGEST_BYTES", "10")
    big = tmp_path / "big.txt"
    big.write_text("x" * 11)
    assert main(["app.ingest", str(big)]) == 1
    assert "larger than" in capsys.readouterr().err
    assert InMemoryIndex(index_dir).size() == 0


def test_cli_rejects_directory(index_dir, tmp_path, capsys):
    assert main(["app.ingest", str(tmp_path)]) == 1
    assert "regular file" in capsys.readouterr().err


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


def test_non_list_index_raises(index_dir):
    open(f"{index_dir}/index.json", "w").write("{}")
    with pytest.raises(IndexCorruptError, match="not a JSON list"):
        InMemoryIndex(index_dir)


def test_cli_non_utf8_input_fails(index_dir, tmp_path, capsys):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00bad\n")
    assert main(["app.ingest", str(bad)]) == 1
    assert "error" in capsys.readouterr().err
    assert InMemoryIndex(index_dir).size() == 0
