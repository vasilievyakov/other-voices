"""Tests for src.database — real SQLite on tmp_path, no mocks."""

import json

from src.database import Database


class TestInsertAndGet:
    def test_insert_and_get_call(self, tmp_db):
        """Insert + get round-trip, all fields present."""
        tmp_db.insert_call(
            session_id="s1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path="/rec/s1/system.wav",
            mic_wav_path="/rec/s1/mic.wav",
            transcript="Hello world",
            summary={"summary": "Test call", "action_items": []},
        )
        call = tmp_db.get_call("s1")
        assert call is not None
        assert call["session_id"] == "s1"
        assert call["app_name"] == "Zoom"
        assert call["started_at"] == "2025-02-20T10:00:00"
        assert call["ended_at"] == "2025-02-20T10:30:00"
        assert call["duration_seconds"] == 1800.0
        assert call["system_wav_path"] == "/rec/s1/system.wav"
        assert call["mic_wav_path"] == "/rec/s1/mic.wav"
        assert call["transcript"] == "Hello world"
        parsed = json.loads(call["summary_json"])
        assert parsed["summary"] == "Test call"

    def test_insert_with_none_summary(self, tmp_db):
        """summary=None doesn't crash, stored as NULL."""
        tmp_db.insert_call(
            session_id="s2",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript=None,
            summary=None,
        )
        call = tmp_db.get_call("s2")
        assert call is not None
        assert call["summary_json"] is None
        assert call["transcript"] is None

    def test_insert_or_replace(self, tmp_db):
        """Repeated session_id overwrites the record."""
        tmp_db.insert_call(
            session_id="s3",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="First",
            summary=None,
        )
        tmp_db.insert_call(
            session_id="s3",
            app_name="Google Meet",
            started_at="2025-02-20T11:00:00",
            ended_at="2025-02-20T11:30:00",
            duration_seconds=900.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Second",
            summary=None,
        )
        call = tmp_db.get_call("s3")
        assert call["app_name"] == "Google Meet"
        assert call["transcript"] == "Second"


class TestListRecent:
    def test_list_recent_ordering(self, populated_db):
        """Sorted by started_at DESC, limit works."""
        results = populated_db.list_recent(limit=2)
        assert len(results) == 2
        assert results[0]["session_id"] == "20250220_140000"
        assert results[1]["session_id"] == "20250220_100000"

    def test_list_recent_empty(self, tmp_db):
        """Empty DB returns empty list."""
        assert tmp_db.list_recent() == []


class TestFTS5Search:
    def test_search_fts5_transcript(self, populated_db):
        """FTS5 MATCH finds text in transcript."""
        results = populated_db.search("deployment")
        assert len(results) == 1
        assert results[0]["session_id"] == "20250220_140000"

    def test_search_fts5_summary(self, populated_db):
        """FTS5 MATCH finds text in summary_json."""
        results = populated_db.search("Альфа")
        assert len(results) == 1
        assert results[0]["session_id"] == "20250220_100000"

    def test_search_no_results(self, populated_db):
        """No matches returns empty list."""
        results = populated_db.search("xyznonexistent")
        assert results == []


class TestActionItems:
    def test_get_action_items_by_days(self, populated_db):
        """Filters by date window, parses action_items."""
        results = populated_db.get_action_items(days=365)
        assert len(results) >= 1
        item = next(r for r in results if r["session_id"] == "20250220_100000")
        assert "Написать ТЗ (@Вася, пятница)" in item["action_items"]

    def test_get_action_items_skips_empty(self, populated_db):
        """Calls without action_items are not returned."""
        results = populated_db.get_action_items(days=365)
        session_ids = [r["session_id"] for r in results]
        # Google Meet has empty action_items, Telegram has no summary
        assert "20250220_140000" not in session_ids
        assert "20250219_090000" not in session_ids
