"""Call Recorder — configuration."""

import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger("call-recorder")

# Paths
BASE_DIR = Path.home() / "call-recorder"
DATA_DIR = BASE_DIR / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"
DB_PATH = DATA_DIR / "calls.db"
STATUS_PATH = DATA_DIR / "status.json"
LOG_PATH = BASE_DIR / "logs" / "call-recorder.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB per log file
LOG_BACKUP_COUNT = 3  # keep 3 rotated backups
AUDIO_CAPTURE_BIN = BASE_DIR / "bin" / "audio-capture"

# Detector
POLL_INTERVAL = 3  # seconds between checks
MIN_CALL_DURATION = 30  # ignore calls shorter than this (seconds)

# Apps to detect — process names and detection strategy
CALL_APPS = {
    "Zoom": {
        "process": "CptHost",
        "strategy": "process_only",  # CptHost only exists during active call
    },
    "Google Meet": {
        "process": ["Google Chrome Helper", "Arc Helper", "Chromium Helper"],
        "strategy": "browser_udp",
    },
    "Microsoft Teams": {
        "process": "Microsoft Teams",
        "strategy": "udp_connections",
        "min_udp": 2,
    },
    "Discord": {
        "process": "Discord",
        "strategy": "udp_connections",
        "min_udp": 2,
    },
    "Telegram": {
        "process": "Telegram",
        "strategy": "udp_connections",
        "min_udp": 2,
    },
    "FaceTime": {
        "process": "FaceTime",
        "strategy": "udp_connections",
        "min_udp": 2,
    },
}

# Transcription
MLX_WHISPER_BIN = Path.home() / ".local" / "bin" / "mlx_whisper"
WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"
WHISPER_LANGUAGE = "ru"
FFMPEG_BIN = "ffmpeg"

# Summarization
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_MODEL = "qwen3:14b"
OLLAMA_HEALTH_TIMEOUT = 5  # seconds for health check

# Notifications
NOTIFY_ENABLED = True


def check_ollama() -> bool:
    """Ping Ollama /api/tags to verify it's running and responsive.

    Returns True if Ollama is available, False otherwise.
    """
    url = f"{OLLAMA_BASE_URL}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_HEALTH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]
            log.info(
                f"Ollama health check OK: {len(models)} models available "
                f"({', '.join(model_names[:5])})"
            )
            return True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning(f"Ollama health check FAILED: {e}")
        return False
