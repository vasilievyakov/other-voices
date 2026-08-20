"""Blind precision audit for the commitments table.

Usage:
  .venv/bin/python scripts/audit_commitments.py           # export open rows
  .venv/bin/python scripts/audit_commitments.py --all     # export open + dismissed
  .venv/bin/python scripts/audit_commitments.py --score   # score the marked-up file

Export shuffles rows deterministically (seed 42) and hides direction, status,
uncertain flag and session_id from the reviewer — row identity lives only in
HTML comments, so the verdict cannot be biased by extraction metadata.
Dismissed rows are auditable too: they are the extractor's product no less
than open ones. Read-only: the database is never written.
"""

import argparse
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH  # noqa: E402

AUDIT_PATH = Path(__file__).resolve().parent.parent / "eval" / "precision-audit.md"
SEED = 42

_INSTRUCTIONS = (
    "---\n"
    "Разметка владельцем: в каждом блоке замени подчёркивание в строке «Вердикт».\n"
    "Вердикт: + реальное обязательство, - мусор (обрывок ASR, не обязательство, "
    "дубль).\n"
    "Затем: .venv/bin/python scripts/audit_commitments.py --score\n"
)

_VERDICT_RE = re.compile(r"<!-- id:(\d+)[^>]*-->.*?Вердикт:\s*([^\n]*)", re.S)


def fetch_commitments(db_path, include_dismissed: bool = False) -> list[dict]:
    statuses = ("open", "dismissed") if include_dismissed else ("open",)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT cm.id, cm.session_id, cm.text, cm.verbatim_quote,
                       cm.uncertain, cm.status, c.started_at
                FROM commitments cm
                JOIN calls c ON c.session_id = cm.session_id
                WHERE cm.status IN ({",".join("?" * len(statuses))})
                ORDER BY cm.id""",
            statuses,
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def build_audit_md(rows: list[dict]) -> str:
    shuffled = list(rows)
    random.Random(SEED).shuffle(shuffled)
    lines = []
    for n, r in enumerate(shuffled, 1):
        lines += [
            f"## {n} <!-- id:{r['id']} session:{r['session_id']} "
            f"status:{r['status']} -->",
            f"Цитата: «{r.get('verbatim_quote') or '—'}»",
            f"Текст: {r.get('text') or ''}",
            f"Дата звонка: {(r.get('started_at') or '')[:10]}",
            "Вердикт: _",
            "",
        ]
    lines.append(_INSTRUCTIONS)
    return "\n".join(lines)


def parse_verdicts(md: str) -> dict[int, str]:
    """Map row id -> '+', '-' or '' (unmarked). First mark character wins,
    so annotations like «- дубль» still count."""
    verdicts = {}
    for row_id, raw in _VERDICT_RE.findall(md):
        mark = raw.strip()[:1]
        verdicts[int(row_id)] = mark if mark in "+-" else ""
    return verdicts


def score_verdicts(verdicts: dict[int, str], rows: list[dict]) -> dict:
    by_id = {r["id"]: r for r in rows}

    def _bucket(ids):
        marked = [i for i in ids if verdicts.get(i) in ("+", "-")]
        positive = sum(1 for i in marked if verdicts[i] == "+")
        precision = round(positive / len(marked), 3) if marked else None
        return len(marked), precision

    known = [i for i in verdicts if i in by_id]
    marked, precision = _bucket(known)
    confident_marked, confident_precision = _bucket(
        [i for i in known if not by_id[i].get("uncertain")]
    )
    uncertain_marked, uncertain_precision = _bucket(
        [i for i in known if by_id[i].get("uncertain")]
    )
    open_marked, open_precision = _bucket(
        [i for i in known if by_id[i].get("status") == "open"]
    )
    return {
        "marked": marked,
        "unmarked": len(known) - marked,
        "precision": precision,
        "confident_marked": confident_marked,
        "confident_precision": confident_precision,
        "uncertain_marked": uncertain_marked,
        "uncertain_precision": uncertain_precision,
        "open_marked": open_marked,
        "open_precision": open_precision,
    }


def export(include_dismissed: bool = False):
    rows = fetch_commitments(DB_PATH, include_dismissed=include_dismissed)
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(build_audit_md(rows), encoding="utf-8")
    print(f"{AUDIT_PATH}: {len(rows)} строк на разметку")


def score():
    if not AUDIT_PATH.exists():
        print(f"Нет файла {AUDIT_PATH} — сначала запусти экспорт.")
        sys.exit(1)
    rows = fetch_commitments(DB_PATH, include_dismissed=True)
    verdicts = parse_verdicts(AUDIT_PATH.read_text(encoding="utf-8"))
    orphans = [i for i in verdicts if i not in {r["id"] for r in rows}]
    if orphans:
        print(f"Не найдены в базе (пропущены): {sorted(orphans)}")
    result = score_verdicts(verdicts, rows)

    def _fmt(p):
        return "n/a" if p is None else f"{p:.3f}"

    print(f"Размечено: {result['marked']} из {result['marked'] + result['unmarked']}")
    if result["unmarked"]:
        print(f"Пропущено: {result['unmarked']} — precision посчитан по размеченным")
    print(f"Precision общий: {_fmt(result['precision'])} ({result['marked']} строк)")
    print(
        f"Precision уверенные: {_fmt(result['confident_precision'])} "
        f"({result['confident_marked']} строк)"
    )
    print(
        f"Precision uncertain: {_fmt(result['uncertain_precision'])} "
        f"({result['uncertain_marked']} строк)"
    )
    print(
        f"Precision open-подмножество: {_fmt(result['open_precision'])} "
        f"({result['open_marked']} строк)"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", action="store_true")
    parser.add_argument(
        "--all", action="store_true", help="включить dismissed-строки в экспорт"
    )
    args = parser.parse_args()
    score() if args.score else export(include_dismissed=args.all)


if __name__ == "__main__":
    main()
