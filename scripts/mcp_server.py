"""Read-only MCP server over the Other Voices call ledger (stdio).

Exposes search, call details, person briefs, the morning digest and open
commitments to MCP clients (Claude Code and friends). No write tools by
design: commitment statuses change only by the owner's hand in the app
or CLI — an LLM on the other end of this socket gets eyes, not hands.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.brief import build_brief, render_brief  # noqa: E402
from src.database import Database  # noqa: E402
from src.digests import build_morning_digest  # noqa: E402

DB_PATH = ROOT / "data" / "calls.db"

# Transcripts run long; cap what a single tool call feeds into a context.
TRANSCRIPT_CAP = 30_000


def search_calls(db, query: str, limit: int = 10) -> list[dict]:
    rows = db.search(query, limit=limit)
    return [
        {
            "session_id": r["session_id"],
            "app_name": r["app_name"],
            "started_at": r["started_at"],
            "duration_seconds": r["duration_seconds"],
            "snippet": r.get("snippet"),
        }
        for r in rows
    ]


def get_call(db, session_id: str) -> dict | None:
    call = db.get_call(session_id)
    if call is None:
        return None
    transcript = call.get("transcript") or ""
    truncated = len(transcript) > TRANSCRIPT_CAP
    summary = None
    if call.get("summary_json"):
        try:
            summary = json.loads(call["summary_json"])
        except (ValueError, TypeError):
            summary = None
    return {
        "session_id": call["session_id"],
        "app_name": call["app_name"],
        "started_at": call["started_at"],
        "duration_seconds": call["duration_seconds"],
        "summary": summary,
        "transcript": transcript[:TRANSCRIPT_CAP],
        "transcript_truncated": truncated,
        "notes": call.get("notes"),
    }


def person_brief(db, name: str) -> str:
    brief = build_brief(db, name)
    if brief is None:
        return f"По имени «{name}» разговоров не найдено."
    return render_brief(brief)


def morning_digest(db) -> str:
    return build_morning_digest(db)


def open_commitments(db, direction: str | None = None) -> list[dict]:
    return db.get_open_commitments(direction=direction)


def make_server(db):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="other-voices",
        instructions=(
            "Локальный архив звонков Other Voices: поиск, саммари, брифы по "
            "людям и реестр обязательств. Только чтение — статусы меняет "
            "владелец в приложении."
        ),
    )

    def _search_calls(query: str, limit: int = 10) -> list[dict]:
        """Полнотекстовый поиск по транскриптам и саммари звонков."""
        return search_calls(db, query, limit)

    def _get_call(session_id: str) -> dict | None:
        """Саммари, транскрипт и метаданные одного звонка по session_id."""
        return get_call(db, session_id)

    def _person_brief(name: str) -> str:
        """Бриф по человеку: долги в обе стороны, последний разговор."""
        return person_brief(db, name)

    def _morning_digest() -> str:
        """Утренний счет открытых обязательств."""
        return morning_digest(db)

    def _open_commitments(direction: str | None = None) -> list[dict]:
        """Открытые обязательства; direction: outgoing | incoming | пусто."""
        return open_commitments(db, direction)

    server.add_tool(_search_calls, name="search_calls")
    server.add_tool(_get_call, name="get_call")
    server.add_tool(_person_brief, name="person_brief")
    server.add_tool(_morning_digest, name="morning_digest")
    server.add_tool(_open_commitments, name="open_commitments")
    return server


if __name__ == "__main__":
    make_server(Database(db_path=DB_PATH)).run("stdio")
