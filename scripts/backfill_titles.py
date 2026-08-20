"""One-shot backfill: title + deadline_date for open commitment rows.

deadline_date is pure code (src.deadlines); the title goes through the live
Ollama (src.commitments2.normalize_title — model and URL live there). Existing
values are never overwritten, so reruns are idempotent and cheap.

Usage:
    .venv/bin/python scripts/backfill_titles.py --dry-run
    .venv/bin/python scripts/backfill_titles.py
"""

import argparse
import datetime
import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commitments2 import normalize_title  # noqa: E402
from src.database import Database  # noqa: E402
from src.deadlines import parse_deadline  # noqa: E402

print = functools.partial(print, flush=True)


def compute_deadline_date(row: dict) -> str | None:
    """deadline_raw first; the phrase usually lives inside the quote or text."""
    try:
        call_date = datetime.date.fromisoformat((row.get("started_at") or "")[:10])
    except ValueError:
        return None
    parsed = (
        parse_deadline(row.get("deadline_raw"), call_date)
        or parse_deadline(row.get("verbatim_quote"), call_date)
        or parse_deadline(row.get("text"), call_date)
    )
    return parsed.isoformat() if parsed else None


def plan_updates(rows: list[dict], title_fn=None) -> list[dict]:
    """One update per row; values already present are carried over untouched."""
    title_fn = title_fn or normalize_title
    updates = []
    for row in rows:
        title = row.get("title") or title_fn(
            row.get("verbatim_quote") or "", row.get("deadline_raw") or ""
        )
        deadline_date = row.get("deadline_date") or compute_deadline_date(row)
        updates.append(
            {"id": row["id"], "title": title, "deadline_date": deadline_date}
        )
    return updates


def apply_updates(db: Database, updates: list[dict]) -> int:
    with db._conn() as conn:
        conn.executemany(
            "UPDATE commitments SET title = ?, deadline_date = ? WHERE id = ?",
            [(u["title"], u["deadline_date"], u["id"]) for u in updates],
        )
    return len(updates)


def main(argv=None, title_fn=None):
    parser = argparse.ArgumentParser(
        description="Backfill title and deadline_date for open commitments"
    )
    parser.add_argument("--db", type=Path, default=None, help="database path")
    parser.add_argument(
        "--dry-run", action="store_true", help="print planned updates, write nothing"
    )
    args = parser.parse_args(argv)

    db = Database(db_path=args.db)
    updates = plan_updates(db.get_open_commitments(), title_fn=title_fn)
    for u in updates:
        print(
            f"  id={u['id']} deadline_date={u['deadline_date'] or '-'} "
            f"title={u['title'] or '-'}"
        )
    if args.dry_run:
        print(f"dry-run: {len(updates)} open row(s), nothing written")
        return
    apply_updates(db, updates)
    print(f"updated {len(updates)} open row(s)")


if __name__ == "__main__":
    main()
