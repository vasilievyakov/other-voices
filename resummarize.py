"""Re-summarize all calls in DB using Ollama to extract real action items."""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DB_PATH = Path.home() / "call-recorder" / "data" / "calls.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
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


def summarize(transcript: str) -> dict | None:
    text = transcript[:MAX_CHARS] if len(transcript) > MAX_CHARS else transcript
    prompt = SUMMARY_PROMPT + text

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
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


def main():
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
        summary = summarize(transcript)
        elapsed = time.time() - t0

        if not summary:
            print(f"FAILED ({elapsed:.1f}s)")
            continue

        ai_count = len(summary.get("action_items", []))
        action_items_total += ai_count
        summary_json = json.dumps(summary, ensure_ascii=False)

        conn.execute(
            "UPDATE calls SET summary_json = ? WHERE session_id = ?",
            (summary_json, sid),
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
