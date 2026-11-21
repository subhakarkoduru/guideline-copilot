import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.index import IndexCorruptError, InMemoryIndex
from app.ingest import ingest, main, read_last_ingest
from app.main import app

TOKEN = "k3J9xQ2mZ7vB1nL8wR4tY6uP0cD5aF_h"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", str(tmp_path))
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    return str(tmp_path)


def test_default_model_name_when_env_unset(index_dir):
    body = TestClient(app).get("/health", headers=AUTH).json()
    assert body["model"] == "claude-sonnet-5-5"


def test_index_size_accumulates_across_ingests(index_dir):
    ingest(["a", "b"], InMemoryIndex(index_dir), index_dir)
    first = read_last_ingest(index_dir)
    ingest(["c"], InMemoryIndex(index_dir), index_dir)
    body = TestClient(app).get("/health", headers=AUTH).json()
    assert body["index_size"] == 3
    assert body["last_ingest_at"] >= first


def test_corrupt_index_raises_and_is_not_overwritten(index_dir):
    p = f"{index_dir}/index.json"
    open(p, "w").write("{not json")
    with pytest.raises(IndexCorruptError):
        InMemoryIndex(index_dir)
    # health does not touch the index, so it still works
    assert TestClient(app).get("/health", headers=AUTH).status_code == 200
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
    assert sorted(os.listdir(index_dir)) == [".lock", "index.json", "meta.json"]
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
    body = TestClient(app).get("/health", headers=AUTH).json()
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


def test_legacy_meta_without_index_size_falls_back_to_count(index_dir):
    open(f"{index_dir}/index.json", "w").write('["x", "y"]')
    open(f"{index_dir}/meta.json", "w").write('{"last_ingest_at": "2024-01-01T00:00:00+00:00"}')
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == 2


def test_direct_add_after_ingest_does_not_leave_stale_size(index_dir):
    # Tester repro: index.json changes without meta.json being updated.
    ingest(["a"], InMemoryIndex(index_dir), index_dir)
    InMemoryIndex(index_dir).add(["b", "c"])
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == 3


def test_crash_between_index_and_meta_writes_is_consistent(index_dir, monkeypatch):
    ingest(["a"], InMemoryIndex(index_dir), index_dir)

    def boom(path, text):
        raise OSError("simulated crash")

    import app.ingest as ing

    monkeypatch.setattr(ing, "atomic_write_text", boom)
    with pytest.raises(OSError):
        ingest(["b", "c"], InMemoryIndex(index_dir), index_dir)
    monkeypatch.undo()
    monkeypatch.setenv("INDEX_DIR", index_dir)
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == 3


def test_concurrent_ingests_do_not_drop_documents(index_dir):
    import threading

    n_threads, per = 8, 5
    start = threading.Barrier(n_threads)
    errors = []

    def work(i):
        try:
            idx = InMemoryIndex(index_dir)  # all start from the same (empty) snapshot
            start.wait()
            ingest([f"t{i}-{j}" for j in range(per)], idx, index_dir)
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n_threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert InMemoryIndex(index_dir).size() == n_threads * per
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == n_threads * per


def test_concurrent_processes_do_not_drop_documents(index_dir, tmp_path_factory):
    import subprocess
    import sys

    src = tmp_path_factory.mktemp("src")
    procs = []
    for i in range(4):
        f = src / f"in{i}.txt"
        f.write_text("\n".join(f"p{i}-{j}" for j in range(5)))
        procs.append(
            subprocess.Popen([sys.executable, "-m", "app.ingest", str(f)], stdout=subprocess.DEVNULL)
        )
    assert all(p.wait() == 0 for p in procs)
    assert InMemoryIndex(index_dir).size() == 20


