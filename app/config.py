from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_name: str = "claude-sonnet-5-5"
    index_dir: str = "./data"


def get_settings() -> Settings:
    # Read env on each call so overrides (and tests) take effect.
    return Settings()
