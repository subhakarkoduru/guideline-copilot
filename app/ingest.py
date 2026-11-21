import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.config import get_settings
from app.index import InMemoryIndex, VectorIndex


def meta_path(index_dir: str) -> Path:
    return Path(index_dir) / "meta.json"


def read_last_ingest(index_dir: str) -> Optional[str]:
    try:
        return json.loads(meta_path(index_dir).read_text()).get("last_ingest_at")
    except (OSError, ValueError, AttributeError):
        return None


def ingest(docs: List[str], index: VectorIndex, index_dir: str) -> str:
    """Add docs to the index and record the ingest time (UTC ISO-8601)."""
    index.add(docs)
    ts = datetime.now(timezone.utc).isoformat()
    path = meta_path(index_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_ingest_at": ts}))
    return ts


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.ingest <file-with-one-doc-per-line>")
        return 2
    docs = [ln for ln in Path(argv[1]).read_text().splitlines() if ln.strip()]
    index_dir = get_settings().index_dir
    ingest(docs, InMemoryIndex(index_dir), index_dir)
    print(f"ingested {len(docs)} docs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
