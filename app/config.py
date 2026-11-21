from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

MIN_HEALTH_TOKEN_LEN = 32


class Settings(BaseSettings):
    model_name: str = "claude-sonnet-5-5"
    index_dir: str = "./data"
    # "development" enables /docs, /redoc and /openapi.json. It does NOT affect /health.
    app_env: str = "production"
    # If set (>= 32 chars), GET /health returns details only with
    # "Authorization: Bearer <token>". If unset, /health is always {"status": "ok"}.
    health_token: Optional[str] = None
    max_ingest_bytes: int = 10 * 1024 * 1024

    @field_validator("health_token")
    @classmethod
    def _check_health_token(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if len(v) < MIN_HEALTH_TOKEN_LEN:
            raise ValueError(
                f"HEALTH_TOKEN must be at least {MIN_HEALTH_TOKEN_LEN} characters "
                "(generate one with: openssl rand -hex 32)"
            )
        return v

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() == "development"


def get_settings() -> Settings:
    # Read env on each call so overrides (and tests) take effect.
    return Settings()