def test_lock_released_after_failed_ingest(index_dir, monkeypatch):
    import app.ingest as ing
    from app.index import index_lock

    def boom(path, text):
        raise OSError("simulated failure")

    monkeypatch.setattr(ing, "atomic_write_text", boom)
    with pytest.raises(OSError):
        ingest(["a"], InMemoryIndex(index_dir), index_dir)
    monkeypatch.undo()
    # the failed call must not leave the lock held
    with index_lock(index_dir):
        pass
    monkeypatch.setenv("INDEX_DIR", index_dir)
    monkeypatch.setenv("HEALTH_TOKEN", TOKEN)
    ingest(["b"], InMemoryIndex(index_dir), index_dir)
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == 2


def test_lock_file_not_symlink_followed(tmp_path):
    import os

    import pytest

    from app.index import index_lock

    target = tmp_path / "victim"
    target.write_text("keep")
    d = tmp_path / "idx"
    d.mkdir()
    os.symlink(target, d / ".lock")
    with pytest.raises(OSError):
        with index_lock(str(d)):
            pass
    assert target.read_text() == "keep"


def test_lock_file_mode_0600(tmp_path):
    from app.index import index_lock

    with index_lock(str(tmp_path)):
        pass
    assert (tmp_path / ".lock").stat().st_mode & 0o777 == 0o600


def test_lock_timeout_raises_clear_error(tmp_path, monkeypatch):
    import fcntl
    import os

    import pytest

    import app.index as idx

    monkeypatch.setattr(idx, "LOCK_TIMEOUT_SECONDS", 0.2)
    fd = os.open(tmp_path / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(idx.IndexLockTimeout, match="timed out"):
            with idx.index_lock(str(tmp_path)):
                pass
    finally:
        os.close(fd)


def test_drifted_fingerprint_parses_once(tmp_path, monkeypatch):
    import app.ingest as ing
    from app.index import InMemoryIndex

    InMemoryIndex(str(tmp_path)).add(["a", "b"])  # no meta.json => drift
    calls = []
    orig = InMemoryIndex._load

    def counting(self):
        calls.append(1)
        return orig(self)

    monkeypatch.setattr(InMemoryIndex, "_load", counting)
    ing._recount_cache.clear()
    assert ing.read_index_size(str(tmp_path)) == 2
    assert ing.read_index_size(str(tmp_path)) == 2
    assert len(calls) == 1
    InMemoryIndex(str(tmp_path)).add(["c"])  # new fingerprint => recount
    assert ing.read_index_size(str(tmp_path)) == 3


def test_corrupt_index_health_reports_null_index_size(index_dir):
    # Tester addition: an unreadable index must surface as null, not a stale number.
    ingest(["a"], InMemoryIndex(index_dir), index_dir)
    open(f"{index_dir}/index.json", "w").write("{bad json")
    body = TestClient(app).get("/health", headers=AUTH).json()
    assert body["status"] == "ok"
    assert body["index_size"] is None


@pytest.mark.parametrize("bad_size", [-1, True, "7", None])
def test_invalid_recorded_size_falls_back_to_count(index_dir, bad_size):
    # Tester addition: a non-trustworthy index_size in meta must not be returned as-is.
    from app.index import index_signature

    InMemoryIndex(index_dir).add(["a", "b"])
    sig = index_signature(Path(index_dir) / "index.json")
    meta = {"last_ingest_at": "2024-01-01T00:00:00+00:00", "index_size": bad_size, "index_sig": sig}
    open(f"{index_dir}/meta.json", "w").write(json.dumps(meta))
    assert TestClient(app).get("/health", headers=AUTH).json()["index_size"] == 2


@pytest.mark.xfail(
    strict=True,
    reason="known gap: ingest CLI does not catch IndexLockTimeout (raw traceback, exit 1)",
)
def test_cli_lock_timeout_reports_clean_error(index_dir, tmp_path, monkeypatch, capsys):
    import fcntl
    import os

    import app.index as idx

    monkeypatch.setattr(idx, "LOCK_TIMEOUT_SECONDS", 0.2)
    docs = tmp_path / "d.txt"
    docs.write_text("x\n")
    fd = os.open(f"{index_dir}/.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert main(["app.ingest", str(docs)]) == 1
    finally:
        os.close(fd)
    err = capsys.readouterr().err
    assert "timed out" in err and "Traceback" not in err
