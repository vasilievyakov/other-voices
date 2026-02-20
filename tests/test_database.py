"""Tests for src.database — real SQLite on tmp_path, no mocks.

Enterprise coverage: CRUD, FTS5, action items, security, concurrency.
"""

import json
import sqlite3
import threading

import pytest

from src.database import Database


# =============================================================================
# CRUD Operations (9 tests)
# =============================================================================


class TestCRUD:
    def test_insert_and_get_roundtrip(self, tmp_db):
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
        """summary=None stored as NULL, doesn't crash."""
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

    def test_insert_with_none_paths(self, tmp_db):
        """system_wav_path and mic_wav_path can be None."""
        tmp_db.insert_call(
            session_id="s3",
            app_name="Google Meet",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:15:00",
            duration_seconds=900.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Some text",
            summary=None,
        )
        call = tmp_db.get_call("s3")
        assert call["system_wav_path"] is None
        assert call["mic_wav_path"] is None

    def test_insert_or_replace_overwrites(self, tmp_db):
        """Repeated session_id overwrites the record (INSERT OR REPLACE)."""
        tmp_db.insert_call(
            session_id="s4",
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
            session_id="s4",
            app_name="Google Meet",
            started_at="2025-02-20T11:00:00",
            ended_at="2025-02-20T11:30:00",
            duration_seconds=900.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Second",
            summary=None,
        )
        call = tmp_db.get_call("s4")
        assert call["app_name"] == "Google Meet"
        assert call["transcript"] == "Second"

    def test_insert_or_replace_fts_updated(self, tmp_db):
        """After INSERT OR REPLACE, FTS index reflects new data."""
        tmp_db.insert_call(
            session_id="fts_replace",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="original unicorn text",
            summary=None,
        )
        assert len(tmp_db.search("unicorn")) == 1

        # Replace with different text
        tmp_db.insert_call(
            session_id="fts_replace",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="replaced dragon text",
            summary=None,
        )
        assert len(tmp_db.search("unicorn")) == 0
        assert len(tmp_db.search("dragon")) == 1

    def test_get_nonexistent_returns_none(self, tmp_db):
        """get_call for missing session_id returns None."""
        assert tmp_db.get_call("nonexistent") is None

    def test_list_recent_ordering(self, populated_db):
        """Sorted by started_at DESC, limit works."""
        results = populated_db.list_recent(limit=2)
        assert len(results) == 2
        assert results[0]["session_id"] == "20250220_140000"
        assert results[1]["session_id"] == "20250220_100000"

    def test_list_recent_empty(self, tmp_db):
        """Empty DB returns empty list."""
        assert tmp_db.list_recent() == []

    def test_list_recent_default_limit(self, populated_db):
        """Default limit returns all 3 records."""
        results = populated_db.list_recent()
        assert len(results) == 3


# =============================================================================
# FTS5 Full-Text Search (9 tests)
# =============================================================================


class TestFTS5:
    def test_search_transcript(self, populated_db):
        """FTS5 MATCH finds text in transcript."""
        results = populated_db.search("deployment")
        assert len(results) == 1
        assert results[0]["session_id"] == "20250220_140000"

    def test_search_summary_json(self, populated_db):
        """FTS5 MATCH finds text in summary_json."""
        results = populated_db.search("Альфа")
        assert len(results) == 1
        assert results[0]["session_id"] == "20250220_100000"

    def test_search_app_name(self, populated_db):
        """FTS5 MATCH finds text in app_name field."""
        results = populated_db.search("Telegram")
        assert len(results) == 1
        assert results[0]["session_id"] == "20250219_090000"

    def test_search_no_results(self, populated_db):
        """No matches returns empty list."""
        results = populated_db.search("xyznonexistent")
        assert results == []

    def test_search_returns_snippet(self, populated_db):
        """Search results include snippet field."""
        results = populated_db.search("deployment")
        assert len(results) == 1
        assert "snippet" in results[0]

    def test_search_limit(self, tmp_db):
        """Search respects limit parameter."""
        for i in range(5):
            tmp_db.insert_call(
                session_id=f"lim_{i}",
                app_name="Zoom",
                started_at=f"2025-02-20T{10 + i}:00:00",
                ended_at=f"2025-02-20T{10 + i}:30:00",
                duration_seconds=1800.0,
                system_wav_path=None,
                mic_wav_path=None,
                transcript=f"Meeting about quarterly review number {i}",
                summary=None,
            )
        results = tmp_db.search("quarterly", limit=2)
        assert len(results) == 2

    def test_search_after_update(self, tmp_db):
        """FTS index updates after INSERT OR REPLACE."""
        tmp_db.insert_call(
            session_id="upd1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Alpha topic",
            summary=None,
        )
        assert len(tmp_db.search("Alpha")) == 1

        tmp_db.insert_call(
            session_id="upd1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Beta topic",
            summary=None,
        )
        assert len(tmp_db.search("Alpha")) == 0
        assert len(tmp_db.search("Beta")) == 1

    def test_search_cyrillic(self, populated_db):
        """FTS5 unicode61 tokenizer handles Cyrillic text."""
        results = populated_db.search("проекта")
        assert len(results) >= 1

    def test_search_special_chars_safe(self, tmp_db):
        """Special characters in query don't crash FTS5."""
        # These might not match anything but shouldn't raise
        for query in ["hello*", "test OR debug", '"exact phrase"']:
            results = tmp_db.search(query)
            assert isinstance(results, list)


