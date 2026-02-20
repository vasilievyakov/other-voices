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
    summary_json TEXT
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
            log.info(f"Database initialized: {self.db_path}")

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
    ):
        """Insert a call record."""
        summary_json = json.dumps(summary, ensure_ascii=False) if summary else None

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO calls
                   (session_id, app_name, started_at, ended_at, duration_seconds,
                    system_wav_path, mic_wav_path, transcript, summary_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
        log.info(f"Saved call {session_id} to database")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across transcripts and summaries."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.session_id, c.app_name, c.started_at, c.duration_seconds,
                          c.transcript, c.summary_json,
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
                          summary_json
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
