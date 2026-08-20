"""Stage-1 sweep: run find_candidates over every transcribed call in calls.db.

Pure-regex pass (src.commitments2.find_candidates, no LLM). Produces
eval/stage1-sweep.json: per-session candidate counts and density, plus a
summary used to calibrate the extraction canary threshold in src/daemon.py
(EXTRACTION_CANARY_MIN_SECONDS). Read-only on the database.
"""

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commitments2 import find_candidates  # noqa: E402
from src.config import DB_PATH  # noqa: E402
from src.summarizer import Summarizer  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "eval" / "stage1-sweep.json"

PERCENTILE_KEYS = (
    ("min", 0.0),
    ("p10", 0.10),
    ("p25", 0.25),
    ("median", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
    ("max", 1.0),
)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile over pre-sorted values."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def sweep(db_path: Path) -> dict:
    """Run stage 1 over every call with a non-empty transcript."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """SELECT session_id, app_name, duration_seconds, transcript
               FROM calls
               WHERE transcript IS NOT NULL
                 AND length(trim(transcript, ' ' || char(9) || char(10) || char(13))) > 0
               ORDER BY session_id"""
        ).fetchall()
    finally:
        conn.close()

    sessions = []
    for session_id, app_name, duration, transcript in rows:
        candidates = len(find_candidates(transcript))
        minutes = (duration or 0.0) / 60.0
        sessions.append(
            {
                "session_id": session_id,
                "app_name": app_name,
                "duration_seconds": duration,
                "transcript_lines": sum(
                    1 for l in transcript.splitlines() if l.strip()
                ),
                "candidates": candidates,
                "candidates_per_minute": (
                    round(candidates / minutes, 4) if minutes > 0 else 0.0
                ),
                "degenerate": Summarizer._is_degenerate(transcript),
            }
        )

    cpm = sorted(s["candidates_per_minute"] for s in sessions)
    summary = {
        "total_sessions": len(sessions),
        "degenerate_sessions": sum(1 for s in sessions if s["degenerate"]),
        "candidates_per_minute": {
            key: round(_percentile(cpm, q), 4) for key, q in PERCENTILE_KEYS
        },
        "zero_candidate_sessions": [
            {
                "session_id": s["session_id"],
                "app_name": s["app_name"],
                "duration_seconds": s["duration_seconds"],
                "degenerate": s["degenerate"],
            }
            for s in sessions
            if s["candidates"] == 0
        ],
    }
    return {
        "generated_at": date.today().isoformat(),
        "db_path": str(db_path),
        "sessions": sessions,
        "summary": summary,
    }


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    report = sweep(args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    s = report["summary"]
    print(
        f"sessions={s['total_sessions']} degenerate={s['degenerate_sessions']} "
        f"zero-candidate={len(s['zero_candidate_sessions'])}"
    )
    print(f"candidates_per_minute: {s['candidates_per_minute']}")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
