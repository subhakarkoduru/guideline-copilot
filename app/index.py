import json
from pathlib import Path
from typing import List, Protocol


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
                self._docs = list(json.loads(self._path.read_text()))
            except (ValueError, OSError):
                self._docs = []

    def size(self) -> int:
        return len(self._docs)

    def add(self, docs: List[str]) -> None:
        self._docs.extend(docs)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._docs))
