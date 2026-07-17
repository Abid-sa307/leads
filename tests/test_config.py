"""Unit tests for configuration management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Ensure project root is in sys.path
import sys
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Settings, get_settings, reset_settings


class TestSettings:
    """Tests for the Settings model and loading."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_settings()

    def test_default_settings(self):
        """Settings should load with valid defaults when no config file exists."""
        settings = Settings()
        assert settings.concurrency.worker_count == 10
        assert settings.concurrency.browser_pool_size == 5
        assert settings.timeouts.page_load_seconds == 30
        assert settings.retries.max_attempts == 3
        assert settings.crawler.headless is True
        assert settings.storage.db_path == "data/industries.db"

    def test_from_json(self, tmp_path):
        """Settings.from_json should override defaults with JSON values."""
        config = {
            "concurrency": {"worker_count": 25, "browser_pool_size": 8},
            "timeouts": {"page_load_seconds": 45},
            "storage": {"db_path": "custom/path.db"},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        settings = Settings.from_json(config_file)
        assert settings.concurrency.worker_count == 25
        assert settings.concurrency.browser_pool_size == 8
        assert settings.timeouts.page_load_seconds == 45
        assert settings.storage.db_path == "custom/path.db"

    def test_from_json_missing_file(self):
        """from_json with non-existent file should use defaults."""
        settings = Settings.from_json("nonexistent_config.json")
        assert settings.concurrency.worker_count == 10

    def test_singleton_get_settings(self):
        """get_settings should return the same instance on repeated calls."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_singleton_reset(self):
        """reset_settings should clear the singleton."""
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2

    def test_log_level_validator(self):
        """Invalid log level should raise ValueError."""
        from config.settings import LoggingSettings
        with pytest.raises(Exception):
            LoggingSettings(level="INVALID_LEVEL")

    def test_log_level_case_insensitive(self):
        """Log level should be normalized to uppercase."""
        from config.settings import LoggingSettings
        s = LoggingSettings(level="debug")
        assert s.level == "DEBUG"

    def test_concurrency_bounds(self):
        """Worker count should be clipped to valid range."""
        from config.settings import ConcurrencySettings
        with pytest.raises(Exception):
            ConcurrencySettings(worker_count=0)  # ge=1

    def test_resolve_path(self, tmp_path):
        """resolve_path should return an absolute Path."""
        settings = Settings()
        resolved = settings.resolve_path("data/industries.db")
        assert resolved.is_absolute()