# =============================================================================
# Action Items (5 tests)
# =============================================================================


class TestActionItems:
    def test_get_action_items_by_days(self, populated_db):
        """Filters by date window, parses action_items."""
        results = populated_db.get_action_items(days=365)
        assert len(results) >= 1
        item = next(r for r in results if r["session_id"] == "20250220_100000")
        assert "Написать ТЗ (@Вася, пятница)" in item["action_items"]

    def test_get_action_items_skips_empty(self, populated_db):
        """Calls with empty action_items are not returned."""
        results = populated_db.get_action_items(days=365)
        session_ids = [r["session_id"] for r in results]
        assert "20250220_140000" not in session_ids
        assert "20250219_090000" not in session_ids

    def test_get_action_items_returns_app_name(self, populated_db):
        """Each result includes app_name and started_at."""
        results = populated_db.get_action_items(days=365)
        for r in results:
            assert "app_name" in r
            assert "started_at" in r

    def test_get_action_items_empty_db(self, tmp_db):
        """Empty database returns empty list."""
        assert tmp_db.get_action_items() == []

    def test_get_action_items_corrupt_json(self, tmp_db):
        """Corrupt summary_json is skipped without crash."""
        with tmp_db._conn() as conn:
            conn.execute(
                """INSERT INTO calls
                   (session_id, app_name, started_at, ended_at, duration_seconds,
                    transcript, summary_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "corrupt1",
                    "Zoom",
                    "2025-02-20T10:00:00",
                    "2025-02-20T10:30:00",
                    1800.0,
                    "text",
                    "{invalid json!!!",
                ),
            )
        results = tmp_db.get_action_items(days=365)
        session_ids = [r["session_id"] for r in results]
        assert "corrupt1" not in session_ids


# =============================================================================
# Database Security & Robustness (8 tests)
# =============================================================================


class TestDatabaseSecurity:
    def test_sql_injection_in_search(self, populated_db):
        """SQL injection attempt in search query — parameterized, table survives."""
        import sqlite3

        # FTS5 has its own syntax; ' triggers syntax error, not SQL injection
        try:
            results = populated_db.search("'; DROP TABLE calls; --")
            assert isinstance(results, list)
        except sqlite3.OperationalError:
            pass  # FTS5 syntax error is acceptable — no injection occurred
        # Table still intact regardless
        assert populated_db.get_call("20250220_100000") is not None

    def test_sql_injection_in_session_id(self, tmp_db):
        """SQL injection in session_id is safely handled."""
        tmp_db.insert_call(
            session_id="'; DROP TABLE calls; --",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        call = tmp_db.get_call("'; DROP TABLE calls; --")
        assert call is not None
        assert call["session_id"] == "'; DROP TABLE calls; --"

    def test_concurrent_init(self, tmp_path):
        """Multiple Database instances on same path don't corrupt."""
        db_path = tmp_path / "concurrent.db"
        db1 = Database(db_path=db_path)
        db2 = Database(db_path=db_path)
        db1.insert_call(
            session_id="c1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="From db1",
            summary=None,
        )
        call = db2.get_call("c1")
        assert call is not None
        assert call["transcript"] == "From db1"

    def test_concurrent_writes(self, tmp_path):
        """Concurrent writes from threads don't lose data."""
        db_path = tmp_path / "threads.db"
        db = Database(db_path=db_path)
        errors = []

        def writer(thread_id):
            try:
                for i in range(5):
                    db.insert_call(
                        session_id=f"t{thread_id}_{i}",
                        app_name="Zoom",
                        started_at="2025-02-20T10:00:00",
                        ended_at="2025-02-20T10:30:00",
                        duration_seconds=1800.0,
                        system_wav_path=None,
                        mic_wav_path=None,
                        transcript=f"Thread {thread_id} call {i}",
                        summary=None,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent write errors: {errors}"
        all_calls = db.list_recent(limit=100)
        assert len(all_calls) == 15  # 3 threads × 5 calls

    def test_large_transcript(self, tmp_db):
        """Very large transcript (100KB) is stored and retrieved."""
        big_text = "А" * 100_000
        tmp_db.insert_call(
            session_id="big",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript=big_text,
            summary=None,
        )
        call = tmp_db.get_call("big")
        assert len(call["transcript"]) == 100_000

    def test_unicode_in_all_fields(self, tmp_db):
        """Unicode (emoji, CJK, Arabic) in all text fields."""
        tmp_db.insert_call(
            session_id="unicode_test",
            app_name="会议 🎉",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="مرحبا 你好 привет 🌍",
            summary={"summary": "会议 مرحبا 🎉", "action_items": []},
        )
        call = tmp_db.get_call("unicode_test")
        assert "🎉" in call["app_name"]
        assert "مرحبا" in call["transcript"]

    def test_schema_idempotent(self, tmp_path):
        """Creating Database twice on same path doesn't duplicate schema."""
        db_path = tmp_path / "idem.db"
        db1 = Database(db_path=db_path)
        db1.insert_call(
            session_id="idem1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        # Re-init on same path
        db2 = Database(db_path=db_path)
        call = db2.get_call("idem1")
        assert call is not None

    def test_creates_parent_dirs(self, tmp_path):
        """Database creates parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "test.db"
        db = Database(db_path=deep_path)
        db.insert_call(
            session_id="deep1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Deep path test",
            summary=None,
        )
        assert db.get_call("deep1") is not None
