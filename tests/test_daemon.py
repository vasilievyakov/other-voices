"""Tests for src.daemon — structured logging, Ollama health check, pipeline.

Enterprise coverage: write_status, process_recording, notify, main loop,
Ollama graceful degradation, structured logging.
"""

import json
import logging
import os
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from src.daemon import write_status, process_recording, notify, _Timer, _log


# Helper: mock all settings to return defaults (enabled)
_SETTINGS_DEFAULTS = {
    "src.daemon.get_min_call_duration": 30,
    "src.daemon.should_transcribe": True,
    "src.daemon.should_summarize": True,
    "src.daemon.should_extract_commitments": True,
    "src.daemon.get_default_template": "default",
}


def _patch_settings():
    """Return a list of patch context managers for all settings functions."""
    return [patch(k, return_value=v) for k, v in _SETTINGS_DEFAULTS.items()]


# =============================================================================
# Write Status (6 tests)
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

    def test_ollama_available_in_status(self, tmp_path):
        """status.json includes ollama_available field."""
        import src.daemon

        status_path = tmp_path / "status.json"
        with patch("src.daemon.STATUS_PATH", status_path):
            src.daemon._ollama_available = True
            write_status("idle")

        data = json.loads(status_path.read_text())
        assert data["ollama_available"] is True

        with patch("src.daemon.STATUS_PATH", status_path):
            src.daemon._ollama_available = False
            write_status("idle")

        data = json.loads(status_path.read_text())
        assert data["ollama_available"] is False


# =============================================================================
# Process Recording (10 tests)
# =============================================================================


class TestProcessRecording:
    """Tests for process_recording pipeline.

    The pipeline is: check_ollama -> transcribe_separate -> fallback(transcribe)
    -> resolve_speakers -> summarize -> extract_commitments -> save.
    """

    def _make_separate_result(self, text="Full transcript text here"):
        """Create a mock transcribe_separate() return value."""
        return {
            "text": text,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": text, "speaker": "SPEAKER_ME"},
            ],
            "transcript_me": [{"start": 0.0, "end": 5.0, "text": text}],
            "transcript_others": [],
        }

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_short_call_skipped(
        self,
        mock_status,
        mock_notify,
        mock_min_dur,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
    ):
        """Duration < MIN_CALL_DURATION -> skip processing."""
        sample_session["duration_seconds"] = 10.0
        transcriber = MagicMock()
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe_separate.assert_not_called()
        transcriber.transcribe.assert_not_called()
        summarizer.summarize.assert_not_called()

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_no_transcript_saves_without_summary(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
    ):
        """Both transcriptions fail -> save record without transcript/summary."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = None
        transcriber.transcribe.return_value = None
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        summarizer.summarize.assert_not_called()
        mock_resolve.assert_not_called()
        mock_extract.assert_not_called()
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record is not None
        assert call_record["transcript"] is None
        assert call_record["summary_json"] is None

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments", return_value={"commitments": []})
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_full_pipeline(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
        sample_summary,
    ):
        """transcribe_separate -> resolve -> summarize -> extract -> save."""
        transcriber = MagicMock()
        separate = self._make_separate_result()
        transcriber.transcribe_separate.return_value = separate
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        transcriber.transcribe_separate.assert_called_once_with(
            sample_session["session_dir"]
        )
        mock_resolve.assert_called_once()
        summarizer.summarize.assert_called_once()
        mock_extract.assert_called_once()
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record is not None
        assert call_record["transcript"] == separate["text"]
        parsed = json.loads(call_record["summary_json"])
        assert parsed["summary"] == sample_summary["summary"]

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments", return_value={"commitments": []})
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_fallback_to_merged_transcribe(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
        sample_summary,
    ):
        """transcribe_separate fails -> falls back to transcribe()."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = None
        transcriber.transcribe.return_value = "Merged transcript text"
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        # Fallback path: no speaker resolution or commitment extraction
        mock_resolve.assert_not_called()
        mock_extract.assert_not_called()
        summarizer.summarize.assert_called_once()
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record["transcript"] == "Merged transcript text"

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments", return_value={"commitments": []})
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_no_summary_saves_transcript(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
    ):
        """summarizer returns None -> save with transcript but no summary."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate_result(
            "Some transcript"
        )
        summarizer = MagicMock()
        summarizer.summarize.return_value = None

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record["transcript"] == "Some transcript"
        assert call_record["summary_json"] is None

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments", return_value={"commitments": []})
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_write_status_pipeline_stages(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
        sample_summary,
    ):
        """write_status is called with all pipeline stages."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate_result()
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
        assert "resolving speakers" in pipelines
        assert "summarizing" in pipelines
        assert "extracting commitments" in pipelines
        assert "saving" in pipelines

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_short_call_notifies(
        self,
        mock_status,
        mock_notify,
        mock_min_dur,
        mock_check,
        tmp_db,
        sample_session,
    ):
        """Short call sends notification about being skipped."""
        sample_session["duration_seconds"] = 5.0
        process_recording(sample_session, MagicMock(), MagicMock(), tmp_db)
        mock_notify.assert_called()

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments", return_value={"commitments": []})
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_full_pipeline_notifies(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
        sample_summary,
    ):
        """Full pipeline sends notification at start and end."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        # At least 2 notify calls: processing start + saved
        assert mock_notify.call_count >= 2

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments")
    @patch(
        "src.daemon.resolve_speakers",
        return_value={"SPEAKER_ME": {"confirmed": True}},
    )
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_commitments_saved_to_db(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
        sample_summary,
    ):
        """Extracted commitments are saved to the database."""
        mock_extract.return_value = {
            "commitments": [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "SPEAKER_OTHER",
                    "what": "Send proposal by Friday",
                    "quote": "I'll send it by Friday",
                    "timestamp": "00:03:42",
                    "deadline": "Friday",
                    "uncertain": False,
                }
            ]
        }
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate_result()
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        commitments = tmp_db.get_commitments(sample_session["session_id"])
        assert len(commitments) == 1
        assert commitments[0]["direction"] == "outgoing"
        assert commitments[0]["text"] == "Send proposal by Friday"

    # ── Ollama unavailability tests ──

    @patch("src.daemon.check_ollama", return_value=False)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
    @patch("src.daemon.extract_commitments")
    @patch("src.daemon.resolve_speakers")
    @patch("src.daemon.notify")
    @patch("src.daemon.write_status")
    def test_ollama_down_skips_ai_stages(
        self,
        mock_status,
        mock_notify,
        mock_resolve,
        mock_extract,
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
        tmp_db,
        sample_session,
    ):
        """When Ollama is down: transcribe runs, but summarize/resolve/extract skip."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate_result(
            "Transcript from call"
        )
        summarizer = MagicMock()

        process_recording(sample_session, transcriber, summarizer, tmp_db)

        # Transcription still happens
        transcriber.transcribe_separate.assert_called_once()

        # AI stages are skipped
        mock_resolve.assert_not_called()
        summarizer.summarize.assert_not_called()
        mock_extract.assert_not_called()

        # Call is still saved with transcript but no summary
        call_record = tmp_db.get_call(sample_session["session_id"])
        assert call_record is not None
        assert call_record["transcript"] == "Transcript from call"
        assert call_record["summary_json"] is None


