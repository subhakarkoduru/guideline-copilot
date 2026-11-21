import secrets
from typing import Optional

from fastapi import FastAPI, Header

from app.config import get_settings
from app.ingest import read_index_size, read_last_ingest


def create_app() -> FastAPI:
    # Interactive docs / schema only in development.
    dev = get_settings().is_dev
    app = FastAPI(
        title="Guideline Copilot",
        docs_url="/docs" if dev else None,
        redoc_url="/redoc" if dev else None,
        openapi_url="/openapi.json" if dev else None,
    )

    @app.get("/health")
    def health(authorization: Optional[str] = Header(default=None)) -> dict:
        settings = get_settings()
        # No token configured => always minimal, regardless of APP_ENV.
        detailed = False
        if settings.health_token:
            # Scheme is case-insensitive (RFC 7235); the token compare is constant-time.
            scheme, _, supplied = (authorization or "").partition(" ")
            detailed = scheme.lower() == "bearer" and secrets.compare_digest(
                supplied.encode(), settings.health_token.encode()
            )
        if not detailed:
            return {"status": "ok"}
        # Normally reads only the small meta.json; see read_index_size.
        return {
            "status": "ok",
            "model": settings.model_name,
            "index_size": read_index_size(settings.index_dir),
            "last_ingest_at": read_last_ingest(settings.index_dir),
        }

    return app


app = create_app()
