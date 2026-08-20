"""Freeze the owner-curated commitments table into eval/regression-set.json.

The owner's hand is training data: every open row is a promise the owner
kept, every dismissed row is one the owner rejected. A later extractor run
must keep the former and must not resurrect the latter —
scripts/eval_commitments.py reads this snapshot and scores each run against
it (kept_open_rate / reproduced_dismissed_rate).

Read-only on the database (sqlite opened with mode=ro); writes only under
eval/.

Usage: .venv/bin/python scripts/freeze_regression_set.py
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "eval" / "regression-set.json"

FIELDS = (
    "id",
    "session_id",
    "text",
    "verbatim_quote",
    "direction",
    "uncertain",
    "status",
    "resolved_at",
)


def fetch_rows(db_path) -> list[dict]:
    """All commitment rows (any status) in id order, frozen fields only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {', '.join(FIELDS)} FROM commitments ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def freeze(db_path, out_path) -> dict:
    rows = fetch_rows(db_path)
    payload = {
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Owner-curated snapshot: open rows must be reproduced, "
            "dismissed rows must not be."
        ),
        "count": len(rows),
        "rows": rows,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot the commitments table into eval/regression-set.json"
    )
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()
    payload = freeze(args.db, args.out)
    by_status: dict[str, int] = {}
    for row in payload["rows"]:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    print(f"{args.out}: {payload['count']} rows {by_status}")


if __name__ == "__main__":
    main()
