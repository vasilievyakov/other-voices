"""Import existing transcripts into calls.db for testing Other Voices app."""

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

TRANSCRIPTS_DIR = Path.home() / "Audio" / "Transcripts"
DB_PATH = Path.home() / "call-recorder" / "data" / "calls.db"

# Map participant names to likely apps
APP_GUESSES = {
    "Zoom": ["воркшоп", "конференц", "лаборатория", "брифинг", "группа"],
    "Google Meet": ["обсуждение", "стратегия", "мониторинг"],
    "Telegram": ["лектор", "участники"],
}


def guess_app(filename: str) -> str:
    lower = filename.lower()
    for app, keywords in APP_GUESSES.items():
        if any(kw in lower for kw in keywords):
            return app
    # Default distribution
    return random.choice(["Zoom", "Zoom", "Google Meet", "Telegram", "FaceTime"])


def main():
    txt_files = sorted(TRANSCRIPTS_DIR.glob("*.txt"))
    if not txt_files:
        print("No .txt files found")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Check existing count
    existing = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    print(f"Existing calls in DB: {existing}")

    imported = 0
    for txt_path in txt_files:
        # Parse filename: "Name — topic.txt"
        stem = txt_path.stem.strip()

        # Read transcript
        transcript = txt_path.read_text(encoding="utf-8").strip()
        if not transcript:
            continue

        # Use file modification time as call time
        mtime = os.path.getmtime(txt_path)
        started = datetime.fromtimestamp(mtime)

        # Estimate duration from transcript length (rough: ~150 words/min speaking)
        word_count = len(transcript.split())
        duration_minutes = max(5, word_count / 150)
        duration_seconds = duration_minutes * 60

        ended = started + timedelta(seconds=duration_seconds)
        session_id = started.strftime("%Y%m%d_%H%M%S")

        # Check for duplicate
        row = conn.execute(
            "SELECT 1 FROM calls WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row:
            # Add random seconds to avoid collision
            started = started + timedelta(seconds=random.randint(1, 59))
            session_id = started.strftime("%Y%m%d_%H%M%S")

        app_name = guess_app(stem)

        # Build a minimal summary from transcript (first ~500 chars as summary)
        summary_text = transcript[:500].replace("\n", " ").strip()
        if len(transcript) > 500:
            summary_text += "..."

        summary = {
            "summary": summary_text,
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [stem.split("—")[0].strip()] if "—" in stem else [],
        }

        conn.execute(
            """INSERT OR IGNORE INTO calls
               (session_id, app_name, started_at, ended_at, duration_seconds,
                system_wav_path, mic_wav_path, transcript, summary_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                app_name,
                started.isoformat(),
                ended.isoformat(),
                duration_seconds,
                None,  # no audio files
                None,
                transcript,
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        imported += 1
        print(f"  + {app_name:15s} | {stem[:50]}")

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    conn.close()

    print(f"\nImported: {imported} transcripts")
    print(f"Total calls in DB: {total}")


if __name__ == "__main__":
    main()
