"""Call Recorder — pre-meeting briefs (local Granola-style Briefs).

Pure logic between bin/calendar-peek and the daemon: parse the helper's JSON,
pick events starting in a few minutes, and assemble a short note on each
participant's standing (debts both ways + days since last talk) from the
call database. The daemon polls, dedups and notifies; nothing here talks to
the network or the calendar itself.
"""

import json
from datetime import datetime

from .brief import _days_phrase, build_brief
from .digests import DIGESTS_DIR, _slug


def parse_peek_output(raw: str) -> list[dict] | None:
    """Parse bin/calendar-peek stdout into a list of event dicts.

    Returns None on anything that is not a JSON array (the helper's
    {"error": "no-access"} included) — the caller must treat None as
    «календаря сегодня нет», not as an empty day.
    """
    try:
        data = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None

    events = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("id") or not item.get("start"):
            continue
        events.append(
            {
                "id": str(item["id"]),
                "title": str(item.get("title") or ""),
                "start": str(item["start"]),
                "attendees": [
                    a for a in (item.get("attendees") or []) if isinstance(a, str)
                ],
            }
        )
    return events


def _parse_start(raw: str, ref: datetime) -> datetime | None:
    """Parse an ISO start into ref's frame (naive local vs tz-aware).

    calendar-peek emits UTC Z-timestamps while the daemon lives in naive
    local time — comparing them directly would either crash or shift the
    window by the UTC offset.
    """
    try:
        dt = datetime.fromisoformat((raw or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is not None and ref.tzinfo is None:
        return dt.astimezone().replace(tzinfo=None)
    if dt.tzinfo is None and ref.tzinfo is not None:
        return dt.replace(tzinfo=ref.tzinfo)
    return dt


def upcoming_window(
    events: list[dict],
    now: datetime,
    lead_min: int = 12,
    min_lead_min: int = 3,
) -> list[dict]:
    """Events starting in [min_lead_min, lead_min] minutes from now.

    The lower bound keeps us from notifying about a meeting the owner is
    already joining; the upper bound matches the ~2-minute poll so every
    meeting gets exactly one chance to fire.
    """
    picked = []
    for event in events:
        start = _parse_start(event.get("start"), now)
        if start is None:
            continue
        lead = (start - now).total_seconds() / 60
        if min_lead_min <= lead <= lead_min:
            picked.append(event)
    return picked


def event_key(event: dict) -> str:
    """Dedup key: recurring events share an id, so the start participates."""
    return f"{event.get('id')}|{event.get('start')}"


def build_premeeting_note(db, event: dict) -> tuple[str, str] | None:
    """Assemble (title, body) for a pre-meeting note.

    One line per attendee: debt counters + days since the last call when the
    person is in the database, «истории нет» when not. Returns None when
    there is nobody to brief about (no attendees) or the start is garbage.
    """
    attendees = event.get("attendees") or []
    if not attendees:
        return None
    start = _parse_start(event.get("start"), datetime.now())
    if start is None:
        return None

    event_title = (event.get("title") or "").strip()
    hhmm = start.strftime("%H:%M")
    title = f"Встреча {event_title} в {hhmm}" if event_title else f"Встреча в {hhmm}"

    lines = [f"# {title}", ""]
    for name in attendees:
        brief = build_brief(db, name)
        if brief is None:
            lines.append(f"{name}: истории нет")
            continue
        lines.append(
            f"{name}: должен {len(brief['outgoing'])} / "
            f"тебе должны {len(brief['incoming'])}, "
            f"последний разговор {_days_phrase(brief['days_since_contact'])}"
        )
    return title, "\n".join(lines)


def write_premeeting_note(db, event: dict) -> tuple[str, str] | None:
    """Render and write the note; returns (path, title) or None."""
    result = build_premeeting_note(db, event)
    if result is None:
        return None
    title, body = result
    start = _parse_start(event.get("start"), datetime.now())
    date = start.strftime("%Y-%m-%d")
    slug = _slug(event.get("title") or "встреча")
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"premeet-{date}-{slug}.md"
    path.write_text(body, encoding="utf-8")
    return str(path), title
