"""Call Recorder — per-person briefing: the combine's first artifact.

build_brief() computes one shared model (Python CLI and the Swift app render
the same object); render_brief() turns it into markdown. Debt comes first,
the date is context for the debt, field names never leak to the reader.
"""

import json
import re
from datetime import datetime

from .evaluation import _name_present

# Board cycle 3 (Ive): the recipient of a commitment is rarely captured
# (to_whom is almost always null), so outgoing items are honestly labeled
# «обещано в разговоре с X», never «ты должен X» without evidence.


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0][:200] if text else ""


def _strip_ts(item: str) -> str:
    return re.sub(r"^\[[\d:]+\]\s*", "", (item or "").strip())


def build_brief(db, name: str, now: datetime | None = None) -> dict | None:
    """One person's standing: open obligations both ways + recent context."""
    now = now or datetime.now()
    calls = db.get_calls_by_entity(name, entity_type="person")
    if not calls:
        return None

    last_started = calls[0].get("started_at") or ""
    days_since = None
    try:
        last_dt = datetime.fromisoformat(last_started.replace("Z", ""))
        days_since = max(0, (now - last_dt).days)
    except ValueError:
        pass

    call_dates = {c["session_id"]: (c.get("started_at") or "")[:10] for c in calls}

    outgoing: list[dict] = []
    incoming: list[dict] = []
    unconfirmed: list[dict] = []
    for c_row in calls:
        for c in db.get_commitments(c_row["session_id"]):
            if c.get("status") != "open":
                continue
            entry = {
                "what": c.get("text") or "",
                "deadline": c.get("deadline_raw"),
                "quote": c.get("verbatim_quote"),
                "session_id": c["session_id"],
                "date": call_dates.get(c["session_id"], ""),
            }
            # Uncertain extraction never mixes into the debt counters —
            # a confident number over shaky data is a polite lie (board rule).
            if c.get("uncertain"):
                unconfirmed.append(entry)
                continue
            direction = c.get("direction")
            if direction == "outgoing":
                outgoing.append(entry)
            elif direction == "incoming":
                committer = " ".join(
                    str(x) for x in (c.get("who_label"), c.get("who_name")) if x
                )
                if _name_present(name, committer):
                    incoming.append(entry)

    recent = []
    for c_row in calls[:3]:
        summary = {}
        if c_row.get("summary_json"):
            try:
                summary = json.loads(c_row["summary_json"])
            except (json.JSONDecodeError, TypeError):
                summary = {}
        recent.append(
            {
                "date": call_dates.get(c_row["session_id"], ""),
                "summary": _first_line(summary.get("summary")),
                "decisions": [_strip_ts(d) for d in (summary.get("decisions") or [])],
            }
        )

    return {
        "name": name,
        "last_contact": last_started,
        "days_since_contact": days_since,
        "calls_count": len(calls),
        "outgoing": outgoing,
        "incoming": incoming,
        "unconfirmed": unconfirmed,
        "recent": recent,
    }


def _days_phrase(days: int | None) -> str:
    if days is None:
        return "дата неизвестна"
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день назад"
    if days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        return f"{days} дня назад"
    return f"{days} дней назад"


def render_brief(brief: dict) -> str:
    """Markdown a person brief: debt first, human words, no raw fields."""
    name = brief["name"]
    header = (
        f"# {name} — должен: {len(brief['outgoing'])} · "
        f"тебе должны: {len(brief['incoming'])} · "
        f"последний разговор: {_days_phrase(brief['days_since_contact'])}"
    )
    if brief.get("unconfirmed"):
        header += f" · нужно подтвердить: {len(brief['unconfirmed'])}"
    lines = [header, ""]

    if brief["outgoing"]:
        lines.append(f"## Ты обещал (в разговорах с {name})")
        for c in brief["outgoing"]:
            deadline = f" — к сроку: {c['deadline']}" if c.get("deadline") else ""
            lines.append(f"- {c['what']}{deadline} (звонок {c['date']})")
            if c.get("quote"):
                lines.append(f"  > {c['quote']}")
        lines.append("")

    if brief["incoming"]:
        lines.append("## Тебе обещали")
        for c in brief["incoming"]:
            deadline = f" — к сроку: {c['deadline']}" if c.get("deadline") else ""
            lines.append(f"- {c['what']}{deadline} (звонок {c['date']})")
            if c.get("quote"):
                lines.append(f"  > {c['quote']}")
        lines.append("")

    if brief.get("unconfirmed"):
        lines.append("## Нужно подтвердить (извлечено с низкой уверенностью)")
        for c in brief["unconfirmed"]:
            lines.append(f"- {c['what']} (звонок {c['date']})")
            if c.get("quote"):
                lines.append(f"  > {c['quote']}")
        lines.append("")

    if not brief["outgoing"] and not brief["incoming"]:
        lines.append(
            "Открытых обязательств не найдено — не значит, что их не было: "
            "извлечение покрывает не всё."
        )
        lines.append("")

    lines.append("## О чём говорили в последний раз")
    for r in brief["recent"]:
        if r["summary"]:
            lines.append(f"- {r['date']} — {r['summary']}")
        for d in r["decisions"]:
            lines.append(f"  - решение: {d}")

    return "\n".join(lines)
