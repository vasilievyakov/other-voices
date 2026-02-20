"""Integration tests — multi-component pipelines.

Enterprise coverage: end-to-end data flow across components.
"""

import json
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from src.database import Database
from src.daemon import process_recording
from src.summarizer import Summarizer


# =============================================================================
# Integration Tests (5 tests)
# =============================================================================


class TestIntegration:
    @staticmethod
    def _make_separate(text):
        """Create a transcribe_separate() return value."""
        return {
            "text": text,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": text, "speaker": "SPEAKER_ME"},
            ],
            "transcript_me": [{"start": 0.0, "end": 5.0, "text": text}],
            "transcript_others": [],
        }

    def test_full_pipeline_data_integrity(self, tmp_db, sample_session, sample_summary):
        """Full pipeline: process_recording → get_call → all fields match."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate(
            "Full transcript for integration test"
        )
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        with (
            patch("src.daemon.notify"),
            patch("src.daemon.write_status"),
            patch(
                "src.daemon.resolve_speakers",
                return_value={"SPEAKER_ME": {"confirmed": True}},
            ),
            patch("src.daemon.extract_commitments", return_value={"commitments": []}),
        ):
            process_recording(sample_session, transcriber, summarizer, tmp_db)

        call = tmp_db.get_call(sample_session["session_id"])
        assert call is not None
        assert call["session_id"] == sample_session["session_id"]
        assert call["app_name"] == sample_session["app_name"]
        assert call["transcript"] == "Full transcript for integration test"
        parsed = json.loads(call["summary_json"])
        assert parsed["summary"] == sample_summary["summary"]
        assert parsed["action_items"] == sample_summary["action_items"]

    def test_pipeline_then_search(self, tmp_db, sample_session, sample_summary):
        """After pipeline, FTS5 search finds the call."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate(
            "Discussed quantum computing breakthroughs"
        )
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        with (
            patch("src.daemon.notify"),
            patch("src.daemon.write_status"),
            patch(
                "src.daemon.resolve_speakers",
                return_value={"SPEAKER_ME": {"confirmed": True}},
            ),
            patch("src.daemon.extract_commitments", return_value={"commitments": []}),
        ):
            process_recording(sample_session, transcriber, summarizer, tmp_db)

        results = tmp_db.search("quantum")
        assert len(results) == 1
        assert results[0]["session_id"] == sample_session["session_id"]

    def test_pipeline_then_action_items(self, tmp_db, sample_session, sample_summary):
        """After pipeline, action_items are retrievable."""
        transcriber = MagicMock()
        transcriber.transcribe_separate.return_value = self._make_separate(
            "Some transcript"
        )
        summarizer = MagicMock()
        summarizer.summarize.return_value = sample_summary

        with (
            patch("src.daemon.notify"),
            patch("src.daemon.write_status"),
            patch(
                "src.daemon.resolve_speakers",
                return_value={"SPEAKER_ME": {"confirmed": True}},
            ),
            patch("src.daemon.extract_commitments", return_value={"commitments": []}),
        ):
            process_recording(sample_session, transcriber, summarizer, tmp_db)

        items = tmp_db.get_action_items(days=365)
        assert len(items) >= 1
        found = next(
            i for i in items if i["session_id"] == sample_session["session_id"]
        )
        assert "Подготовить RFC (@Вася)" in found["action_items"]

    def test_multiple_calls_isolation(self, tmp_db, tmp_path):
        """Multiple calls processed independently, data doesn't leak."""
        sessions = []
        for i in range(3):
            d = tmp_path / f"session_{i}"
            d.mkdir()
            sessions.append(
                {
                    "session_id": f"integ_{i}",
                    "app_name": ["Zoom", "Google Meet", "Telegram"][i],
                    "started_at": f"2025-02-20T{10 + i}:00:00",
                    "ended_at": f"2025-02-20T{10 + i}:30:00",
                    "duration_seconds": 1800.0,
                    "session_dir": str(d),
                    "system_wav": str(d / "system.wav"),
                    "mic_wav": str(d / "mic.wav"),
                }
            )

        transcriber = MagicMock()
        summarizer = MagicMock()

        for i, session in enumerate(sessions):
            transcriber.transcribe_separate.return_value = self._make_separate(
                f"Unique transcript {i}"
            )
            summarizer.summarize.return_value = {
                "summary": f"Summary {i}",
                "key_points": [],
                "decisions": [],
                "action_items": [f"Task {i}"] if i == 0 else [],
                "participants": [],
            }
            with (
                patch("src.daemon.notify"),
                patch("src.daemon.write_status"),
                patch(
                    "src.daemon.resolve_speakers",
                    return_value={"SPEAKER_ME": {"confirmed": True}},
                ),
                patch(
                    "src.daemon.extract_commitments", return_value={"commitments": []}
                ),
            ):
                process_recording(session, transcriber, summarizer, tmp_db)

        all_calls = tmp_db.list_recent()
        assert len(all_calls) == 3

        for i in range(3):
            call = tmp_db.get_call(f"integ_{i}")
            assert call["transcript"] == f"Unique transcript {i}"

    def test_summarizer_input_validation_with_db(self, tmp_db):
        """Summarizer.summarize(None) → None; DB stores null summary."""
        summarizer = Summarizer()
        result = summarizer.summarize(None)
        assert result is None

        tmp_db.insert_call(
            session_id="null_sum",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Some text",
            summary=result,
        )
        call = tmp_db.get_call("null_sum")
        assert call["summary_json"] is None
