"""Call Recorder — user settings reader.

Reads settings.json written by the SwiftUI app (SettingsSync).
Falls back to config.py defaults if settings.json is missing or invalid.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .config import DATA_DIR, MIN_CALL_DURATION, OLLAMA_URL, OLLAMA_MODEL, CALL_APPS

log = logging.getLogger("call-recorder")

SETTINGS_PATH = DATA_DIR / "settings.json"

# Cache: (mtime, settings_dict)
_cache: tuple[float, dict[str, Any]] | None = None


def load_settings() -> dict[str, Any]:
    """Load settings.json with mtime-based caching.

    Returns a dict with all settings, falling back to defaults
    for any missing keys.
    """
    global _cache

    defaults = {
        "auto_record_calls": True,
        "enabled_apps": {name: True for name in CALL_APPS},
        "min_call_duration_seconds": MIN_CALL_DURATION,
        "transcribe_calls": True,
        "generate_summary": True,
        "extract_commitments": True,
        "default_template": "default",
        "ollama_model": OLLAMA_MODEL,
        "ollama_url": OLLAMA_URL,
        "audio_retention": "forever",
    }

    if not SETTINGS_PATH.exists():
        return defaults

    try:
        mtime = SETTINGS_PATH.stat().st_mtime
    except OSError:
        return defaults

    # Return cached if file unchanged
    if _cache is not None and _cache[0] == mtime:
        return _cache[1]

    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        # Merge with defaults so missing keys get filled
        merged = {**defaults, **raw}
        _cache = (mtime, merged)
        return merged
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read settings.json: {e}")
        return defaults


def is_app_enabled(app_name: str) -> bool:
    """Check if a specific app is enabled for recording."""
    settings = load_settings()
    if not settings.get("auto_record_calls", True):
        return False
    enabled_apps = settings.get("enabled_apps", {})
    return enabled_apps.get(app_name, True)


def get_min_call_duration() -> int:
    """Get minimum call duration in seconds."""
    return load_settings().get("min_call_duration_seconds", MIN_CALL_DURATION)


def should_transcribe() -> bool:
    """Check if transcription is enabled."""
    return load_settings().get("transcribe_calls", True)


def should_summarize() -> bool:
    """Check if AI summary generation is enabled."""
    return load_settings().get("generate_summary", True)


def should_extract_commitments() -> bool:
    """Check if commitment extraction is enabled."""
    return load_settings().get("extract_commitments", True)


def get_default_template() -> str:
    """Get the default template name."""
    return load_settings().get("default_template", "default")


def get_ollama_model() -> str:
    """Get the configured Ollama model name."""
    return load_settings().get("ollama_model", OLLAMA_MODEL)


def get_ollama_url() -> str:
    """Get the configured Ollama base URL."""
    base = load_settings().get("ollama_url", "http://localhost:11434")
    # Ensure it ends with the API endpoint path
    if not base.endswith("/api/generate"):
        return base.rstrip("/") + "/api/generate"
    return base


def get_audio_retention_days() -> int | None:
    """Get audio retention period in days, or None for forever."""
    retention = load_settings().get("audio_retention", "forever")
    retention_map = {
        "forever": None,
        "30_days": 30,
        "90_days": 90,
        "1_year": 365,
    }
    return retention_map.get(retention)
