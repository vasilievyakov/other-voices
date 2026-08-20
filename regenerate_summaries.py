#!/usr/bin/env python3
"""Re-generate all summaries using updated prompts.

Usage:
    python3 regenerate_summaries.py          # re-summarize all calls with transcript
    python3 regenerate_summaries.py --dry-run # show what would be done
    python3 regenerate_summaries.py --session 20260122_141359  # single call
"""

import json
import logging
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import DB_PATH
from src.summarizer import Summarizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("regenerate")


def main():
    dry_run = "--dry-run" in sys.argv
    single_session = None
    for i, arg in enumerate(sys.argv):
        if arg == "--session" and i + 1 < len(sys.argv):
            single_session = sys.argv[i + 1]

    if not DB_PATH.exists():
        log.error(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if single_session:
        rows = conn.execute(
            "SELECT session_id, app_name, transcript, template_name, notes, "
            "transcript_segments FROM calls WHERE session_id = ?",
            (single_session,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT session_id, app_name, transcript, template_name, notes, "
            "transcript_segments FROM calls WHERE transcript IS NOT NULL "
            "ORDER BY started_at"
        ).fetchall()

    total = len(rows)
    log.info(f"Found {total} calls to re-summarize" + (" (DRY RUN)" if dry_run else ""))

    summarizer = Summarizer()
    success = 0
    failed = 0

    for i, row in enumerate(rows, 1):
        sid = row["session_id"]
        app = row["app_name"]
        template = row["template_name"] or "default"
        transcript = row["transcript"]
        notes = row["notes"]

        # Parse segments if available
        segments = None
        if row["transcript_segments"]:
            try:
                segments = json.loads(row["transcript_segments"])
            except json.JSONDecodeError:
                pass

        log.info(f"[{i}/{total}] {sid} ({app}, template={template})")

        if dry_run:
            log.info(f"  Would re-summarize: {len(transcript)} chars")
            continue

        summary = summarizer.summarize(
            transcript,
            template_name=template,
            notes=notes,
            segments=segments,
        )

        if summary is None:
            log.warning(f"  FAILED: Ollama returned None")
            failed += 1
            continue

        summary_json = json.dumps(summary, ensure_ascii=False)

        conn.execute(
            "UPDATE calls SET summary_json = ? WHERE session_id = ?",
            (summary_json, sid),
        )
        conn.commit()

        # Show a preview
        title = summary.get("title", "NO TITLE")
        kp_count = len(summary.get("key_points", []))
        ai_count = len(summary.get("action_items", []))
        log.info(
            f"  OK: title='{title}', {kp_count} key_points, {ai_count} action_items"
        )
        success += 1

    conn.close()

    if not dry_run:
        log.info(f"\nDone: {success} succeeded, {failed} failed out of {total}")
    else:
        log.info(f"\nDry run complete: {total} calls would be re-summarized")


if __name__ == "__main__":
    main()
