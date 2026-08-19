"""One-shot backfill: run commitment extraction v2 over historical calls.

Reads transcripts (never modifies calls), writes ONLY the commitments table.
Sessions already having commitment rows are skipped (idempotent).
"""

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commitments2 import extract_commitments  # noqa: E402
from src.database import Database  # noqa: E402
from src.summarizer import Summarizer  # noqa: E402

print = functools.partial(print, flush=True)


def main():
    db = Database()
    with db._conn() as conn:
        rows = conn.execute(
            """SELECT session_id, transcript FROM calls
               WHERE source = 'live' AND transcript IS NOT NULL
                 AND length(transcript) >= 500
               ORDER BY session_id"""
        ).fetchall()

    done = skipped = degenerate = total_commitments = 0
    for sid, transcript in rows:
        if db.get_commitments(sid):
            skipped += 1
            continue
        if Summarizer._is_degenerate(transcript):
            degenerate += 1
            continue
        items = extract_commitments(transcript)
        if items:
            db.insert_commitments(sid, items)
            total_commitments += len(items)
        done += 1
        print(f"  {sid}: {len(items)} commitment(s)")

    print(
        f"done={done} skipped(existing)={skipped} degenerate={degenerate} "
        f"commitments_written={total_commitments}"
    )


if __name__ == "__main__":
    main()
