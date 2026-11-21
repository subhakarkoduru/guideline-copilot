import math
from collections import Counter
from typing import Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings

MIN_HEALTH_TOKEN_LEN = 32
MIN_HEALTH_TOKEN_DISTINCT = 8
MIN_HEALTH_TOKEN_ENTROPY_BITS = 2.5  # empirical Shannon entropy per character
MAX_CHAR_FRACTION = 0.4  # no single character may make up more than this share
MAX_SEQUENTIAL_FRACTION = 0.5  # adjacent chars differing by exactly 1 (abc, 321)

_HINT = "generate one with: openssl rand -hex 32"


class SettingsError(ValueError):
    """Invalid configuration. The message never contains secret values."""


class Settings(BaseSettings):
    model_name: str = "claude-sonnet-5-5"
    index_dir: str = "./data"
    # "development" enables /docs, /redoc and /openapi.json. It does NOT affect /health.
    app_env: str = "production"
    # Held as SecretStr (repr/str are masked) and deliberately NOT validated by pydantic:
    # a pydantic ValidationError carries the raw value in .errors()["input"]. The token
    # is checked by validate_health_token() instead, which never includes the value.
    health_token: Optional[SecretStr] = None
    max_ingest_bytes: int = 10 * 1024 * 1024

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() == "development"

    def health_token_value(self) -> Optional[str]:
        return self.health_token.get_secret_value() if self.health_token else None


def _has_period(v: str) -> bool:
    """True if v is a shorter block repeated (possibly cut off), e.g. abcdabcdabcda."""
    return any(v[p:] == v[:-p] for p in range(1, len(v) // 2 + 1))


def health_token_problem(v: str) -> Optional[str]:
    """Return a reason the token is unacceptable, or None. The reason never includes v."""
    if not (v.isascii() and v.isprintable()) or any(c.isspace() for c in v):
        return (
            "must be printable ASCII with no whitespace or control characters "
            "(it could never match an Authorization header)"
        )
    if len(v) < MIN_HEALTH_TOKEN_LEN:
        return f"must be at least {MIN_HEALTH_TOKEN_LEN} characters"
    counts = Counter(v)
    n = len(v)
    entropy = -sum(c / n * math.log2(c / n) for c in counts.values())
    sequential = sum(1 for a, b in zip(v, v[1:]) if abs(ord(a) - ord(b)) == 1)
    if (
        len(counts) < MIN_HEALTH_TOKEN_DISTINCT
        or entropy < MIN_HEALTH_TOKEN_ENTROPY_BITS
        or max(counts.values()) > n * MAX_CHAR_FRACTION
        or _has_period(v)
        or sequential > (n - 1) * MAX_SEQUENTIAL_FRACTION
    ):
        return "is too weak (repetitive, patterned or low-entropy)"
    return None


def validate_settings(settings: Settings) -> Settings:
    token = settings.health_token_value()
    if token == "":
        settings.health_token = None
    elif token is not None:
        problem = health_token_problem(token)
        if problem:
            raise SettingsError(f"invalid HEALTH_TOKEN: it {problem}; {_HINT}")
    return settings


def get_settings() -> Settings:
    """Read and validate env. Raises SettingsError (secret-free) or pydantic ValidationError
    for non-secret fields."""
    return validate_settings(Settings())
