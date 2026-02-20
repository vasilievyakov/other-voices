"""Tests for src.recorder — mock subprocess.Popen and RECORDINGS_DIR.

Enterprise coverage: lifecycle, errors, timeout handling, security.
"""

import signal
import subprocess
from datetime import datetime
from unittest.mock import patch, MagicMock, PropertyMock

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


# =============================================================================
# Recorder Lifecycle (9 tests)
# =============================================================================


class TestRecorderLifecycle:
    def test_initial_state(self, recorder):
        """Fresh recorder: is_recording=False, all attrs None."""
        assert recorder.is_recording is False
        assert recorder.session_id is None
        assert recorder.session_dir is None
        assert recorder.started_at is None
        assert recorder.app_name is None
        assert recorder.process is None

    def test_start_creates_session(self, recorder, mock_popen):
        """start() sets session_id, session_dir, app_name, is_recording."""
        _, proc = mock_popen
        session_id = recorder.start("Zoom")

        assert session_id is not None
        assert recorder.session_id == session_id
        assert recorder.app_name == "Zoom"
        assert recorder.session_dir is not None
        assert recorder.session_dir.exists()
        assert recorder.is_recording is True
        assert recorder.started_at is not None

    def test_start_session_id_format(self, recorder, mock_popen):
        """session_id matches YYYYMMDD_HHMMSS format."""
        session_id = recorder.start("Zoom")
        assert len(session_id) == 15  # "20250220_120000"
        assert session_id[8] == "_"
        # Should be parseable as datetime
        datetime.strptime(session_id, "%Y%m%d_%H%M%S")

    def test_start_creates_directory(self, recorder, mock_popen):
        """start() creates session_dir on disk."""
        recorder.start("Zoom")
        assert recorder.session_dir.is_dir()

    def test_start_calls_popen(self, recorder, mock_popen):
        """start() calls subprocess.Popen with correct arguments."""
        mock_cls, _ = mock_popen
        recorder.start("Zoom")
        mock_cls.assert_called_once()
        args = mock_cls.call_args
        cmd = args[0][0]
        assert len(cmd) == 3  # binary, session_dir, session_id

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
        assert isinstance(result["duration_seconds"], float)

    def test_stop_resets_state(self, recorder, mock_popen):
        """stop() resets all state to initial."""
        _, proc = mock_popen
        proc.wait.return_value = 0

        recorder.start("Zoom")
        recorder.stop()

        assert recorder.is_recording is False
        assert recorder.session_id is None
        assert recorder.session_dir is None
        assert recorder.started_at is None
        assert recorder.app_name is None
        assert recorder.process is None

    def test_stop_sends_sigterm(self, recorder, mock_popen):
        """stop() sends SIGTERM for graceful shutdown."""
        _, proc = mock_popen
        proc.wait.return_value = 0

        recorder.start("Zoom")
        recorder.stop()

        proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_abort_kills_and_resets(self, recorder, mock_popen):
        """abort() kills process and resets state."""
        _, proc = mock_popen

        recorder.start("Zoom")
        assert recorder.is_recording is True

        recorder.abort()

        proc.kill.assert_called_once()
        proc.wait.assert_called_once()
        assert recorder.process is None
        assert recorder.session_id is None


# =============================================================================
# Recorder Errors (5 tests)
# =============================================================================


class TestRecorderErrors:
    def test_start_raises_if_recording(self, recorder, mock_popen):
        """Second start() raises RuntimeError."""
        recorder.start("Zoom")
        with pytest.raises(RuntimeError, match="Already recording"):
            recorder.start("Google Meet")

    def test_stop_when_not_recording(self, recorder):
        """stop() when not recording returns None."""
        assert recorder.stop() is None

    def test_stop_timeout_falls_back_to_kill(self, recorder, mock_popen):
        """If process doesn't exit in 10s, kill() is called."""
        _, proc = mock_popen
        proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 10), None]

        recorder.start("Zoom")
        result = recorder.stop()

        proc.kill.assert_called_once()
        assert result is not None

    def test_abort_when_not_recording(self, recorder):
        """abort() when not recording does nothing, no crash."""
        recorder.abort()  # should not raise

    def test_abort_when_process_already_exited(self, recorder, mock_popen):
        """abort() when process already exited (poll() != None) does nothing."""
        _, proc = mock_popen
        recorder.start("Zoom")
        proc.poll.return_value = 0  # process has exited
        recorder.abort()
        proc.kill.assert_not_called()


# =============================================================================
# Recorder Security (3 tests)
# =============================================================================


class TestRecorderSecurity:
    def test_session_dir_under_recordings(self, recorder, mock_popen, tmp_path):
        """session_dir is created inside RECORDINGS_DIR, not elsewhere."""
        recorder.start("Zoom")
        assert str(recorder.session_dir).startswith(str(tmp_path))

    def test_wav_paths_in_session_dir(self, recorder, mock_popen):
        """system_wav and mic_wav paths are inside session_dir."""
        _, proc = mock_popen
        proc.wait.return_value = 0
        recorder.start("Zoom")
        result = recorder.stop()
        assert result["system_wav"].startswith(result["session_dir"])
        assert result["mic_wav"].startswith(result["session_dir"])

    def test_duration_is_positive(self, recorder, mock_popen):
        """duration_seconds is non-negative."""
        _, proc = mock_popen
        proc.wait.return_value = 0
        recorder.start("Zoom")
        result = recorder.stop()
        assert result["duration_seconds"] >= 0
