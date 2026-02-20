"""Tests for src.config — verify paths, constants, and types."""

from pathlib import Path

from src.config import (
    BASE_DIR,
    DATA_DIR,
    RECORDINGS_DIR,
    DB_PATH,
    STATUS_PATH,
    LOG_PATH,
    AUDIO_CAPTURE_BIN,
    POLL_INTERVAL,
    MIN_CALL_DURATION,
    CALL_APPS,
    MLX_WHISPER_BIN,
    WHISPER_MODEL,
    WHISPER_LANGUAGE,
    FFMPEG_BIN,
    OLLAMA_URL,
    OLLAMA_MODEL,
    NOTIFY_ENABLED,
)


class TestConfigPaths:
    def test_base_dir_is_path(self):
        """All path constants are pathlib.Path instances."""
        assert isinstance(BASE_DIR, Path)
        assert isinstance(DATA_DIR, Path)
        assert isinstance(RECORDINGS_DIR, Path)
        assert isinstance(DB_PATH, Path)
        assert isinstance(STATUS_PATH, Path)
        assert isinstance(LOG_PATH, Path)
        assert isinstance(AUDIO_CAPTURE_BIN, Path)

    def test_directory_hierarchy(self):
        """DATA_DIR and RECORDINGS_DIR are children of BASE_DIR."""
        assert str(DATA_DIR).startswith(str(BASE_DIR))
        assert str(RECORDINGS_DIR).startswith(str(DATA_DIR))
        assert str(DB_PATH).startswith(str(DATA_DIR))
        assert str(STATUS_PATH).startswith(str(DATA_DIR))

    def test_db_path_extension(self):
        """DB_PATH has .db extension."""
        assert DB_PATH.suffix == ".db"

    def test_status_path_extension(self):
        """STATUS_PATH has .json extension."""
        assert STATUS_PATH.suffix == ".json"


class TestConfigConstants:
    def test_poll_interval_positive(self):
        """POLL_INTERVAL is a positive number."""
        assert isinstance(POLL_INTERVAL, (int, float))
        assert POLL_INTERVAL > 0

    def test_min_call_duration_positive(self):
        """MIN_CALL_DURATION is a positive number."""
        assert isinstance(MIN_CALL_DURATION, (int, float))
        assert MIN_CALL_DURATION > 0

    def test_call_apps_is_dict(self):
        """CALL_APPS is a dict with expected apps."""
        assert isinstance(CALL_APPS, dict)
        assert "Zoom" in CALL_APPS
        assert "Google Meet" in CALL_APPS
        assert "Microsoft Teams" in CALL_APPS

    def test_call_apps_structure(self):
        """Each CALL_APPS entry has 'process' and 'strategy' keys."""
        for app_name, config in CALL_APPS.items():
            assert "process" in config, f"{app_name} missing 'process'"
            assert "strategy" in config, f"{app_name} missing 'strategy'"

    def test_ollama_url_is_http(self):
        """OLLAMA_URL starts with http."""
        assert OLLAMA_URL.startswith("http")

    def test_whisper_model_not_empty(self):
        """WHISPER_MODEL and WHISPER_LANGUAGE are non-empty strings."""
        assert isinstance(WHISPER_MODEL, str) and len(WHISPER_MODEL) > 0
        assert isinstance(WHISPER_LANGUAGE, str) and len(WHISPER_LANGUAGE) > 0

    def test_notify_enabled_is_bool(self):
        """NOTIFY_ENABLED is a boolean."""
        assert isinstance(NOTIFY_ENABLED, bool)
