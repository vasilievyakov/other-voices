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
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso or "?"


def cmd_search(db: Database, args: list[str]):
    # Check for entity flags
    person = None
    company = None
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--person" and i + 1 < len(args):
            person = args[i + 1]
            i += 2
        elif args[i] == "--company" and i + 1 < len(args):
            company = args[i + 1]
            i += 2
        else:
            remaining.append(args[i])
            i += 1

    if person:
        results = db.get_calls_by_entity(person, entity_type="person")
        if not results:
            print(f"No calls found for person: {person}")
            return
        print(f"Calls mentioning {person}:\n")
        for r in results:
            print(
                f"  {r['session_id']}  {r['app_name']:15s}  {fmt_date(r['started_at'])}  {fmt_duration(r['duration_seconds'])}"
            )
        return

    if company:
        results = db.get_calls_by_entity(company, entity_type="company")
        if not results:
            print(f"No calls found for company: {company}")
            return
        print(f"Calls mentioning {company}:\n")
        for r in results:
            print(
                f"  {r['session_id']}  {r['app_name']:15s}  {fmt_date(r['started_at'])}  {fmt_duration(r['duration_seconds'])}"
            )
        return

    if not remaining:
        print("Usage: cli.py search <query>")
        print("       cli.py search --person <name>")
        print("       cli.py search --company <name>")
        sys.exit(1)

    query = " ".join(remaining)
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
    print(f"Template: {call.get('template_name', 'default')}")
    print(f"System:   {call.get('system_wav_path', 'N/A')}")
    print(f"Mic:      {call.get('mic_wav_path', 'N/A')}")
    print()

    if call.get("notes"):
        print("=== NOTES ===")
        print(call["notes"])
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

    # Show entities
    entities = db.get_entities(call["session_id"])
    if entities:
        people = [e["name"] for e in entities if e["type"] == "person"]
        companies = [e["name"] for e in entities if e["type"] == "company"]
        if people:
            print(f"People: {', '.join(people)}")
        if companies:
            print(f"Companies: {', '.join(companies)}")
        print()

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


def cmd_entities(db: Database, args: list[str]):
    """List all entities across calls."""
    entities = db.get_all_entities()
    if not entities:
        print("No entities found.")
        return

    people = [e for e in entities if e["type"] == "person"]
    companies = [e for e in entities if e["type"] == "company"]

    if people:
        print("People:")
        for e in people:
            print(
                f"  {e['name']} ({e['call_count']} call{'s' if e['call_count'] > 1 else ''})"
            )
        print()

    if companies:
        print("Companies:")
        for e in companies:
            print(
                f"  {e['name']} ({e['call_count']} call{'s' if e['call_count'] > 1 else ''})"
            )


def main():
    if len(sys.argv) < 2:
        print("Call Recorder CLI")
        print()
        print("Commands:")
        print("  search <query>              Full-text search across all calls")
        print("  search --person <name>      Find calls mentioning a person")
        print("  search --company <name>     Find calls mentioning a company")
        print("  list [N]                    List recent calls (default: 20)")
        print("  show <session_id>           Show full details of a call")
        print("  actions [days]              Show action items (default: 7 days)")
        print("  entities                    List all people and companies")
        sys.exit(0)

    db = Database()
    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "search": cmd_search,
        "list": cmd_list,
        "show": cmd_show,
        "actions": cmd_actions,
        "entities": cmd_entities,
    }

    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands)}")
        sys.exit(1)

    commands[cmd](db, args)


if __name__ == "__main__":
    main()
