"""Re-summarize calls in DB using Ollama.

Usage:
    python resummarize.py                         # re-summarize all calls
    python resummarize.py --session <id>          # re-summarize a specific call
    python resummarize.py --session <id> --template <name>  # with template
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Use the project's template system when available
try:
    from src.templates import build_prompt
    from src.config import OLLAMA_URL, OLLAMA_MODEL
except ImportError:
    build_prompt = None
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "qwen2.5:7b"

DB_PATH = Path.home() / "call-recorder" / "data" / "calls.db"
MAX_CHARS = 12000

SUMMARY_PROMPT = """\
Ты анализируешь транскрипт звонка. Извлеки структурированную информацию.

Ответь строго в JSON формате (без markdown):
{
  "summary": "краткое описание звонка в 2-3 предложения",
  "key_points": ["ключевой момент 1", "ключевой момент 2"],
  "decisions": ["решение 1", "решение 2"],
  "action_items": ["задача 1 (@кто, дедлайн если есть)", "задача 2"],
  "participants": ["имя1", "имя2"]
}

Если какое-то поле не определяется из транскрипта, используй пустой список [].
Отвечай на том же языке, что и транскрипт.

ТРАНСКРИПТ:
"""


def summarize(transcript: str, template_name: str = "default") -> dict | None:
    text = transcript[:MAX_CHARS] if len(transcript) > MAX_CHARS else transcript

    if build_prompt and template_name:
        prompt = build_prompt(template_name, text)
        num_predict = 2048 if template_name != "default" else 1024
    else:
        prompt = SUMMARY_PROMPT + text
        num_predict = 1024

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": num_predict},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ERROR: Ollama unavailable: {e}")
        return None

    response_text = result.get("response", "").strip()

    try:
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(l for l in lines if not l.startswith("```"))
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {
            "summary": response_text[:500],
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }


def resummarize_single(session_id: str, template_name: str = "default"):
    """Re-summarize a single call by session_id."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT session_id, app_name, transcript FROM calls WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if not row:
        print(f"Call not found: {session_id}")
        conn.close()
        sys.exit(1)

    transcript = row["transcript"]
    if not transcript or len(transcript.strip()) < 50:
        print(f"Transcript too short for {session_id}")
        conn.close()
        sys.exit(1)

    print(
        f"Re-summarizing {session_id} ({row['app_name']}) with template={template_name}...",
        flush=True,
    )
    t0 = time.time()
    summary = summarize(transcript, template_name)
    elapsed = time.time() - t0

    if not summary:
        print(f"FAILED ({elapsed:.1f}s)")
        conn.close()
        sys.exit(1)

    summary_json = json.dumps(summary, ensure_ascii=False)
    conn.execute(
        "UPDATE calls SET summary_json = ?, template_name = ? WHERE session_id = ?",
        (summary_json, template_name, session_id),
    )
    conn.commit()
    conn.close()

    ai_count = len(summary.get("action_items", []))
    print(f"OK ({elapsed:.1f}s) — {ai_count} action items")


def main():
    # Parse args
    args = sys.argv[1:]
    session_id = None
    template_name = "default"

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--template" and i + 1 < len(args):
            template_name = args[i + 1]
            i += 2
        else:
            i += 1

    if session_id:
        resummarize_single(session_id, template_name)
        return

    # Batch mode: re-summarize all
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT session_id, app_name, transcript, summary_json FROM calls ORDER BY started_at"
    ).fetchall()

    total = len(rows)
    print(f"Found {total} calls to re-summarize\n")

    updated = 0
    action_items_total = 0

    for i, row in enumerate(rows):
        sid = row["session_id"]
        app = row["app_name"]
        transcript = row["transcript"]

        if not transcript or len(transcript.strip()) < 50:
            print(f"[{i + 1}/{total}] {sid} ({app}) — transcript too short, skip")
            continue

        print(f"[{i + 1}/{total}] {sid} ({app}) — summarizing...", end=" ", flush=True)
        t0 = time.time()
        summary = summarize(transcript, template_name)
        elapsed = time.time() - t0

        if not summary:
            print(f"FAILED ({elapsed:.1f}s)")
            continue

        ai_count = len(summary.get("action_items", []))
        action_items_total += ai_count
        summary_json = json.dumps(summary, ensure_ascii=False)

        conn.execute(
            "UPDATE calls SET summary_json = ?, template_name = ? WHERE session_id = ?",
            (summary_json, template_name, sid),
        )
        conn.commit()
        updated += 1

        status = f"OK ({elapsed:.1f}s)"
        if ai_count > 0:
            status += f" — {ai_count} action items!"
        print(status)

    conn.close()
    print(
        f"\nDone: {updated}/{total} updated, {action_items_total} total action items found"
    )


if __name__ == "__main__":
    main()
