import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.config import SettingsError, get_settings
from app.index import (
    IndexCorruptError,
    IndexLockError,
    InMemoryIndex,
    VectorIndex,
    atomic_write_text,
    index_lock,
    index_signature,
)


def meta_path(index_dir: str) -> Path:
    return Path(index_dir) / "meta.json"


def _read_meta(index_dir: str) -> dict:
    try:
        meta = json.loads(meta_path(index_dir).read_text())
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def read_last_ingest(index_dir: str) -> Optional[str]:
    return _read_meta(index_dir).get("last_ingest_at")


# Recount cache keyed by (index_dir, fingerprint) so a drifted fingerprint costs
# one full parse, not one per request. A new index.json write changes the key.
_recount_cache: dict = {}
_recount_lock = threading.Lock()  # guards check-and-fill so a drift is parsed once


def read_index_size(index_dir: str) -> Optional[int]:
    """Index size, cheaply when possible.

    meta.json records index_size plus a fingerprint of index.json. If the
    fingerprint matches, the recorded size is trusted (no index load). If it
    does not (crash between the two writes, InMemoryIndex.add called directly,
    legacy meta without index_size) we count from index.json itself, so the
    value is recomputed from the file (cached per fingerprint). Returns None if the index is unreadable.
    """
    index_path = Path(index_dir) / "index.json"
    sig = index_signature(index_path)
    if sig is None:
        return 0
    meta = _read_meta(index_dir)
    size = meta.get("index_size")
    if (
        isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
        and meta.get("index_sig") == sig
    ):
        return size
    key = (str(Path(index_dir).resolve()), tuple(sig))
    with _recount_lock:
        if key in _recount_cache:
            return _recount_cache[key]
        try:
            count = InMemoryIndex(index_dir).size()
        except IndexCorruptError:
            return None  # not cached: a fixed file changes the fingerprint anyway
        _recount_cache.clear()  # keep at most one entry; bounded memory
        _recount_cache[key] = count
        return count


def ingest(docs: List[str], index: VectorIndex, index_dir: str) -> Optional[str]:
    """Add docs, record ingest time (UTC ISO-8601) and index size in meta.json.

    Returns the timestamp, or the previous one unchanged if docs is empty.
    """
    if not docs:
        return read_last_ingest(index_dir)
    with index_lock(index_dir):
        index.add(docs)
        ts = datetime.now(timezone.utc).isoformat()
        atomic_write_text(
            meta_path(index_dir),
            json.dumps(
                {
                    "last_ingest_at": ts,
                    "index_size": index.size(),
                    "index_sig": index_signature(Path(index_dir) / "index.json"),
                }
            ),
        )
    return ts


def read_bounded(path: Path, limit: int) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    if path.stat().st_size > limit:
        raise ValueError(f"input file larger than {limit} bytes: {path}")
    with path.open("rb") as f:
        data = f.read(limit + 1)  # guards against growth after the stat
    if len(data) > limit:
        raise ValueError(f"input file larger than {limit} bytes: {path}")
    return data.decode("utf-8")


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.ingest <file-with-one-doc-per-line>")
        return 2
    try:
        settings = get_settings()
    except SettingsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        text = read_bounded(Path(argv[1]), settings.max_ingest_bytes)
    except FileNotFoundError:
        print(f"error: input file not found: {argv[1]}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    docs = [ln for ln in text.splitlines() if ln.strip()]
    try:
        ingest(docs, InMemoryIndex(settings.index_dir), settings.index_dir)
    except (IndexCorruptError, IndexLockError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"ingested {len(docs)} docs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
