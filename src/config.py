"""Call Recorder — configuration."""

import os
from pathlib import Path

# Paths
BASE_DIR = Path.home() / "call-recorder"
DATA_DIR = BASE_DIR / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"
DB_PATH = DATA_DIR / "calls.db"
STATUS_PATH = DATA_DIR / "status.json"
LOG_PATH = BASE_DIR / "logs" / "call-recorder.log"
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
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:14b"

# Notifications
NOTIFY_ENABLED = True
