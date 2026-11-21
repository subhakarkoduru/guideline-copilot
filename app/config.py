from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_HEALTH_TOKEN_LEN = 32
MIN_HEALTH_TOKEN_DISTINCT = 8


class Settings(BaseSettings):
    # Never echo the offending input (e.g. a too-short secret) in validation errors/logs.
    model_config = SettingsConfigDict(hide_input_in_errors=True)

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
        if v != v.strip():
            raise ValueError(
                "HEALTH_TOKEN must not be blank or have leading/trailing whitespace "
                "(it could never match an Authorization header)"
            )
        if len(v) < MIN_HEALTH_TOKEN_LEN:
            raise ValueError(
                f"HEALTH_TOKEN must be at least {MIN_HEALTH_TOKEN_LEN} characters "
                "(generate one with: openssl rand -hex 32)"
            )
        if len(set(v)) < MIN_HEALTH_TOKEN_DISTINCT:
            raise ValueError(
                f"HEALTH_TOKEN is too repetitive (needs at least "
                f"{MIN_HEALTH_TOKEN_DISTINCT} distinct characters); "
                "generate one with: openssl rand -hex 32"
            )
        return v

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() == "development"


def get_settings() -> Settings:
    # Read env on each call so overrides (and tests) take effect.
    return Settings()
