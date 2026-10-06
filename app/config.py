"""Typed application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def parse_integer_list(value: Any) -> tuple[int, ...]:
    """Parse empty, comma-separated, or already-decoded integer lists.

    Empty environment values must become ``()``. Values are never treated as JSON
    objects, so ``ADMIN_IDS=`` does not raise a JSON decode error.
    """
    if value is None or value == "" or value == b"":
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(int(item) for item in value if str(item).strip() != "")
    text = str(value).strip()
    if not text or text in {"[]", "()"}:
        return ()
    return tuple(int(item.strip()) for item in text.split(",") if item.strip())


def parse_secret_list(value: Any) -> tuple[str, ...]:
    """Parse comma-separated secrets or sequences of SecretStr/str."""
    if value is None or value == "" or value == b"":
        return ()
    if isinstance(value, (list, tuple, set)):
        secrets: list[str] = []
        for item in value:
            raw = item.get_secret_value() if isinstance(item, SecretStr) else str(item)
            stripped = raw.strip()
            if stripped:
                secrets.append(stripped)
        return tuple(secrets)
    text = str(value).strip()
    if not text or text in {"[]", "()"}:
        return ()
    return tuple(item.strip() for item in text.split(",") if item.strip())


class Settings(BaseSettings):
    """Runtime settings. Secrets must only be supplied through environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    bot_token: SecretStr
    admin_ids: Annotated[tuple[int, ...], NoDecode] = ()
    main_channel_id: int | None = None
    reels_channel_id: int | None = None
    required_channel_ids: Annotated[tuple[int, ...], NoDecode] = ()
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    aimlapi_keys: Annotated[tuple[SecretStr, ...], NoDecode] = ()
    aimlapi_key_1: SecretStr | None = None
    aimlapi_key_2: SecretStr | None = None
    aimlapi_key_3: SecretStr | None = None
    aimlapi_key_4: SecretStr | None = None
    aimlapi_base_url: str = "https://api.aimlapi.com/v1"
    aimlapi_model: str = "glm-5.2"
    aimlapi_fallback_model: str | None = None
    aimlapi_timeout: float = 90.0
    aimlapi_key_cooldown_seconds: float = 120.0
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    video_work_dir: Path = Field(default=Path("/app/data/work"))
    whisper_model: str = "base"
    reel_job_max_attempts: int = Field(default=3, ge=1)
    worker_concurrency: int = Field(default=1, ge=1, le=4)
    worker_retry_backoff_seconds: float = Field(default=5.0, ge=1)
    worker_retry_backoff_max_seconds: float = Field(default=300.0, ge=1)
    reel_max_per_movie: int = 4
    reel_min_seconds: int = 15
    reel_max_seconds: int = 30
    reel_face_tracking: bool = False
    face_detection_model: str = "haar"
    reel_moment_strategy: str = "auto"
    reel_transcript_max_duration: int = 1200
    # Window-based moment selection (Clip Generator / Adversitas style)
    reel_window_seconds: int = Field(default=300, ge=30)
    reel_window_min_duration: int = Field(default=15, ge=1)
    reel_window_max_duration: int = Field(default=30, ge=1)
    reel_window_max_retries: int = Field(default=3, ge=1)
    reel_use_windows_threshold: int = Field(default=300, ge=0)
    environment: str = "development"
    log_level: str = "INFO"
    health_port: int | None = None
    port: int | None = None
    premium_card_number: SecretStr | None = None
    premium_card_name: str | None = None
    premium_weekly_price: int = 10000
    premium_monthly_price: int = 15000
    admin_contact_username: str | None = None
    card_number: SecretStr | None = None
    card_owner: str | None = None
    premium_week_price: int = 10000
    premium_month_price: int = 15000
    subscriber_100_price: int = 15000
    subscriber_500_price: int = 70000
    subscriber_1000_price: int = 130000
    admin_username: str | None = None
    # Advertising system (§12)
    reklama_kanal_id: int | None = None
    reklama_week_price: int = 30000
    reklama_month_price: int = 100000
    reklama_week_times_per_day: int = 3
    reklama_month_times_per_day: int = 5
    reklama_post_hours_3: Annotated[tuple[int, ...], NoDecode] = (9, 15, 21)
    reklama_post_hours_5: Annotated[tuple[int, ...], NoDecode] = (9, 12, 15, 18, 21)
    # Mandatory-channel subscriber-growth packages (§13)
    mandatory_100_price: int = 15000
    mandatory_500_price: int = 70000
    mandatory_1000_price: int = 100000


    @field_validator(
        "admin_ids",
        "required_channel_ids",
        "reklama_post_hours_3",
        "reklama_post_hours_5",
        mode="before",
    )
    @classmethod
    def parse_ids(cls, value: Any) -> tuple[int, ...]:
        return parse_integer_list(value)


    @field_validator("aimlapi_keys", mode="before")
    @classmethod
    def parse_keys(cls, value: Any) -> tuple[str, ...]:
        return parse_secret_list(value)

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any) -> str:
        """Keep the operator-supplied URL; only add the asyncpg driver if missing."""
        text = str(value).strip()
        if text.startswith("postgresql://") and "+asyncpg" not in text:
            return "postgresql+asyncpg://" + text[len("postgresql://") :]
        if text.startswith("postgres://") and "+asyncpg" not in text:
            return "postgresql+asyncpg://" + text[len("postgres://") :]
        return text

    @model_validator(mode="after")
    def merge_numbered_aimlapi_keys(self) -> Settings:
        numbered = []
        for item in (self.aimlapi_key_1, self.aimlapi_key_2, self.aimlapi_key_3, self.aimlapi_key_4):
            if item is None:
                continue
            secret = item.get_secret_value().strip()
            if secret:
                numbered.append(SecretStr(secret))
        if numbered:
            existing = [key.get_secret_value() for key in self.aimlapi_keys]
            merged: list[SecretStr] = list(self.aimlapi_keys)
            for extra in numbered:
                if extra.get_secret_value() not in existing:
                    merged.append(extra)
                    existing.append(extra.get_secret_value())
            self.aimlapi_keys = tuple(merged)
        return self

    @model_validator(mode="after")
    def merge_payment_and_contact_settings(self) -> Settings:
        """Support the current Railway variable names and older project names."""
        if self.card_number is None:
            self.card_number = self.premium_card_number
        if self.premium_card_number is None:
            self.premium_card_number = self.card_number
        if not self.card_owner:
            self.card_owner = self.premium_card_name
        if not self.premium_card_name:
            self.premium_card_name = self.card_owner
        if self.premium_week_price == 10000 and self.premium_weekly_price != 10000:
            self.premium_week_price = self.premium_weekly_price
        if self.premium_weekly_price == 10000 and self.premium_week_price != 10000:
            self.premium_weekly_price = self.premium_week_price
        if self.premium_month_price == 15000 and self.premium_monthly_price != 15000:
            self.premium_month_price = self.premium_monthly_price
        if self.premium_monthly_price == 15000 and self.premium_month_price != 15000:
            self.premium_monthly_price = self.premium_month_price
        if not self.admin_username:
            self.admin_username = self.admin_contact_username
        if not self.admin_contact_username:
            self.admin_contact_username = self.admin_username
        return self

    @property
    def aimlapi_key_values(self) -> tuple[str, ...]:
        return tuple(key.get_secret_value() for key in self.aimlapi_keys)

    @property
    def listen_port(self) -> int | None:
        return self.health_port or self.port


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
