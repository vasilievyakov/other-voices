"""Tests for src.daemon — mock STATUS_PATH and dependencies."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.daemon import write_status, process_recording, notify


class TestWriteStatus:
    def test_write_status_creates_file(self, tmp_path):
        """write_status → JSON with correct fields."""
        status_path = tmp_path / "status.json"
        with patch("src.daemon.STATUS_PATH", status_path):
            write_status("idle", app_name="Zoom", session_id="s1")

        data = json.loads(status_path.read_text())
        assert data["state"] == "idle"
        assert data["app_name"] == "Zoom"
        assert data["session_id"] == "s1"
        assert "daemon_pid" in data
        assert "timestamp" in data

    def test_write_status_atomic(self, tmp_path):
        """Writes to .tmp first, then os.replace."""
        status_path = tmp_path / "status.json"
        with (
            patch("src.daemon.STATUS_PATH", status_path),
            patch("src.daemon.os.replace", wraps=os.replace) as mock_replace,
        ):
            write_status("idle")

        mock_replace.assert_called_once()
        tmp_arg = mock_replace.call_args[0][0]
        assert str(tmp_arg).endswith(".tmp")


class TestProcessRecording:
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_process_short_call_skipped(
        self, mock_status, mock_notify, tmp_db, sample_session
    ):
        """Duration < MIN_CALL_DURATION → skip."""
        sample_session["duration_seconds"] = 10.0
        transcriber = MagicMock()
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe.assert_not_called()
        summarizer.summarize.assert_not_called()

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_process_no_transcript(
        self, mock_status, mock_notify, tmp_db, sample_session
    ):
        """Transcription fails → save without summary."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = None
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        summarizer.summarize.assert_not_called()
        call = tmp_db.get_call(sample_session["session_id"])
        assert call is not None
        assert call["transcript"] is None
        assert call["summary_json"] is None

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_process_full_pipeline(
        self, mock_status, mock_notify, tmp_db, sample_session, sample_summary
    ):
        """transcribe → summarize → insert_call."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Full transcript text here"
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe.assert_called_once_with(sample_session["session_dir"])
        summarizer.summarize.assert_called_once_with("Full transcript text here")
        call = tmp_db.get_call(sample_session["session_id"])
        assert call is not None
        assert call["transcript"] == "Full transcript text here"
        parsed = json.loads(call["summary_json"])
        assert parsed["summary"] == sample_summary["summary"]

    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_process_no_summary(self, mock_status, mock_notify, tmp_db, sample_session):
        """summarizer returns None → save with transcript but no summary."""
        transcriber = MagicMock()
        transcriber.transcribe.return_value = "Some transcript"
        summarizer = MagicMock()
        summarizer.summarize.return_value = None

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        call = tmp_db.get_call(sample_session["session_id"])
        assert call is not None
        assert call["transcript"] == "Some transcript"
        assert call["summary_json"] is None

    @patch("src.daemon.subprocess.run")
    def test_notify_handles_exception(self, mock_run):
        """subprocess raises → doesn't crash."""
        mock_run.side_effect = OSError("No osascript")
        # Should not raise
        notify("Test", "Message")
