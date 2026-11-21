import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.config import get_settings
from app.index import IndexCorruptError, InMemoryIndex, VectorIndex, atomic_write_text


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


def read_index_size(index_dir: str) -> int:
    """Cheap size lookup from meta.json; never loads the index."""
    size = _read_meta(index_dir).get("index_size", 0)
    return size if isinstance(size, int) and size >= 0 else 0


def ingest(docs: List[str], index: VectorIndex, index_dir: str) -> Optional[str]:
    """Add docs, record ingest time (UTC ISO-8601) and index size in meta.json.

    Returns the timestamp, or the previous one unchanged if docs is empty.
    """
    if not docs:
        return read_last_ingest(index_dir)
    index.add(docs)
    ts = datetime.now(timezone.utc).isoformat()
    atomic_write_text(
        meta_path(index_dir),
        json.dumps({"last_ingest_at": ts, "index_size": index.size()}),
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
    settings = get_settings()
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
    except IndexCorruptError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"ingested {len(docs)} docs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
