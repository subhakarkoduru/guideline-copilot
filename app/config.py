from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_name: str = "claude-sonnet-5-5"
    index_dir: str = "./data"
    # "development" enables /docs and (without a token) detailed /health.
    app_env: str = "production"
    # If set, GET /health returns details only with "Authorization: Bearer <token>".
    health_token: Optional[str] = None
    max_ingest_bytes: int = 10 * 1024 * 1024

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() == "development"


def get_settings() -> Settings:
    # Read env on each call so overrides (and tests) take effect.
    return Settings()
