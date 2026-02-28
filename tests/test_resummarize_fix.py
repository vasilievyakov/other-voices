"""Test that re-summarization uses proper token limits and chunking.

Verifies the fix for the 51K token exhaustion bug: resummarize.py used
num_predict=1024 which truncated LLM output, causing JSON parsing failures
on long transcripts. After the fix, resummarize delegates to Summarizer
which uses num_predict=16384 and chunked processing.
"""

import json
import sqlite3
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.summarizer import Summarizer
from src.database import Database


def _mock_ollama(response_text):
    """Create a mock urlopen response in /api/chat format."""
    body = json.dumps(
        {
            "message": {"role": "assistant", "content": response_text},
        }
    ).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _valid_summary_json(**overrides):
    """Return a valid summary JSON string."""
    data = {
        "summary": "Test summary of the call",
        "title": "Test Call Summary",
        "key_points": ["point 1"],
        "decisions": ["decision 1"],
        "action_items": ["@Alice: task 1"],
        "participants": ["Alice", "Bob"],
        "entities": [],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _insert_test_call(db_path: Path, session_id: str, transcript: str):
    """Insert a test call directly into the database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS calls (
            session_id TEXT PRIMARY KEY,
            app_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            system_wav_path TEXT,
            mic_wav_path TEXT,
            transcript TEXT,
            summary_json TEXT,
            template_name TEXT DEFAULT 'default',
            notes TEXT,
            transcript_segments TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO calls
           (session_id, app_name, started_at, ended_at, duration_seconds,
            transcript, summary_json, template_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            "Zoom",
            "2025-02-20T10:00:00",
            "2025-02-20T10:30:00",
            1800.0,
            transcript,
            None,
            "default",
        ),
    )
    conn.commit()
    conn.close()


# =============================================================================
# Token Limits — The Core Bug Fix (3 tests)
# =============================================================================


class TestResummarizeTokenLimits:
    """Verify resummarize uses num_predict=16384, not the old 1024."""

    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_resummarize_single_uses_16384_num_predict(self, mock_urlopen, tmp_path):
        """resummarize_single sends num_predict=16384 to Ollama (was 1024)."""
        db_path = tmp_path / "test.db"
        transcript = "A" * 200  # Short but valid transcript
        _insert_test_call(db_path, "session_001", transcript)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        result = self.summarizer.resummarize_single("session_001", str(db_path))

        assert result is not None
        # Verify the Ollama request used 16384, not 1024
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["options"]["num_predict"] == 16384, (
            f"Expected num_predict=16384 but got {payload['options']['num_predict']}. "
            "This is the 51K bug: old resummarize.py used 1024 which truncates output."
        )

    @patch("src.summarizer.urllib.request.urlopen")
    def test_resummarize_batch_uses_16384_num_predict(self, mock_urlopen, tmp_path):
        """resummarize_batch sends num_predict=16384 for every call."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)
        _insert_test_call(db_path, "session_002", "B" * 200)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        result = self.summarizer.resummarize_batch(str(db_path))

        assert result["updated"] == 2
        # Check every Ollama call used 16384
        for call_args in mock_urlopen.call_args_list:
            req = call_args[0][0]
            payload = json.loads(req.data.decode("utf-8"))
            assert payload["options"]["num_predict"] == 16384

    @patch("src.summarizer.urllib.request.urlopen")
    def test_resummarize_uses_chat_api_not_generate(self, mock_urlopen, tmp_path):
        """resummarize uses /api/chat (Summarizer) not /api/generate (old code)."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        self.summarizer.resummarize_single("session_001", str(db_path))

        req = mock_urlopen.call_args[0][0]
        assert "/api/chat" in req.full_url, (
            "Expected /api/chat URL (Summarizer class) but got /api/generate (old code)"
        )


# =============================================================================
# Chunking for Long Transcripts (3 tests)
# =============================================================================


class TestResummarizeChunking:
    """Verify chunking is applied for long transcripts during resummarize."""

    def setup_method(self):
        self.summarizer = Summarizer()

    def _make_long_transcript(self, chars: int = 30000) -> str:
        """Create a transcript longer than CHUNK_MAX_CHARS (25000)."""
        line = "Speaker A: This is a test line for chunking verification.\n"
        return line * (chars // len(line) + 1)

    @patch("src.summarizer.urllib.request.urlopen")
    def test_long_transcript_is_chunked(self, mock_urlopen, tmp_path):
        """Transcripts >25K chars are split into chunks during resummarize."""
        db_path = tmp_path / "test.db"
        long_text = self._make_long_transcript(60000)
        _insert_test_call(db_path, "session_long", long_text)

        chunk_result = _valid_summary_json()
        merge_result = _valid_summary_json(summary="Merged final summary")

        # Multiple chunk calls + 1 merge call
        mock_urlopen.side_effect = [
            _mock_ollama(chunk_result),
            _mock_ollama(chunk_result),
            _mock_ollama(chunk_result),
            _mock_ollama(merge_result),
        ]

        result = self.summarizer.resummarize_single("session_long", str(db_path))

        assert result is not None
        # Verify multiple Ollama calls were made (chunked processing)
        assert mock_urlopen.call_count >= 3, (
            f"Expected at least 3 Ollama calls for 60K transcript (chunks + merge) "
            f"but got {mock_urlopen.call_count}. Old code truncated to 12K chars."
        )

    @patch("src.summarizer.urllib.request.urlopen")
    def test_short_transcript_not_chunked(self, mock_urlopen, tmp_path):
        """Transcripts <25K chars use single-pass summarization."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_short", "A" * 5000)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        result = self.summarizer.resummarize_single("session_short", str(db_path))

        assert result is not None
        assert mock_urlopen.call_count == 1, "Short transcript should use single pass"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_no_12k_truncation(self, mock_urlopen, tmp_path):
        """Verify transcript is NOT truncated to 12K (old MAX_CHARS bug)."""
        db_path = tmp_path / "test.db"
        # 20K transcript: old code would truncate to 12K, new code passes full text
        transcript = "A" * 20000
        _insert_test_call(db_path, "session_20k", transcript)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        self.summarizer.resummarize_single("session_20k", str(db_path))

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        prompt = payload["messages"][0]["content"]
        # The prompt should contain the full 20K transcript (not truncated to 12K)
        assert len(prompt) > 15000, (
            f"Prompt is only {len(prompt)} chars. "
            "Old code truncated to 12K (MAX_CHARS). "
            "New code should pass full transcript."
        )


