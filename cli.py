#!/usr/bin/env python3
"""Call Recorder — CLI interface."""

import json
import sys
from datetime import datetime

from src.database import Database


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso or "?"


def cmd_search(db: Database, args: list[str]):
    if not args:
        print("Usage: cli.py search <query>")
        sys.exit(1)

    query = " ".join(args)
    results = db.search(query)

    if not results:
        print(f"No results for: {query}")
        return

    print(f"Found {len(results)} result(s) for: {query}\n")
    for r in results:
        print(
            f"  {r['session_id']}  {r['app_name']:15s}  {fmt_date(r['started_at'])}  {fmt_duration(r['duration_seconds'])}"
        )
        if r.get("snippet"):
            print(f"    ...{r['snippet']}...")
        print()


def cmd_list(db: Database, args: list[str]):
    limit = int(args[0]) if args else 20
    calls = db.list_recent(limit)

    if not calls:
        print("No calls recorded yet.")
        return

    print(f"{'Session ID':20s}  {'App':15s}  {'Date':16s}  {'Duration':>8s}  Summary")
    print("-" * 90)
    for c in calls:
        summary_preview = ""
        if c.get("summary_json"):
            try:
                s = json.loads(c["summary_json"])
                summary_preview = (s.get("summary", ""))[:50]
            except (json.JSONDecodeError, TypeError):
                pass
        print(
            f"{c['session_id']:20s}  {c['app_name']:15s}  {fmt_date(c['started_at'])}  {fmt_duration(c['duration_seconds']):>8s}  {summary_preview}"
        )


def cmd_show(db: Database, args: list[str]):
    if not args:
        print("Usage: cli.py show <session_id>")
        sys.exit(1)

    call = db.get_call(args[0])
    if not call:
        print(f"Call not found: {args[0]}")
        sys.exit(1)

    print(f"Session:  {call['session_id']}")
    print(f"App:      {call['app_name']}")
    print(f"Started:  {fmt_date(call['started_at'])}")
    print(f"Ended:    {fmt_date(call['ended_at'])}")
    print(f"Duration: {fmt_duration(call['duration_seconds'])}")
    print(f"System:   {call.get('system_wav_path', 'N/A')}")
    print(f"Mic:      {call.get('mic_wav_path', 'N/A')}")
    print()

    if call.get("summary_json"):
        try:
            s = json.loads(call["summary_json"])
            print("=== SUMMARY ===")
            print(s.get("summary", ""))
            print()
            if s.get("key_points"):
                print("Key points:")
                for p in s["key_points"]:
                    print(f"  - {p}")
                print()
            if s.get("decisions"):
                print("Decisions:")
                for d in s["decisions"]:
                    print(f"  - {d}")
                print()
            if s.get("action_items"):
                print("Action items:")
                for a in s["action_items"]:
                    print(f"  [ ] {a}")
                print()
            if s.get("participants"):
                print(f"Participants: {', '.join(s['participants'])}")
                print()
        except (json.JSONDecodeError, TypeError):
            pass

    if call.get("transcript"):
        print("=== TRANSCRIPT ===")
        print(call["transcript"])


def cmd_actions(db: Database, args: list[str]):
    days = int(args[0]) if args else 7
    results = db.get_action_items(days)

    if not results:
        print(f"No action items in the last {days} days.")
        return

    print(f"Action items from the last {days} days:\n")
    for r in results:
        print(f"  {r['app_name']} — {fmt_date(r['started_at'])}")
        for item in r["action_items"]:
            print(f"    [ ] {item}")
        print()


def main():
    if len(sys.argv) < 2:
        print("Call Recorder CLI")
        print()
        print("Commands:")
        print("  search <query>     Full-text search across all calls")
        print("  list [N]           List recent calls (default: 20)")
        print("  show <session_id>  Show full details of a call")
        print("  actions [days]     Show action items (default: 7 days)")
        sys.exit(0)

    db = Database()
    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "search": cmd_search,
        "list": cmd_list,
        "show": cmd_show,
        "actions": cmd_actions,
    }

    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands)}")
        sys.exit(1)

    commands[cmd](db, args)


if __name__ == "__main__":
    main()
