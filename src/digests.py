"""Call Recorder — delivery artifacts: follow-up drafts and the morning digest.

Vohra's night-panel design: the follow-up is ready before you remember it
should exist — but nothing ever leaves the machine by itself. Files land in
~/call-recorder/digests/ (gitignored); sending is always the owner's hand.
"""

import json
import logging
import re
from datetime import datetime

from .config import DATA_DIR
from .database import Database  # noqa: F401 — typing/documentation

log = logging.getLogger("call-recorder")

DIGESTS_DIR = DATA_DIR.parent / "digests"

_TRAILER = (
    "---\n"
    "Черновик собран автоматически. Пункты без цитаты — не проверены, "
    "сверь перед отправкой."
)


def _strip_ts(item: str) -> str:
    return re.sub(r"^\[[\d:]+\]\s*", "", (item or "").strip())


def _slug(name: str) -> str:
    return re.sub(r"[^\wа-яё-]+", "-", (name or "").strip().lower()).strip("-")


def build_followup(db, session_id: str) -> tuple[str, str] | None:
    """Post-call follow-up draft for the call's main person.

    Returns (recipient_slug, markdown) or None when the call produced no
    substance (no decisions, no confident commitments) — an empty draft
    trains the owner to ignore notifications.
    """
    call = db.get_call(session_id)
    if not call:
        return None
    summary = {}
    if call.get("summary_json"):
        try:
            summary = json.loads(call["summary_json"])
        except (json.JSONDecodeError, TypeError):
            summary = {}

    decisions = [_strip_ts(d) for d in (summary.get("decisions") or []) if d]
    commitments = [c for c in db.get_commitments(session_id) if not c.get("uncertain")]
    outgoing = [c for c in commitments if c.get("direction") == "outgoing"]
    incoming = [c for c in commitments if c.get("direction") == "incoming"]

    if not decisions and not outgoing and not incoming:
        return None

    persons = [
        e["name"]
        for e in db.get_entities(session_id)
        if e.get("type") == "person" and not e["name"].upper().startswith("SPEAKER")
    ]
    recipient = persons[0] if persons else None
    date = (call.get("started_at") or "")[:10]

    lines = [f"# {recipient or 'Собеседник'} — {date}", ""]
    first_summary_line = (summary.get("summary") or "").strip().splitlines()
    if first_summary_line:
        lines += [first_summary_line[0], ""]

    if decisions:
        lines.append("## Договорились")
        lines += [f"- {d}" for d in decisions]
        lines.append("")

    def _block(title: str, items: list[dict]):
        if not items:
            return
        lines.append(title)
        for c in items:
            deadline = f" — к {c['deadline_raw']}" if c.get("deadline_raw") else ""
            lines.append(f"- {c.get('text') or ''}{deadline}")
            if c.get("verbatim_quote"):
                lines.append(f"  > {c['verbatim_quote']}")
        lines.append("")

    _block("## Беру на себя", outgoing)
    _block("## От тебя жду", incoming)
    lines.append(_TRAILER)

    return _slug(recipient or "собеседник"), "\n".join(lines)


def write_followup(db, session_id: str) -> str | None:
    """Render and write the follow-up draft; returns the path or None."""
    result = build_followup(db, session_id)
    if result is None:
        return None
    slug, md = result
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"{session_id}-followup-{slug}.md"
    path.write_text(md, encoding="utf-8")
    log.info(f"Follow-up draft written: {path}")
    return str(path)


def build_morning_digest(db, now: datetime | None = None) -> str:
    """Daily score of open obligations, sorted by activation energy.

    «Горит» = older than 7 days and still open (dateless debt rots silently —
    age is the honest trigger when deadline_raw is unparsed prose).
    """
    now = now or datetime.now()
    open_items = db.get_open_commitments()

    def _age_days(c) -> int | None:
        call = db.get_call(c.get("session_id") or "")
        started = (call or {}).get("started_at") or ""
        try:
            return (now - datetime.fromisoformat(started.replace("Z", ""))).days
        except ValueError:
            return None

    burning, outgoing, incoming = [], [], []
    for c in open_items:
        if c.get("uncertain"):
            continue
        age = _age_days(c)
        if age is not None and age > 7:
            burning.append((age, c))
        elif c.get("direction") == "outgoing":
            outgoing.append(c)
        elif c.get("direction") == "incoming":
            incoming.append(c)
    burning.sort(key=lambda t: -t[0])

    date_str = now.strftime("%Y-%m-%d")
    lines = [
        f"# {date_str} — {len(burning)} горит · {len(outgoing)} ты должен · "
        f"{len(incoming)} тебе должны",
        "",
    ]

    if burning:
        lines.append("## Горит (висит дольше недели)")
        for age, c in burning:
            who = c.get("who_name") or c.get("who_label") or ""
            lines.append(f"- {c.get('text') or ''} — {who}, звонок {age} дней назад")
            if c.get("verbatim_quote"):
                lines.append(f"  > {c['verbatim_quote']}")
        lines.append("")

    def _block(title: str, items: list[dict]):
        if not items:
            return
        lines.append(title)
        for c in items:
            who = c.get("who_name") or c.get("who_label") or ""
            deadline = f" — к {c['deadline_raw']}" if c.get("deadline_raw") else ""
            lines.append(f"- {c.get('text') or ''}{deadline} ({who})")
        lines.append("")

    _block("## Ты должен", outgoing)
    _block("## Тебе должны", incoming)

    if not burning and not outgoing and not incoming:
        lines.append(
            "Открытых обязательств не найдено — не значит, что их нет: "
            "извлечение покрывает не всё."
        )
        lines.append("")

    return "\n".join(lines)


def write_morning_digest(db, now: datetime | None = None) -> str:
    """Idempotent daily file: overwrites today's digest."""
    now = now or datetime.now()
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGESTS_DIR / f"{now.strftime('%Y-%m-%d')}-morning.md"
    path.write_text(build_morning_digest(db, now=now), encoding="utf-8")
    log.info(f"Morning digest written: {path}")
    return str(path)
