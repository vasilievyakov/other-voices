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


# =============================================================================
# Migration & New Columns (6 tests)
# =============================================================================


class TestMigrationAndNewColumns:
    def test_template_name_default(self, tmp_db):
        """New calls get template_name='default' by default."""
        tmp_db.insert_call(
            session_id="m1",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        call = tmp_db.get_call("m1")
        assert call["template_name"] == "default"

    def test_template_name_custom(self, tmp_db):
        """Custom template_name is stored and retrieved."""
        tmp_db.insert_call(
            session_id="m2",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
            template_name="sales_call",
        )
        call = tmp_db.get_call("m2")
        assert call["template_name"] == "sales_call"

    def test_notes_stored(self, tmp_db):
        """Notes are stored on insert."""
        tmp_db.insert_call(
            session_id="m3",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
            notes="Important meeting notes",
        )
        call = tmp_db.get_call("m3")
        assert call["notes"] == "Important meeting notes"

    def test_notes_default_none(self, tmp_db):
        """Notes default to None when not provided."""
        tmp_db.insert_call(
            session_id="m4",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        call = tmp_db.get_call("m4")
        assert call["notes"] is None

    def test_update_notes(self, tmp_db):
        """update_notes updates the notes column."""
        tmp_db.insert_call(
            session_id="m5",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        tmp_db.update_notes("m5", "Updated notes here")
        call = tmp_db.get_call("m5")
        assert call["notes"] == "Updated notes here"

    def test_transcript_segments_stored(self, tmp_db):
        """Transcript segments JSON is stored and retrieved."""
        import json as _json

        segments = [{"start": 0.0, "end": 2.5, "text": "Hello"}]
        segments_json = _json.dumps(segments, ensure_ascii=False)
        tmp_db.insert_call(
            session_id="m6",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Hello",
            summary=None,
            transcript_segments=segments_json,
        )
        call = tmp_db.get_call("m6")
        assert call["transcript_segments"] is not None
        parsed = _json.loads(call["transcript_segments"])
        assert len(parsed) == 1
        assert parsed[0]["text"] == "Hello"

    def test_transcript_segments_default_none(self, tmp_db):
        """Transcript segments default to None."""
        tmp_db.insert_call(
            session_id="m7",
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )
        call = tmp_db.get_call("m7")
        assert call["transcript_segments"] is None

    def test_migrate_existing_db(self, tmp_path):
        """Migration adds columns to a DB created without them."""
        import sqlite3

        db_path = tmp_path / "old.db"
        # Create a DB with old schema (no template_name, notes, transcript_segments)
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE calls (
                session_id TEXT PRIMARY KEY,
                app_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                system_wav_path TEXT,
                mic_wav_path TEXT,
                transcript TEXT,
                summary_json TEXT
            );
        """)
        conn.execute(
            """INSERT INTO calls (session_id, app_name, started_at, ended_at,
               duration_seconds, transcript) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "old1",
                "Zoom",
                "2025-01-01T10:00:00",
                "2025-01-01T10:30:00",
                1800.0,
                "Old data",
            ),
        )
        conn.commit()
        conn.close()

        # Now open with our Database class (triggers migration)
        db = Database(db_path=db_path)
        call = db.get_call("old1")
        assert call is not None
        assert call["transcript"] == "Old data"
        assert call["template_name"] == "default"
        assert call["notes"] is None


# =============================================================================
# Entities (8 tests)
# =============================================================================


class TestEntities:
    def _insert_call(self, db, session_id="e1"):
        db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )

    def test_insert_and_get_entities(self, tmp_db):
        """Insert entities and retrieve them."""
        self._insert_call(tmp_db)
        entities = [
            {"name": "Вася", "type": "person"},
            {"name": "Acme Corp", "type": "company"},
        ]
        tmp_db.insert_entities("e1", entities)
        result = tmp_db.get_entities("e1")
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert "Вася" in names
        assert "Acme Corp" in names

    def test_insert_entities_dedup(self, tmp_db):
        """Duplicate entities are ignored (UNIQUE constraint)."""
        self._insert_call(tmp_db)
        entities = [{"name": "Вася", "type": "person"}]
        tmp_db.insert_entities("e1", entities)
        tmp_db.insert_entities("e1", entities)  # duplicate
        result = tmp_db.get_entities("e1")
        assert len(result) == 1

    def test_insert_entities_skips_invalid(self, tmp_db):
        """Invalid entities (no name, bad type) are skipped."""
        self._insert_call(tmp_db)
        entities = [
            {"name": "", "type": "person"},  # empty name
            {"name": "X", "type": "alien"},  # invalid type
            {"name": "Valid", "type": "person"},  # valid
        ]
        tmp_db.insert_entities("e1", entities)
        result = tmp_db.get_entities("e1")
        assert len(result) == 1
        assert result[0]["name"] == "Valid"

    def test_search_entities(self, tmp_db):
        """Search entities by partial name."""
        self._insert_call(tmp_db)
        tmp_db.insert_entities(
            "e1",
            [
                {"name": "Василий Петров", "type": "person"},
                {"name": "Acme Corp", "type": "company"},
            ],
        )
        result = tmp_db.search_entities("Васил")
        assert len(result) == 1
        assert result[0]["name"] == "Василий Петров"

    def test_get_calls_by_entity(self, tmp_db):
        """Find calls mentioning a specific entity."""
        self._insert_call(tmp_db, "e1")
        self._insert_call(tmp_db, "e2")
        tmp_db.insert_entities("e1", [{"name": "Вася", "type": "person"}])
        tmp_db.insert_entities("e2", [{"name": "Вася", "type": "person"}])
        result = tmp_db.get_calls_by_entity("Вася")
        assert len(result) == 2

    def test_get_calls_by_entity_with_type(self, tmp_db):
        """Filter by entity type."""
        self._insert_call(tmp_db)
        tmp_db.insert_entities(
            "e1",
            [
                {"name": "Вася", "type": "person"},
                {"name": "Вася", "type": "company"},  # hypothetical
            ],
        )
        result = tmp_db.get_calls_by_entity("Вася", entity_type="person")
        assert len(result) == 1

    def test_get_all_entities(self, tmp_db):
        """Get all entities with call counts."""
        self._insert_call(tmp_db, "e1")
        self._insert_call(tmp_db, "e2")
        tmp_db.insert_entities("e1", [{"name": "Вася", "type": "person"}])
        tmp_db.insert_entities("e2", [{"name": "Вася", "type": "person"}])
        tmp_db.insert_entities("e2", [{"name": "Acme", "type": "company"}])
        result = tmp_db.get_all_entities()
        assert len(result) == 2
        # Вася appears in 2 calls
        vasya = next(r for r in result if r["name"] == "Вася")
        assert vasya["call_count"] == 2

    def test_entities_empty(self, tmp_db):
        """No entities returns empty list."""
        assert tmp_db.get_all_entities() == []
        assert tmp_db.get_entities("nonexistent") == []


