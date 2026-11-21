from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.index import InMemoryIndex
from app.ingest import read_last_ingest

app = FastAPI(title="Guideline Copilot")


class Health(BaseModel):
    status: str
    model: str
    index_size: int
    last_ingest_at: Optional[str]


@app.get("/health", response_model=Health)
def health() -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        model=settings.model_name,
        index_size=InMemoryIndex(settings.index_dir).size(),
        last_ingest_at=read_last_ingest(settings.index_dir),
    )
