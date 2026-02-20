"""Tests for src.recorder — mock subprocess.Popen and RECORDINGS_DIR."""

import signal
from unittest.mock import patch, MagicMock

import pytest

from src.recorder import AudioRecorder


@pytest.fixture
def recorder(tmp_path):
    """AudioRecorder with RECORDINGS_DIR pointing to tmp_path."""
    with patch("src.recorder.RECORDINGS_DIR", tmp_path):
        yield AudioRecorder()


@pytest.fixture
def mock_popen():
    """Patch subprocess.Popen to return a mock process."""
    with patch("src.recorder.subprocess.Popen") as mock:
        proc = MagicMock()
        proc.poll.return_value = None  # process is "running"
        mock.return_value = proc
        yield mock, proc


class TestAudioRecorder:
    def test_initial_state(self, recorder):
        """Fresh recorder: is_recording=False, all attrs None."""
        assert recorder.is_recording is False
        assert recorder.session_id is None
        assert recorder.session_dir is None
        assert recorder.started_at is None
        assert recorder.app_name is None

    def test_start_creates_session(self, recorder, mock_popen):
        """start() sets session_id, session_dir, app_name."""
        _, proc = mock_popen
        session_id = recorder.start("Zoom")

        assert session_id is not None
        assert recorder.session_id == session_id
        assert recorder.app_name == "Zoom"
        assert recorder.session_dir is not None
        assert recorder.session_dir.exists()
        assert recorder.is_recording is True

    def test_start_raises_if_recording(self, recorder, mock_popen):
        """Second start() raises RuntimeError."""
        recorder.start("Zoom")
        with pytest.raises(RuntimeError, match="Already recording"):
            recorder.start("Google Meet")

    def test_stop_returns_metadata(self, recorder, mock_popen):
        """stop() returns dict with all expected keys."""
        _, proc = mock_popen
        proc.wait.return_value = 0

        recorder.start("Zoom")
        result = recorder.stop()

        assert result is not None
        assert result["app_name"] == "Zoom"
        assert "session_id" in result
        assert "started_at" in result
        assert "ended_at" in result
        assert "duration_seconds" in result
        assert "session_dir" in result
        assert "system_wav" in result
        assert "mic_wav" in result
        # State is reset
        assert recorder.is_recording is False
        assert recorder.session_id is None

    def test_stop_when_not_recording(self, recorder):
        """stop() when not recording returns None."""
        assert recorder.stop() is None

    def test_abort_kills(self, recorder, mock_popen):
        """abort() kills process and resets state."""
        _, proc = mock_popen

        recorder.start("Zoom")
        assert recorder.is_recording is True

        recorder.abort()

        proc.kill.assert_called_once()
        proc.wait.assert_called_once()
        assert recorder.process is None
        assert recorder.session_id is None
