#!/usr/bin/env python3
"""Normalize summary_json format across all calls.

Fixes:
- summary field as dict → extract text, flatten nested fields to top level
- Embedded JSON strings → parse and re-serialize
- Missing standard fields → leave as-is (Swift decoder handles gracefully)

Usage:
    python fix_summaries.py [--dry-run]
"""

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / "call-recorder" / "data" / "calls.db"


def normalize_summary(summary_json: str) -> tuple[str, list[str]]:
    """Normalize a summary_json string. Returns (normalized_json, list_of_changes)."""
    changes = []

    try:
        data = json.loads(summary_json)
    except (json.JSONDecodeError, TypeError):
        return summary_json, ["SKIP: invalid JSON"]

    if not isinstance(data, dict):
        return summary_json, ["SKIP: not a dict"]

    modified = False

    # Fix 1: summary is a nested dict
    if isinstance(data.get("summary"), dict):
        nested = data["summary"]
        changes.append(f"summary was dict with keys: {list(nested.keys())}")

        # Extract text from nested dict
        text = nested.get("summary") or nested.get("text") or nested.get("topic")
        if text and isinstance(text, str):
            data["summary"] = text
        else:
            # No text found — stringify it for display
            data["summary"] = json.dumps(nested, ensure_ascii=False, indent=2)

        # Promote nested list fields to top level
        for key in list(nested.keys()):
            if key in ("summary", "text", "topic"):
                continue
            value = nested[key]
            if key not in data:
                data[key] = value
                changes.append(f"promoted {key} from nested summary")

        modified = True

    # Fix 2: summary is an embedded JSON string
    if isinstance(data.get("summary"), str):
        s = data["summary"].strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                inner = json.loads(s)
                if isinstance(inner, dict):
                    changes.append("summary was embedded JSON string")
                    text = inner.get("summary") or inner.get("text")
                    if text:
                        data["summary"] = text
                    for key, value in inner.items():
                        if key not in ("summary", "text") and key not in data:
                            data[key] = value
                    modified = True
            except json.JSONDecodeError:
                pass

    if not modified:
        return summary_json, []

    return json.dumps(data, ensure_ascii=False), changes


def main():
    dry_run = "--dry-run" in sys.argv

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT session_id, summary_json FROM calls WHERE summary_json IS NOT NULL"
    ).fetchall()

    print(f"Found {len(rows)} calls with summary_json")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("-" * 60)

    fixed = 0
    skipped = 0

    for row in rows:
        sid = row["session_id"]
        original = row["summary_json"]
        normalized, changes = normalize_summary(original)

        if not changes:
            continue

        if any(c.startswith("SKIP") for c in changes):
            print(f"  {sid}: {changes[0]}")
            skipped += 1
            continue

        print(f"  {sid}:")
        for c in changes:
            print(f"    - {c}")

        if not dry_run:
            conn.execute(
                "UPDATE calls SET summary_json = ? WHERE session_id = ?",
                (normalized, sid),
            )

        fixed += 1

    if not dry_run and fixed > 0:
        # Rebuild FTS index after all updates
        conn.execute("INSERT INTO calls_fts(calls_fts) VALUES ('rebuild')")
        conn.commit()

    print("-" * 60)
    print(f"Fixed: {fixed}, Skipped: {skipped}")

    conn.close()


if __name__ == "__main__":
    main()
