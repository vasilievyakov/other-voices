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
HEARTBEAT_INTERVAL = 60  # refresh status.json at least this often (seconds)

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

# Diarization — per-speaker labels WITHIN system.wav (remote participants).
# Channel-level ME/OTHER stays the guaranteed baseline; this refines the system
# channel into SPEAKER_1..N using sherpa-onnx speaker embeddings + clustering.
# Fully local/offline, no gated model downloads (no auth token required).
DIARIZATION_ENABLED = True
DIARIZATION_MODELS_DIR = Path.home() / ".cache" / "other-voices" / "models"
DIARIZATION_MODEL_FILE = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
DIARIZATION_MODEL_PATH = DIARIZATION_MODELS_DIR / DIARIZATION_MODEL_FILE
# Public GitHub release asset (no HuggingFace auth / no gating). Used by
# diarizer.download_model() for reproducible setup.
DIARIZATION_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
)
DIARIZATION_NUM_THREADS = 2
# Segments shorter than this (seconds) are not embedded directly (embeddings are
# unreliable on very short audio); they inherit the speaker of the temporally
# nearest embedded segment.
DIARIZATION_MIN_EMBED_DURATION = 0.5
# Cosine distance cutoff for agglomerative clustering when the speaker count is
# unknown (DIARIZATION_NUM_SPEAKERS = 0). Lower = more speakers (splits more),
# higher = fewer speakers (merges more).
DIARIZATION_DISTANCE_THRESHOLD = 0.55
# Upper bound on distinct remote speakers when auto-detecting.
DIARIZATION_MAX_SPEAKERS = 8
# 0 = auto-detect count via DIARIZATION_DISTANCE_THRESHOLD; >0 forces exactly N.
DIARIZATION_NUM_SPEAKERS = 0

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
