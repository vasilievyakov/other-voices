"""Call Recorder — SQLite FTS5 database."""

import json
import logging
import sqlite3
from pathlib import Path

from .config import DB_PATH

log = logging.getLogger("call-recorder")

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
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
    notes TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS calls_fts USING fts5(
    session_id,
    app_name,
    transcript,
    summary_json,
    content='calls',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS calls_ai AFTER INSERT ON calls BEGIN
    INSERT INTO calls_fts(rowid, session_id, app_name, transcript, summary_json)
    VALUES (new.rowid, new.session_id, new.app_name, new.transcript, new.summary_json);
END;

CREATE TRIGGER IF NOT EXISTS calls_au AFTER UPDATE ON calls BEGIN
    INSERT INTO calls_fts(calls_fts, rowid, session_id, app_name, transcript, summary_json)
    VALUES ('delete', old.rowid, old.session_id, old.app_name, old.transcript, old.summary_json);
    INSERT INTO calls_fts(rowid, session_id, app_name, transcript, summary_json)
    VALUES (new.rowid, new.session_id, new.app_name, new.transcript, new.summary_json);
END;

CREATE TRIGGER IF NOT EXISTS calls_ad AFTER DELETE ON calls BEGIN
    INSERT INTO calls_fts(calls_fts, rowid, session_id, app_name, transcript, summary_json)
    VALUES ('delete', old.rowid, old.session_id, old.app_name, old.transcript, old.summary_json);
END;
"""


class Database:
    """SQLite database with FTS5 full-text search."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate_db(conn)
            log.info(f"Database initialized: {self.db_path}")

    def _migrate_db(self, conn: sqlite3.Connection):
        """Add columns and tables introduced in later phases (safe for existing DBs)."""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(calls)").fetchall()
        }
        if "template_name" not in columns:
            conn.execute(
                "ALTER TABLE calls ADD COLUMN template_name TEXT DEFAULT 'default'"
            )
        if "notes" not in columns:
            conn.execute("ALTER TABLE calls ADD COLUMN notes TEXT")
        if "transcript_segments" not in columns:
            conn.execute("ALTER TABLE calls ADD COLUMN transcript_segments TEXT")

        # Entities table (Phase 2)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT CHECK(type IN ('person','company')),
                session_id TEXT REFERENCES calls(session_id) ON DELETE CASCADE,
                UNIQUE(name, type, session_id)
            )
        """)

        # Chat messages table (Phase 6)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES calls(session_id),
                role TEXT CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                scope TEXT DEFAULT 'call' CHECK(scope IN ('call','global'))
            )
        """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def insert_call(
        self,
        session_id: str,
        app_name: str,
        started_at: str,
        ended_at: str,
        duration_seconds: float,
        system_wav_path: str | None,
        mic_wav_path: str | None,
        transcript: str | None,
        summary: dict | None,
        template_name: str = "default",
        notes: str | None = None,
        transcript_segments: str | None = None,
    ):
        """Insert a call record."""
        summary_json = json.dumps(summary, ensure_ascii=False) if summary else None

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO calls
                   (session_id, app_name, started_at, ended_at, duration_seconds,
                    system_wav_path, mic_wav_path, transcript, summary_json,
                    template_name, notes, transcript_segments)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    app_name,
                    started_at,
                    ended_at,
                    duration_seconds,
                    system_wav_path,
                    mic_wav_path,
                    transcript,
                    summary_json,
                    template_name,
                    notes,
                    transcript_segments,
                ),
            )
        log.info(f"Saved call {session_id} to database")

    def update_notes(self, session_id: str, notes: str | None):
        """Update user notes for a call."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE calls SET notes = ? WHERE session_id = ?",
                (notes, session_id),
            )

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across transcripts and summaries."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.session_id, c.app_name, c.started_at, c.duration_seconds,
                          c.transcript, c.summary_json, c.template_name, c.notes,
                          snippet(calls_fts, 2, '>>>', '<<<', '...', 40) AS snippet
                   FROM calls_fts fts
                   JOIN calls c ON c.rowid = fts.rowid
                   WHERE calls_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_recent(self, limit: int = 20) -> list[dict]:
        """List most recent calls."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT session_id, app_name, started_at, ended_at, duration_seconds,
                          summary_json, template_name, notes
                   FROM calls
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_call(self, session_id: str) -> dict | None:
        """Get full details of a specific call."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM calls WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    # --- Entities ---

    def insert_entities(self, session_id: str, entities: list[dict]):
        """Insert entities extracted from a call. Each entity: {name, type}."""
        with self._conn() as conn:
            for entity in entities:
                name = entity.get("name", "").strip()
                etype = entity.get("type", "")
                if not name or etype not in ("person", "company"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO entities (name, type, session_id) VALUES (?, ?, ?)",
                    (name, etype, session_id),
                )

    def get_entities(self, session_id: str) -> list[dict]:
        """Get all entities for a specific call."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, type FROM entities WHERE session_id = ? ORDER BY type, name",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_entities(self, query: str) -> list[dict]:
        """Search entities by name (partial match)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name, type FROM entities WHERE name LIKE ? ORDER BY name",
                (f"%{query}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_calls_by_entity(
        self, name: str, entity_type: str | None = None
    ) -> list[dict]:
        """Get all calls that mention a specific entity."""
        with self._conn() as conn:
            if entity_type:
                rows = conn.execute(
                    """SELECT c.* FROM calls c
                       JOIN entities e ON e.session_id = c.session_id
                       WHERE e.name = ? AND e.type = ?
                       ORDER BY c.started_at DESC""",
                    (name, entity_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT c.* FROM calls c
                       JOIN entities e ON e.session_id = c.session_id
                       WHERE e.name = ?
                       ORDER BY c.started_at DESC""",
                    (name,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_all_entities(self) -> list[dict]:
        """Get all unique entities with call counts."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT name, type, COUNT(DISTINCT session_id) as call_count
                   FROM entities
                   GROUP BY name, type
                   ORDER BY call_count DESC, name""",
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Chat Messages ---

    def insert_chat_message(
        self,
        session_id: str | None,
        role: str,
        content: str,
        scope: str = "call",
    ):
        """Insert a chat message."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content, scope) VALUES (?, ?, ?, ?)",
                (session_id, role, content, scope),
            )

    def get_chat_messages(
        self,
        session_id: str | None,
        scope: str = "call",
        limit: int = 20,
    ) -> list[dict]:
        """Get chat history for a call or globally."""
        with self._conn() as conn:
            if scope == "call" and session_id:
                rows = conn.execute(
                    """SELECT role, content, created_at FROM chat_messages
                       WHERE session_id = ? AND scope = 'call'
                       ORDER BY id DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT role, content, created_at FROM chat_messages
                       WHERE scope = 'global'
                       ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        # Return in chronological order (oldest first)
        return [dict(r) for r in reversed(rows)]

    def clear_chat(self, session_id: str | None = None):
        """Clear chat history for a call or all global chats."""
        with self._conn() as conn:
            if session_id:
                conn.execute(
                    "DELETE FROM chat_messages WHERE session_id = ?",
                    (session_id,),
                )
            else:
                conn.execute("DELETE FROM chat_messages WHERE scope = 'global'")

    def get_action_items(self, days: int = 7) -> list[dict]:
        """Get all action items from calls in the last N days."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT session_id, app_name, started_at, summary_json
                   FROM calls
                   WHERE summary_json IS NOT NULL
                     AND started_at >= datetime('now', ?)
                   ORDER BY started_at DESC""",
                (f"-{days} days",),
            ).fetchall()

        results = []
        for row in rows:
            row_dict = dict(row)
            try:
                summary = json.loads(row_dict["summary_json"])
                items = summary.get("action_items", [])
                if items:
                    results.append(
                        {
                            "session_id": row_dict["session_id"],
                            "app_name": row_dict["app_name"],
                            "started_at": row_dict["started_at"],
                            "action_items": items,
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                continue
        return results
