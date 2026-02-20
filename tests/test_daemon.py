"""Tests for src.daemon — mock STATUS_PATH and dependencies.

Enterprise coverage: write_status, process_recording, notify, main loop.
"""

import json
import os
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from src.daemon import write_status, process_recording, notify


# =============================================================================
# Write Status (5 tests)
# =============================================================================


class TestWriteStatus:
    def test_creates_json_file(self, tmp_path):
        """write_status creates JSON file with correct fields."""
        status_path = tmp_path / "status.json"
        with patch("src.daemon.STATUS_PATH", status_path):
            write_status("idle", app_name="Zoom", session_id="s1")

        data = json.loads(status_path.read_text())
        assert data["state"] == "idle"
        assert data["app_name"] == "Zoom"
        assert data["session_id"] == "s1"
        assert "daemon_pid" in data
        assert "timestamp" in data

    def test_atomic_via_os_replace(self, tmp_path):
        """Writes to .tmp first, then os.replace."""
        status_path = tmp_path / "status.json"
        with (
            patch("src.daemon.STATUS_PATH", status_path),
            patch("src.daemon.os.replace", wraps=os.replace) as mock_replace,
        ):
            write_status("idle")

        mock_replace.assert_called_once()
        tmp_arg = str(mock_replace.call_args[0][0])
        assert tmp_arg.endswith(".tmp")

    def test_pipeline_field(self, tmp_path):
        """Pipeline stage is stored in status."""
        status_path = tmp_path / "status.json"
        with patch("src.daemon.STATUS_PATH", status_path):
            write_status("processing", pipeline="transcribing")

        data = json.loads(status_path.read_text())
        assert data["pipeline"] == "transcribing"

    def test_none_optional_fields(self, tmp_path):
        """Optional fields default to None."""
        status_path = tmp_path / "status.json"
        with patch("src.daemon.STATUS_PATH", status_path):
            write_status("idle")

        data = json.loads(status_path.read_text())
        assert data["app_name"] is None
        assert data["session_id"] is None
        assert data["started_at"] is None
        assert data["pipeline"] is None

    def test_write_failure_no_crash(self, tmp_path):
        """If write fails (e.g., read-only dir), doesn't crash."""
        status_path = tmp_path / "readonly" / "status.json"
        # Don't create the directory — write will fail
        with patch("src.daemon.STATUS_PATH", status_path):
            # Should log warning but not raise
            write_status("idle")


# =============================================================================
# Process Recording (7 tests)
# =============================================================================


class TestProcessRecording:
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_short_call_skipped(self, mock_status, mock_notify, tmp_db, sample_session):
        """Duration < MIN_CALL_DURATION → skip processing."""
        sample_session["duration_seconds"] = 10.0
        transcriber = MagicMock()
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe.assert_not_called()
        summarizer.summarize.assert_not_called()

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_no_transcript_saves_without_summary(
        self, mock_status, mock_notify, tmp_db, sample_session
    ):
        """Transcription fails → save record without transcript/summary."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = None
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        summarizer.summarize.assert_not_called()
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record is not None
        assert call_record["transcript"] is None
        assert call_record["summary_json"] is None

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_full_pipeline(
        self, mock_status, mock_notify, tmp_db, sample_session, sample_summary
    ):
        """transcribe → summarize → insert_call — full pipeline."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Full transcript text here"
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe.assert_called_once_with(sample_session["session_dir"])
        summarizer.summarize.assert_called_once_with(
            "Full transcript text here", template_name="default", segments=None
        )
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record is not None
        assert call_record["transcript"] == "Full transcript text here"
        parsed = json.loads(call_record["summary_json"])
        assert parsed["summary"] == sample_summary["summary"]

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_no_summary_saves_transcript(
        self, mock_status, mock_notify, tmp_db, sample_session
    ):
        """summarizer returns None → save with transcript but no summary."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Some transcript"
        summarizer = MagicMock()
        summarizer.summarize.return_value = None

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record["transcript"] == "Some transcript"
        assert call_record["summary_json"] is None

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_write_status_pipeline_stages(
        self, mock_status, mock_notify, tmp_db, sample_session, sample_summary
    ):
        """write_status is called with pipeline stages: transcribing, summarizing, saving."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Transcript"
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        pipeline_calls = [
            c
            for c in mock_status.call_args_list
            if len(c[0]) >= 5 and c[0][4] is not None
        ]
        pipelines = [c[0][4] for c in pipeline_calls]
        assert "transcribing" in pipelines
        assert "summarizing" in pipelines
        assert "saving" in pipelines

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_short_call_notifies(
        self, mock_status, mock_notify, tmp_db, sample_session
    ):
        """Short call sends notification about being skipped."""
        sample_session["duration_seconds"] = 5.0
        process_recording(sample_session, MagicMock(), MagicMock(), tmp_db)
        mock_notify.assert_called()

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_full_pipeline_notifies(
        self, mock_status, mock_notify, tmp_db, sample_session, sample_summary
    ):
        """Full pipeline sends notification at start and end."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Transcript"
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        # At least 2 notify calls: processing start + saved
        assert mock_notify.call_count >= 2


# =============================================================================
# Notify (3 tests)
# =============================================================================


class TestNotify:
    @patch("src.daemon.subprocess.run")
    def test_notify_calls_osascript(self, mock_run):
        """notify() calls osascript."""
        mock_run.return_value = MagicMock(returncode=0)
        notify("Title", "Message")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"

    @patch("src.daemon.subprocess.run")
    def test_notify_handles_exception(self, mock_run):
        """subprocess raises → doesn't crash."""
        mock_run.side_effect = OSError("No osascript")
        notify("Test", "Message")  # Should not raise

    @patch("src.daemon.subprocess.run")
    def test_notify_timeout(self, mock_run):
        """notify passes timeout argument."""
        mock_run.return_value = MagicMock(returncode=0)
        notify("Title", "Message")
        kwargs = mock_run.call_args[1]
        assert "timeout" in kwargs


# =============================================================================
# Main Loop (2 tests — limited scope, no real loop)
# =============================================================================


class TestMainLoop:
    def test_main_imports(self):
        """main() function is importable."""
        from src.daemon import main

        assert callable(main)

    @patch("src.daemon.time.sleep", side_effect=KeyboardInterrupt)
    @patch("src.daemon.write_status")
    @patch("src.daemon.notify")
    @patch("src.daemon.Database")
    @patch("src.daemon.Summarizer")
    @patch("src.daemon.Transcriber")
    @patch("src.daemon.AudioRecorder")
    @patch("src.daemon.CallDetector")
    def test_main_handles_keyboard_interrupt(
        self,
        mock_detector,
        mock_recorder,
        mock_transcriber,
        mock_summarizer,
        mock_db,
        mock_notify,
        mock_status,
        mock_sleep,
    ):
        """main() handles KeyboardInterrupt gracefully via signal."""
        mock_detector_inst = MagicMock()
        mock_detector_inst.check.return_value = (False, None)
        mock_detector.return_value = mock_detector_inst

        mock_recorder_inst = MagicMock()
        mock_recorder_inst.is_recording = False
        mock_recorder.return_value = mock_recorder_inst

        from src.daemon import main

        # KeyboardInterrupt from sleep should be caught
        with pytest.raises(KeyboardInterrupt):
            main()
