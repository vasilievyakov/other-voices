"""Call Recorder — main daemon loop."""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import MIN_CALL_DURATION, POLL_INTERVAL, LOG_PATH, STATUS_PATH, DATA_DIR
from .database import Database
from .detector import CallDetector
from .recorder import AudioRecorder
from .summarizer import Summarizer
from .templates import export_templates_json
from .transcriber import Transcriber

# Logging setup
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("call-recorder")


def notify(title: str, message: str):
    """Send macOS notification."""
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def write_status(
    state: str,
    app_name: str | None = None,
    session_id: str | None = None,
    started_at: str | None = None,
    pipeline: str | None = None,
):
    """Write daemon status to status.json atomically via os.replace."""
    status = {
        "daemon_pid": os.getpid(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "app_name": app_name,
        "session_id": session_id,
        "started_at": started_at,
        "pipeline": pipeline,
    }
    tmp_path = STATUS_PATH.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, STATUS_PATH)
    except Exception as e:
        log.warning(f"Failed to write status: {e}")


def process_recording(
    session: dict, transcriber: Transcriber, summarizer: Summarizer, db: Database
):
    """Post-process a completed recording: transcribe, summarize, save to DB."""
    session_id = session["session_id"]
    duration = session["duration_seconds"]
    app_name = session["app_name"]

    if duration < MIN_CALL_DURATION:
        log.info(f"Call too short ({duration:.0f}s < {MIN_CALL_DURATION}s), skipping")
        notify(
            "Call Recorder",
            f"Звонок {app_name} слишком короткий ({duration:.0f}с), пропущен",
        )
        return

    notify("Call Recorder", f"Обработка звонка {app_name} ({duration:.0f}с)...")

    # Transcribe
    log.info(f"Transcribing {session_id}...")
    write_status(
        "processing", app_name, session_id, session["started_at"], "transcribing"
    )
    transcribe_result = transcriber.transcribe(session["session_dir"])

    if not transcribe_result:
        log.warning(f"Transcription failed for {session_id}")
        notify("Call Recorder", f"Ошибка транскрипции {app_name}")
        # Still save the record without transcript
        db.insert_call(
            session_id=session_id,
            app_name=app_name,
            started_at=session["started_at"],
            ended_at=session["ended_at"],
            duration_seconds=duration,
            system_wav_path=session["system_wav"],
            mic_wav_path=session["mic_wav"],
            transcript=None,
            summary=None,
        )
        return

    # Handle both dict (with segments) and str (plain text) return
    import json as _json

    transcript_segments = None
    if isinstance(transcribe_result, dict):
        transcript = transcribe_result["text"]
        transcript_segments = _json.dumps(
            transcribe_result["segments"], ensure_ascii=False
        )
    else:
        transcript = transcribe_result

    # Summarize
    log.info(f"Summarizing {session_id}...")
    write_status(
        "processing", app_name, session_id, session["started_at"], "summarizing"
    )
    template_name = session.get("template_name", "default")
    # Pass segments for timestamp-aware citation in summary
    segments_list = (
        transcribe_result.get("segments")
        if isinstance(transcribe_result, dict)
        else None
    )
    summary = summarizer.summarize(
        transcript, template_name=template_name, segments=segments_list
    )

    # Extract entities from summary response
    entities = []
    if summary and isinstance(summary.get("entities"), list):
        entities = summary.pop("entities")

    # Save to database
    write_status("processing", app_name, session_id, session["started_at"], "saving")
    db.insert_call(
        session_id=session_id,
        app_name=app_name,
        started_at=session["started_at"],
        ended_at=session["ended_at"],
        duration_seconds=duration,
        system_wav_path=session["system_wav"],
        mic_wav_path=session["mic_wav"],
        transcript=transcript,
        summary=summary,
        template_name=template_name,
        transcript_segments=transcript_segments,
    )

    if entities:
        db.insert_entities(session_id, entities)

    summary_text = ""
    if summary and summary.get("summary"):
        summary_text = f"\n{summary['summary'][:100]}"

    notify(
        "Call Recorder", f"Звонок {app_name} ({duration:.0f}с) записан.{summary_text}"
    )
    log.info(f"Call {session_id} fully processed and saved")


def main():
    log.info("=" * 50)
    log.info("Call Recorder daemon starting")
    log.info(f"Poll interval: {POLL_INTERVAL}s, Min duration: {MIN_CALL_DURATION}s")
    log.info("=" * 50)

    # Export templates for Swift app
    try:
        templates_path = DATA_DIR / "templates.json"
        templates_path.write_text(export_templates_json(), encoding="utf-8")
        log.info(f"Templates exported to {templates_path}")
    except Exception as e:
        log.warning(f"Failed to export templates: {e}")

    detector = CallDetector()
    recorder = AudioRecorder()
    transcriber = Transcriber()
    summarizer = Summarizer()
    db = Database()

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info(f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    notify("Call Recorder", "Демон запущен, мониторинг звонков активен")
    write_status("idle")

    try:
        while running:
            in_call, app_name = detector.check()

            if in_call and not recorder.is_recording:
                # Call started
                log.info(f"Call detected: {app_name}")
                notify("Call Recorder", f"Запись начата: {app_name}")
                recorder.start(app_name)
                write_status(
                    "recording",
                    app_name,
                    recorder.session_id,
                    recorder.started_at.isoformat() if recorder.started_at else None,
                )

            elif not in_call and recorder.is_recording:
                # Call ended
                log.info("Call ended, stopping recording")
                session = recorder.stop()
                if session:
                    process_recording(session, transcriber, summarizer, db)
                write_status("idle")

            time.sleep(POLL_INTERVAL)

    except Exception as e:
        log.exception(f"Daemon error: {e}")
        raise
    finally:
        if recorder.is_recording:
            log.info("Stopping active recording before exit...")
            session = recorder.stop()
            if session:
                process_recording(session, transcriber, summarizer, db)
        log.info("Call Recorder daemon stopped")
        write_status("stopped")
        notify("Call Recorder", "Демон остановлен")


if __name__ == "__main__":
    main()
