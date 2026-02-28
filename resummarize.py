"""Re-summarize calls in DB using Ollama.

Thin CLI wrapper around Summarizer.resummarize_single / resummarize_batch.

Usage:
    python resummarize.py                         # re-summarize all calls
    python resummarize.py --session <id>          # re-summarize a specific call
    python resummarize.py --session <id> --template <name>  # with template
    python resummarize.py --limit 10              # re-summarize first 10 calls
"""

import sys
import time
from pathlib import Path

from src.summarizer import Summarizer
from src.config import DB_PATH


def main():
    # Parse args
    args = sys.argv[1:]
    session_id = None
    template_name = "default"
    limit = None
    db_path = str(DB_PATH)

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--template" and i + 1 < len(args):
            template_name = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        else:
            i += 1

    summarizer = Summarizer()

    if session_id:
        print(f"Re-summarizing {session_id} with template={template_name}...", flush=True)
        t0 = time.time()
        result = summarizer.resummarize_single(session_id, db_path, template_name)
        elapsed = time.time() - t0

        if not result:
            print(f"FAILED ({elapsed:.1f}s)")
            sys.exit(1)

        ai_count = len(result.get("action_items", []))
        print(f"OK ({elapsed:.1f}s) — {ai_count} action items")
    else:
        print("Batch re-summarize...", flush=True)
        t0 = time.time()
        stats = summarizer.resummarize_batch(db_path, template_name, limit)
        elapsed = time.time() - t0

        print(
            f"\nDone ({elapsed:.1f}s): {stats['updated']}/{stats['total']} updated, "
            f"{stats['skipped']} skipped, {stats['failed']} failed"
        )


if __name__ == "__main__":
    main()
