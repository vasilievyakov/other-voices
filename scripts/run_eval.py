"""Eval runner: fresh pipeline pass over recent live calls, metrics, LLM judge.

Usage:
    .venv/bin/python scripts/run_eval.py <cycle-name> [--sessions 8] [--judge 3]

Reads transcripts from calls.db, re-runs summarization through the CURRENT
pipeline (never writes to the database), applies src.evaluation metrics, and
asks qwen3:32b to judge grounding on a subset. Results: eval/<cycle-name>/.
"""

import argparse
import functools
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH, OLLAMA_BASE_URL  # noqa: E402
from src.evaluation import (  # noqa: E402
    coverage_correct,
    hallucinated_participants,
    owner_attestation,
    summary_shape,
)
from src.summarizer import Summarizer  # noqa: E402

print = functools.partial(print, flush=True)  # noqa: A001 — progress must stream

JUDGE_MODEL = "qwen3:32b"

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "grounded_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "ungrounded_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["grounded_score", "ungrounded_claims"],
}

JUDGE_PROMPT = """Ты — строгий проверяющий фактов. Ниже транскрипт звонка и \
JSON-саммари, построенное по нему. Найди утверждения саммари, которых НЕТ в \
транскрипте (выдуманные решения, задачи, имена, факты). Пустые списки — не \
ошибка. Поставь grounded_score: 5 = всё обосновано транскриптом, 1 = саммари \
в основном выдумано. Перечисли необоснованные утверждения дословно.

ТРАНСКРИПТ:
{transcript}

САММАРИ:
{summary}
"""


def judge_grounding(transcript: str, summary: dict) -> dict | None:
    payload = json.dumps(
        {
            "model": JUDGE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": JUDGE_PROMPT.format(
                        transcript=transcript[:12000],
                        summary=json.dumps(summary, ensure_ascii=False),
                    ),
                }
            ],
            "stream": False,
            "format": JUDGE_SCHEMA,
            "options": {"temperature": 0.0, "num_ctx": 32768},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return json.loads(result["message"]["content"])
    except Exception as e:
        print(f"  judge failed: {e}")
        return None


def pick_sessions(n: int) -> tuple[list[dict], int]:
    """Most recent live sessions with REAL content.

    Whisper-hallucination loops (degenerate transcripts) are excluded — the
    cycle-1 baseline accidentally measured the same artifact 8 times. Returns
    (sessions, degenerate_skipped).
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT session_id, app_name, transcript FROM calls
           WHERE source = 'live' AND transcript IS NOT NULL
             AND length(transcript) >= 500
           ORDER BY session_id DESC""",
    ).fetchall()
    conn.close()
    picked: list[dict] = []
    degenerate = 0
    for sid, app, t in rows:
        if Summarizer._is_degenerate(t):
            degenerate += 1
            continue
        if len(picked) < n:
            picked.append({"session_id": sid, "app_name": app, "transcript": t})
    return picked, degenerate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cycle")
    parser.add_argument("--sessions", type=int, default=8)
    parser.add_argument("--judge", type=int, default=3)
    args = parser.parse_args()

    out_dir = Path(__file__).resolve().parent.parent / "eval" / args.cycle
    out_dir.mkdir(parents=True, exist_ok=True)

    sessions, degenerate_skipped = pick_sessions(args.sessions)
    print(
        f"Evaluating {len(sessions)} sessions "
        f"({degenerate_skipped} degenerate skipped) → {out_dir}"
    )

    summarizer = Summarizer()
    results = []
    for i, s in enumerate(sessions):
        t0 = time.monotonic()
        summary = summarizer.summarize(s["transcript"])
        elapsed = time.monotonic() - t0
        entry = {
            "session_id": s["session_id"],
            "app_name": s["app_name"],
            "transcript_chars": len(s["transcript"]),
            "seconds": round(elapsed, 1),
            "shape": summary_shape(summary),
        }
        if summary:
            entry["owner_attestation"] = owner_attestation(summary, s["transcript"])
            entry["hallucinated_participants"] = hallucinated_participants(
                summary, s["transcript"]
            )
            entry["coverage_correct"] = coverage_correct(summary, s["transcript"])
            if i < args.judge:
                entry["judge"] = judge_grounding(s["transcript"], summary)
            (out_dir / f"{s['session_id']}.summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        results.append(entry)
        print(
            f"  [{i + 1}/{len(sessions)}] {s['session_id']} "
            f"{entry['seconds']}s failed={entry['shape'].get('failed')}"
        )

    ok = [r for r in results if not r["shape"].get("failed")]
    judged = [r for r in ok if r.get("judge")]
    aggregate = {
        "degenerate_skipped": degenerate_skipped,
        "sessions": len(results),
        "failed": len(results) - len(ok),
        "repaired": sum(1 for r in ok if r["shape"].get("repaired")),
        "coverage_correct": sum(1 for r in ok if r.get("coverage_correct")),
        "owner_items_total": sum(
            r["owner_attestation"]["with_owner"] for r in ok if "owner_attestation" in r
        ),
        "owner_items_attested": sum(
            r["owner_attestation"]["attested"] for r in ok if "owner_attestation" in r
        ),
        "sessions_with_hallucinated_participants": sum(
            1 for r in ok if r.get("hallucinated_participants")
        ),
        "judge_scores": [r["judge"]["grounded_score"] for r in judged],
        "avg_seconds": round(
            sum(r["seconds"] for r in results) / max(len(results), 1), 1
        ),
    }
    report = {"aggregate": aggregate, "sessions": results}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(aggregate, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
