from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DEFAULT_DATABASE_URL = f"sqlite:///{(ROOT / 'social_intelligence.db').as_posix()}"


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise ValueError("Value must be non-negative")
    return parsed


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Value must be positive")
    return parsed


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    cookie_secure: bool = field(
        default_factory=lambda: parse_bool(os.getenv("COOKIE_SECURE", "false"))
    )
    seed_demo_data: bool = field(
        default_factory=lambda: parse_bool(os.getenv("SEED_DEMO_DATA", "true"))
    )
    auto_refresh_hours: float = field(
        default_factory=lambda: parse_non_negative_float(os.getenv("AUTO_REFRESH_HOURS", "0"))
    )
    run_inline_worker: bool = field(
        default_factory=lambda: parse_bool(os.getenv("RUN_INLINE_WORKER", "true"))
    )
    allow_registration: bool = field(
        default_factory=lambda: parse_bool(os.getenv("ALLOW_REGISTRATION", "true"))
    )
    public_origin: str = field(
        default_factory=lambda: os.getenv("PUBLIC_ORIGIN", "").rstrip("/")
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()
        )
    )
    public_preview_enabled: bool = field(
        default_factory=lambda: parse_bool(os.getenv("PUBLIC_PREVIEW_ENABLED", "false"))
    )
    public_preview_daily_limit: int = field(
        default_factory=lambda: parse_positive_int(os.getenv("PUBLIC_PREVIEW_DAILY_LIMIT", "2"))
    )
    public_preview_max_channels: int = field(
        default_factory=lambda: parse_positive_int(os.getenv("PUBLIC_PREVIEW_MAX_CHANNELS", "100"))
    )
    youtube_daily_quota: int = field(
        default_factory=lambda: parse_positive_int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000"))
    )
    job_timeout_hours: float = field(
        default_factory=lambda: parse_non_negative_float(os.getenv("JOB_TIMEOUT_HOURS", "6")) or 6.0
    )
    semantic_engine: str = field(
        default_factory=lambda: os.getenv("SEMANTIC_ENGINE", "tfidf")
    )
    semantic_embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "SEMANTIC_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    semantic_label_llm_url: str = field(
        default_factory=lambda: os.getenv("SEMANTIC_LABEL_LLM_URL", "")
    )
    semantic_label_llm_api_key: str = field(
        default_factory=lambda: os.getenv("SEMANTIC_LABEL_LLM_API_KEY", "")
    )
    semantic_label_llm_model: str = field(
        default_factory=lambda: os.getenv("SEMANTIC_LABEL_LLM_MODEL", "")
    )
    semantic_label_llm_timeout: float = field(
        default_factory=lambda: parse_non_negative_float(
            os.getenv("SEMANTIC_LABEL_LLM_TIMEOUT", "10")
        ) or 10.0
    )


settings = Settings()
