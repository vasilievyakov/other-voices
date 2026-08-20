"""Dry-run of closure detection over the live database — strictly read-only.

Usage:
  .venv/bin/python scripts/closures_dryrun.py [path/to/calls.db]

Prints every proposed pair (open promise + later fulfilment evidence, both
quotes) and proves with a before/after snapshot of the commitments table
that nothing was written. Closing stays the owner's hand.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.closures import build_closure_proposals  # noqa: E402
from src.config import DB_PATH  # noqa: E402
from src.database import Database  # noqa: E402


def _snapshot(db_path: Path) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute("SELECT * FROM commitments ORDER BY id").fetchall()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    db = Database(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        calls_total = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        open_total = conn.execute(
            "SELECT COUNT(*) FROM commitments WHERE status = 'open'"
        ).fetchone()[0]

    before = _snapshot(db_path)
    proposals = build_closure_proposals(db)
    after = _snapshot(db_path)

    print(
        f"База: {db_path} — {calls_total} звонков, {open_total} открытых обязательств"
    )
    print()
    if not proposals:
        print("Пар не найдено — честный ноль.")
    for p in proposals:
        print(f"[{p['commitment_id']}] {p['commitment_text']}")
        print(f"  обещание:      «{p['commitment_quote']}»")
        print(
            f"  свидетельство: «{p['evidence_quote']}» "
            f"({p['evidence_date']}, звонок {p['evidence_session_id']})"
        )
        print()
    print(f"Итого пар: {len(proposals)}")

    if before != after:
        print("ВНИМАНИЕ: таблица commitments изменилась во время прогона!")
        return 1
    print("БД не изменена (снимок таблицы commitments до/после совпал).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
