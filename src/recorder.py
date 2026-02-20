"""Call Recorder — manages the Swift audio-capture subprocess."""

import logging
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import AUDIO_CAPTURE_BIN, RECORDINGS_DIR

log = logging.getLogger("call-recorder")


class AudioRecorder:
    """Manages the Swift audio-capture binary lifecycle."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.session_dir: Path | None = None
        self.started_at: datetime | None = None
        self.app_name: str | None = None

    @property
    def is_recording(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, app_name: str) -> str:
        """Start recording. Returns session_id."""
        if self.is_recording:
            raise RuntimeError("Already recording")

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = RECORDINGS_DIR / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.app_name = app_name
        self.started_at = datetime.now()

        log.info(f"Starting recording: session={self.session_id}, app={app_name}")

        self.process = subprocess.Popen(
            [str(AUDIO_CAPTURE_BIN), str(self.session_dir), self.session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return self.session_id

    def stop(self) -> dict | None:
        """Stop recording. Returns session metadata or None if not recording."""
        if not self.is_recording:
            return None

        log.info(f"Stopping recording: session={self.session_id}")

        # Send SIGTERM for graceful shutdown
        self.process.send_signal(signal.SIGTERM)

        # Wait up to 10 seconds for clean exit
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("audio-capture did not exit in 10s, killing")
            self.process.kill()
            self.process.wait()

        ended_at = datetime.now()
        duration = (ended_at - self.started_at).total_seconds()

        result = {
            "session_id": self.session_id,
            "app_name": self.app_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": duration,
            "session_dir": str(self.session_dir),
            "system_wav": str(self.session_dir / "system.wav"),
            "mic_wav": str(self.session_dir / "mic.wav"),
        }

        # Cleanup state
        self.process = None
        self.session_id = None
        self.session_dir = None
        self.started_at = None
        self.app_name = None

        return result

    def abort(self):
        """Force-kill recording without returning results."""
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.process = None
        self.session_id = None
        self.session_dir = None
        self.started_at = None
        self.app_name = None
