"""
Configuration management for Industry Contact Discovery System.

Merges config.json defaults with environment variable overrides.
Environment variables use the prefix SD_ (e.g., SD_CONCURRENCY__WORKER_COUNT=20).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Nested configuration models
# ---------------------------------------------------------------------------


class ConcurrencySettings(BaseSettings):
    """Worker and browser pool concurrency limits."""

    model_config = SettingsConfigDict(env_prefix="SD_CONCURRENCY__")

    browser_pool_size: int = Field(5, ge=1, le=50)
    worker_count: int = Field(10, ge=1, le=200)
    requests_per_second_per_domain: float = Field(1.0, ge=0.1, le=100.0)
    max_concurrent_domains: int = Field(20, ge=1, le=500)


class TimeoutSettings(BaseSettings):
    """Timeout values in seconds."""

    model_config = SettingsConfigDict(env_prefix="SD_TIMEOUTS__")

    page_load_seconds: int = Field(30, ge=5, le=120)
    request_seconds: int = Field(15, ge=3, le=60)
    dns_seconds: int = Field(5, ge=1, le=30)
    resolve_timeout_seconds: int = Field(20, ge=5, le=60)


class RetrySettings(BaseSettings):
    """Retry policy for failed requests."""

    model_config = SettingsConfigDict(env_prefix="SD_RETRIES__")

    max_attempts: int = Field(3, ge=1, le=10)
    backoff_factor: float = Field(2.0, ge=1.0, le=10.0)
    retry_on_status: list[int] = Field(default=[429, 500, 502, 503, 504])


class CrawlerSettings(BaseSettings):
    """Playwright crawler behaviour."""

    model_config = SettingsConfigDict(env_prefix="SD_CRAWLER__")

    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (compatible; IndustryDiscoveryBot/1.0; +https://example.com/bot)"
    )
    accept_language: str = "en-US,en;q=0.9"
    pages_to_visit: list[str] = Field(
        default=["/", "/contact", "/contact-us", "/about", "/about-us", "/careers", "/jobs", "/team"]
    )
    respect_robots_txt: bool = True
    ssl_permissive: bool = True
    max_pages_per_industry: int = Field(10, ge=1, le=50)


class ResolverSettings(BaseSettings):
    """Website resolution strategy."""

    model_config = SettingsConfigDict(env_prefix="SD_RESOLVER__")

    use_cache: bool = True
    search_engine: str = "duckduckgo"
    verify_before_crawl: bool = True
    fallback_patterns: list[str] = Field(
        default=[
            "site:{name} official website",
            "{name} {city} {state} official site",
        ],
        description="Search query templates for website resolution fallback.",
    )


class ExtractionSettings(BaseSettings):
    """Contact extraction preferences."""

    model_config = SettingsConfigDict(env_prefix="SD_EXTRACTION__")

    prefer_same_domain_emails: bool = True
    extract_exec_email: bool = True
    extract_hr_email: bool = True
    min_email_confidence: float = Field(0.7, ge=0.0, le=1.0)
    phone_default_region: str = "US"


class StorageSettings(BaseSettings):
    """Database and output paths."""

    model_config = SettingsConfigDict(env_prefix="SD_STORAGE__")

    db_path: str = "data/industries.db"
    output_dir: str = "data/output"
    backup_on_start: bool = True


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(env_prefix="SD_LOGGING__")

    level: str = "INFO"
    log_dir: str = "logs"
    max_bytes: int = 10_485_760  # 10 MB
    backup_count: int = 5
    console_level: str = "INFO"

    @field_validator("level", "console_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is valid."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"Invalid log level '{v}'. Must be one of {valid}")
        return upper


class DashboardSettings(BaseSettings):
    """Live terminal dashboard settings."""

    model_config = SettingsConfigDict(env_prefix="SD_DASHBOARD__")

    refresh_rate: float = Field(1.0, ge=0.1, le=10.0)
    show_active_workers: bool = True


class ReportSettings(BaseSettings):
    """Report generation settings."""

    model_config = SettingsConfigDict(env_prefix="SD_REPORTS__")

    auto_generate_on_complete: bool = True
    include_raw_html: bool = False


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    Root settings object.

    Priority (highest to lowest):
    1. Environment variables (SD_* prefix)
    2. config.json values
    3. Pydantic field defaults
    """

    model_config = SettingsConfigDict(
        env_prefix="SD_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    config_file: str = "config/config.json"

    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    timeouts: TimeoutSettings = Field(default_factory=TimeoutSettings)
    retries: RetrySettings = Field(default_factory=RetrySettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    resolver: ResolverSettings = Field(default_factory=ResolverSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    reports: ReportSettings = Field(default_factory=ReportSettings)

    @classmethod
    def from_json(cls, config_path: Optional[str | Path] = None) -> "Settings":
        """
        Load settings from a JSON config file, then allow environment
        variable overrides on top.

        Args:
            config_path: Path to config.json. Defaults to 'config/config.json'.

        Returns:
            Populated Settings instance.
        """
        path = Path(config_path or "config/config.json")
        json_data: dict = {}

        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                json_data = json.load(fh)

        # Build nested model instances from JSON, then let env vars override
        concurrency = ConcurrencySettings(**json_data.get("concurrency", {}))
        timeouts = TimeoutSettings(**json_data.get("timeouts", {}))
        retries = RetrySettings(**json_data.get("retries", {}))
        crawler = CrawlerSettings(**json_data.get("crawler", {}))
        resolver = ResolverSettings(**json_data.get("resolver", {}))
        extraction = ExtractionSettings(**json_data.get("extraction", {}))
        storage = StorageSettings(**json_data.get("storage", {}))
        logging_cfg = LoggingSettings(**json_data.get("logging", {}))
        dashboard = DashboardSettings(**json_data.get("dashboard", {}))
        reports = ReportSettings(**json_data.get("reports", {}))

        return cls(
            concurrency=concurrency,
            timeouts=timeouts,
            retries=retries,
            crawler=crawler,
            resolver=resolver,
            extraction=extraction,
            storage=storage,
            logging=logging_cfg,
            dashboard=dashboard,
            reports=reports,
        )

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a path relative to the project root."""
        return Path(relative_path).resolve()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_settings: Optional[Settings] = None


def get_settings(config_path: Optional[str | Path] = None) -> Settings:
    """
    Return the singleton Settings instance.

    Call with config_path on first use to initialise from a specific file.
    Subsequent calls ignore config_path and return the cached instance.

    Args:
        config_path: Optional path to config.json.

    Returns:
        Singleton Settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings.from_json(config_path)
    return _settings


def reset_settings() -> None:
    """Reset the singleton (useful for testing)."""
    global _settings
    _settings = None