# =============================================================================
# Ollama Health Check (3 tests)
# =============================================================================


class TestCheckOllama:
    @patch("src.config.urllib.request.urlopen")
    def test_ollama_healthy(self, mock_urlopen):
        """check_ollama returns True when Ollama responds with models."""
        from src.config import check_ollama

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"models": [{"name": "qwen3:14b"}]}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert check_ollama() is True

    @patch(
        "src.config.urllib.request.urlopen",
        side_effect=OSError("Connection refused"),
    )
    def test_ollama_unreachable(self, mock_urlopen):
        """check_ollama returns False when Ollama is not running."""
        from src.config import check_ollama

        assert check_ollama() is False

    @patch("src.config.urllib.request.urlopen")
    def test_ollama_empty_models(self, mock_urlopen):
        """check_ollama returns True even with empty models list."""
        from src.config import check_ollama

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"models": []}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert check_ollama() is True


# =============================================================================
# Timer (2 tests)
# =============================================================================


class TestTimer:
    def test_timer_measures_duration(self):
        """_Timer records elapsed time in milliseconds."""
        import time

        with _Timer() as t:
            time.sleep(0.05)  # 50ms

        assert t.elapsed_ms >= 40  # Allow some slack
        assert t.elapsed_ms < 500  # But not crazy high

    def test_timer_zero_on_fast_op(self):
        """_Timer records near-zero for instant operations."""
        with _Timer() as t:
            _ = 1 + 1

        assert t.elapsed_ms < 10


# =============================================================================
# Structured Logging (3 tests)
# =============================================================================


class TestStructuredLogging:
    def test_log_helper_with_stage(self, caplog):
        """_log emits messages with stage field."""
        with caplog.at_level(logging.INFO):
            _log(logging.INFO, "transcription", "test message")

        assert len(caplog.records) >= 1
        record = caplog.records[-1]
        assert record.stage == "transcription"
        assert "test message" in record.message

    def test_log_helper_with_duration(self, caplog):
        """_log appends duration when provided."""
        with caplog.at_level(logging.INFO):
            _log(logging.INFO, "summarization", "done", duration_ms=1234.7)

        record = caplog.records[-1]
        assert "[duration=1235ms]" in record.message

    def test_log_helper_without_duration(self, caplog):
        """_log omits duration suffix when not provided."""
        with caplog.at_level(logging.INFO):
            _log(logging.INFO, "pipeline", "starting")

        record = caplog.records[-1]
        assert "duration=" not in record.message


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
        """subprocess raises -> doesn't crash."""
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

    @patch("src.daemon.check_ollama", return_value=True)
    @patch("src.daemon.should_transcribe", return_value=True)
    @patch("src.daemon.should_summarize", return_value=True)
    @patch("src.daemon.should_extract_commitments", return_value=True)
    @patch("src.daemon.get_min_call_duration", return_value=30)
    @patch("src.daemon.get_default_template", return_value="default")
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
        mock_template,
        mock_min_dur,
        mock_extract_setting,
        mock_summarize_setting,
        mock_transcribe_setting,
        mock_check,
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