# =============================================================================
# DB Integration — resummarize_single (4 tests)
# =============================================================================


class TestResummarizeSingle:
    """Test resummarize_single reads from DB, summarizes, and writes back."""

    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_writes_summary_to_db(self, mock_urlopen, tmp_path):
        """Summary JSON is written back to the calls table."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)

        expected_summary = {
            "summary": "Test summary",
            "title": "Test Title",
            "key_points": ["point 1"],
            "decisions": [],
            "action_items": [],
            "participants": ["Alice"],
            "entities": [],
        }
        mock_urlopen.return_value = _mock_ollama(json.dumps(expected_summary))

        result = self.summarizer.resummarize_single("session_001", str(db_path))

        assert result is not None
        # Verify DB was updated
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT summary_json, template_name FROM calls WHERE session_id = ?",
            ("session_001",),
        ).fetchone()
        conn.close()

        assert row is not None
        stored = json.loads(row[0])
        assert stored["summary"] == "Test summary"
        assert row[1] == "default"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_custom_template_written_to_db(self, mock_urlopen, tmp_path):
        """Template name is stored in DB when using non-default template."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        self.summarizer.resummarize_single(
            "session_001", str(db_path), template_name="sales_call"
        )

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT template_name FROM calls WHERE session_id = ?",
            ("session_001",),
        ).fetchone()
        conn.close()
        assert row[0] == "sales_call"

    def test_missing_session_returns_none(self, tmp_path):
        """Non-existent session_id returns None (not crash)."""
        db_path = tmp_path / "test.db"
        # Create empty table
        _insert_test_call(db_path, "other_session", "A" * 200)

        result = self.summarizer.resummarize_single("nonexistent", str(db_path))
        assert result is None

    def test_short_transcript_returns_none(self, tmp_path):
        """Transcript < 50 chars returns None."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_short", "Short")

        result = self.summarizer.resummarize_single("session_short", str(db_path))
        assert result is None


# =============================================================================
# DB Integration — resummarize_batch (3 tests)
# =============================================================================


class TestResummarizeBatch:
    """Test resummarize_batch processes all calls."""

    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_batch_processes_all_valid_calls(self, mock_urlopen, tmp_path):
        """Batch mode processes all calls with valid transcripts."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)
        _insert_test_call(db_path, "session_002", "B" * 200)
        _insert_test_call(db_path, "session_003", "Short")  # Too short, skip

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        result = self.summarizer.resummarize_batch(str(db_path))

        assert result["total"] == 3
        assert result["updated"] == 2  # 2 valid, 1 skipped
        assert result["skipped"] >= 1

    @patch("src.summarizer.urllib.request.urlopen")
    def test_batch_with_limit(self, mock_urlopen, tmp_path):
        """Batch mode respects limit parameter."""
        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)
        _insert_test_call(db_path, "session_002", "B" * 200)
        _insert_test_call(db_path, "session_003", "C" * 200)

        mock_urlopen.return_value = _mock_ollama(_valid_summary_json())

        result = self.summarizer.resummarize_batch(str(db_path), limit=2)

        assert result["updated"] <= 2

    @patch("src.summarizer.urllib.request.urlopen")
    def test_batch_handles_ollama_failure_gracefully(self, mock_urlopen, tmp_path):
        """Batch continues even when individual summarizations fail."""
        from urllib.error import URLError

        db_path = tmp_path / "test.db"
        _insert_test_call(db_path, "session_001", "A" * 200)
        _insert_test_call(db_path, "session_002", "B" * 200)

        # First call fails, second succeeds
        mock_urlopen.side_effect = [
            URLError("Connection refused"),
            _mock_ollama(_valid_summary_json()),
        ]

        result = self.summarizer.resummarize_batch(str(db_path))

        assert result["updated"] == 1
        assert result["failed"] == 1
