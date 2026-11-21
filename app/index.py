import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Protocol


class IndexCorruptError(RuntimeError):
    """The persisted index exists but cannot be read or parsed."""


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same dir, then os.replace (atomic on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_lock_state = threading.local()


@contextmanager
def index_lock(index_dir: str):
    """Exclusive, re-entrant (per thread) advisory lock on <index_dir>/.lock."""
    held = getattr(_lock_state, "held", None)
    if held is None:
        held = _lock_state.held = {}
    key = str(Path(index_dir).resolve())
    if held.get(key, 0) > 0:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(index_dir) / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        held[key] = 1
        try:
            yield
        finally:
            held[key] = 0
            fcntl.flock(f, fcntl.LOCK_UN)


def index_signature(path: Path) -> Optional[list]:
    """Cheap fingerprint of index.json; changes on every atomic replace."""
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino]


class VectorIndex(Protocol):
    def size(self) -> int: ...

    def add(self, docs: List[str]) -> None: ...


class InMemoryIndex:
    """Stub index persisted as JSON. Swap for Chroma/FAISS behind the same interface."""

    def __init__(self, index_dir: str):
        self._dir = index_dir
        self._path = Path(index_dir) / "index.json"
        self._docs: List[str] = self._load()

    def _load(self) -> List[str]:
        if not self._path.exists():
            return []
        try:
            docs = json.loads(self._path.read_text())
        except (ValueError, OSError) as e:
            raise IndexCorruptError(
                f"cannot read index at {self._path}: {e}; fix or remove it manually"
            ) from e
        if not isinstance(docs, list):
            raise IndexCorruptError(f"index at {self._path} is not a JSON list")
        return docs

    def size(self) -> int:
        return len(self._docs)

    def add(self, docs: List[str]) -> None:
        # Re-read under the lock so concurrent writers never drop each other's docs.
        with index_lock(self._dir):
            new = self._load() + list(docs)
            atomic_write_text(self._path, json.dumps(new))
            self._docs = new
