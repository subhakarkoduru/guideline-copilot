import json
import os
import tempfile
from pathlib import Path
from typing import List, Protocol


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


class VectorIndex(Protocol):
    def size(self) -> int: ...

    def add(self, docs: List[str]) -> None: ...


class InMemoryIndex:
    """Stub index persisted as JSON. Swap for Chroma/FAISS behind the same interface."""

    def __init__(self, index_dir: str):
        self._path = Path(index_dir) / "index.json"
        self._docs: List[str] = []
        if self._path.exists():
            try:
                docs = json.loads(self._path.read_text())
            except (ValueError, OSError) as e:
                raise IndexCorruptError(
                    f"cannot read index at {self._path}: {e}; fix or remove it manually"
                ) from e
            if not isinstance(docs, list):
                raise IndexCorruptError(f"index at {self._path} is not a JSON list")
            self._docs = docs

    def size(self) -> int:
        return len(self._docs)

    def add(self, docs: List[str]) -> None:
        new = self._docs + list(docs)
        atomic_write_text(self._path, json.dumps(new))
        self._docs = new