# =============================================================================
# Chat Messages (6 tests)
# =============================================================================


class TestChatMessages:
    def _insert_call(self, db, session_id="cm1"):
        db.insert_call(
            session_id=session_id,
            app_name="Zoom",
            started_at="2025-02-20T10:00:00",
            ended_at="2025-02-20T10:30:00",
            duration_seconds=1800.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="Test",
            summary=None,
        )

    def test_insert_and_get_messages(self, tmp_db):
        """Insert messages and retrieve them in chronological order."""
        self._insert_call(tmp_db)
        tmp_db.insert_chat_message("cm1", "user", "What happened?", "call")
        tmp_db.insert_chat_message("cm1", "assistant", "Meeting about X.", "call")

        messages = tmp_db.get_chat_messages("cm1", "call")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Meeting about X."

    def test_get_messages_empty(self, tmp_db):
        """No messages returns empty list."""
        messages = tmp_db.get_chat_messages("nonexistent", "call")
        assert messages == []

    def test_global_messages(self, tmp_db):
        """Global scope messages are stored and retrieved."""
        tmp_db.insert_chat_message(None, "user", "Global Q", "global")
        tmp_db.insert_chat_message(None, "assistant", "Global A", "global")

        messages = tmp_db.get_chat_messages(None, "global")
        assert len(messages) == 2
        assert messages[0]["content"] == "Global Q"

    def test_clear_chat_per_session(self, tmp_db):
        """Clear chat removes messages for specific session."""
        self._insert_call(tmp_db, "cm1")
        self._insert_call(tmp_db, "cm2")
        tmp_db.insert_chat_message("cm1", "user", "Q1", "call")
        tmp_db.insert_chat_message("cm2", "user", "Q2", "call")

        tmp_db.clear_chat("cm1")
        assert tmp_db.get_chat_messages("cm1", "call") == []
        assert len(tmp_db.get_chat_messages("cm2", "call")) == 1

    def test_clear_global_chat(self, tmp_db):
        """Clear global chat removes only global messages."""
        self._insert_call(tmp_db)
        tmp_db.insert_chat_message("cm1", "user", "Per-call Q", "call")
        tmp_db.insert_chat_message(None, "user", "Global Q", "global")

        tmp_db.clear_chat()  # clears global
        assert tmp_db.get_chat_messages(None, "global") == []
        assert len(tmp_db.get_chat_messages("cm1", "call")) == 1

    def test_messages_limit(self, tmp_db):
        """Limit parameter works correctly."""
        self._insert_call(tmp_db)
        for i in range(10):
            tmp_db.insert_chat_message("cm1", "user", f"Q{i}", "call")

        messages = tmp_db.get_chat_messages("cm1", "call", limit=3)
        assert len(messages) == 3
        # Should be the most recent 3, in chronological order
        assert messages[-1]["content"] == "Q9"
