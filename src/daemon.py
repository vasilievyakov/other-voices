"""Call Recorder — main daemon loop with structured logging and observability."""

import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    POLL_INTERVAL,
    LOG_PATH,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    STATUS_PATH,
    DATA_DIR,
    check_ollama,
)
from .commitment_extractor import extract_commitments
from .database import Database
from .detector import CallDetector
from .recorder import AudioRecorder
from .settings import (
    get_min_call_duration,
    should_transcribe,
    should_summarize,
    should_extract_commitments,
    get_default_template,
)
from .speaker_resolver import resolve_speakers, format_transcript_for_prompt
from .summarizer import Summarizer
from .templates import export_templates_json
from .transcriber import Transcriber

# ---------------------------------------------------------------------------
# Logging setup — rotating file handler (5MB x 3 backups) + stdout
# ---------------------------------------------------------------------------
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_log_formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)s] [%(stage)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class _StageFilter(logging.Filter):
    """Inject a default 'stage' field if the LogRecord doesn't have one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "stage"):
            record.stage = "daemon"  # type: ignore[attr-defined]
        return True


_file_handler = logging.handlers.RotatingFileHandler(
    str(LOG_PATH),
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)
_file_handler.addFilter(_StageFilter())

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)
_console_handler.addFilter(_StageFilter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _console_handler],
)
log = logging.getLogger("call-recorder")


def _log(level: int, stage: str, msg: str, duration_ms: float | None = None):
    """Emit a structured log line with stage and optional duration."""
    extra = {"stage": stage}
    suffix = f" [duration={duration_ms:.0f}ms]" if duration_ms is not None else ""
    log.log(level, f"{msg}{suffix}", extra=extra)


# ---------------------------------------------------------------------------
# macOS notifications
# ---------------------------------------------------------------------------


def notify(title: str, message: str):
    """Send macOS notification via osascript."""
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


def _notify_error(stage: str, app_name: str, error: str):
    """Send macOS notification about a pipeline error."""
    notify("Other Voices", f"{stage} failed for {app_name}: {error}")


# ---------------------------------------------------------------------------
# Status file — read by SwiftUI app
# ---------------------------------------------------------------------------

# Module-level Ollama availability (updated on startup and before each pipeline)
_ollama_available: bool = True


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
        "ollama_available": _ollama_available,
    }
    tmp_path = STATUS_PATH.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, STATUS_PATH)
    except Exception as e:
        _log(logging.WARNING, "status", f"Failed to write status: {e}")


# ---------------------------------------------------------------------------
# Pipeline timer helper
# ---------------------------------------------------------------------------


class _Timer:
    """Context manager that measures elapsed time in milliseconds."""

    def __init__(self):
        self.elapsed_ms: float = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = (time.monotonic() - self._start) * 1000


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def process_recording(
    session: dict, transcriber: Transcriber, summarizer: Summarizer, db: Database
):
    """Post-process a completed recording: transcribe, summarize, extract commitments.

    Pipeline stages (each timed):
        1. transcription (separate channels, fallback to merged)
        2. speaker_resolution (Ollama — skipped if unavailable)
        3. summarization (Ollama — skipped if unavailable)
        4. commitment_extraction (Ollama — skipped if unavailable)
        5. save (SQLite)

    If Ollama is unavailable, recording and transcription still proceed.
    """
    global _ollama_available
    pipeline_start = time.monotonic()

    session_id = session["session_id"]
    duration = session["duration_seconds"]
    app_name = session["app_name"]

    min_duration = get_min_call_duration()
    if duration < min_duration:
        _log(
            logging.INFO,
            "pipeline",
            f"Call too short ({duration:.0f}s < {min_duration}s), skipping "
            f"[session={session_id}, app={app_name}]",
        )
        notify(
            "Call Recorder",
            f"Звонок {app_name} слишком короткий ({duration:.0f}с), пропущен",
        )
        return

    _log(
        logging.INFO,
        "pipeline",
        f"Processing call: session={session_id}, app={app_name}, "
        f"duration={duration:.0f}s",
    )
    notify("Call Recorder", f"Обработка звонка {app_name} ({duration:.0f}с)...")

    # ── Pre-flight: check Ollama availability ──
    _ollama_available = check_ollama()
    if not _ollama_available:
        _log(
            logging.WARNING,
            "pipeline",
            f"Ollama unavailable — will record and transcribe but skip "
            f"AI stages (speaker resolution, summarization, commitments) "
            f"[session={session_id}]",
        )
        _notify_error(
            "Ollama",
            app_name,
            "not running. Transcription will proceed, but no summary.",
        )

    # ── Step 1: Transcription (respects user settings) ──
    if not should_transcribe():
        _log(
            logging.INFO,
            "pipeline",
            f"Transcription DISABLED by user settings [session={session_id}]",
        )
        # Save call record without transcription
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
        notify(
            "Call Recorder",
            f"Звонок {app_name} ({duration:.0f}с) записан (без транскрипции).",
        )
        return

    write_status(
        "processing", app_name, session_id, session["started_at"], "transcribing"
    )

    with _Timer() as t_transcribe:
        _log(
            logging.INFO,
            "transcription",
            f"Starting separate-channel transcription [session={session_id}]",
        )
        separate_result = transcriber.transcribe_separate(session["session_dir"])

    if separate_result:
        _log(
            logging.INFO,
            "transcription",
            f"Separate transcription OK: {len(separate_result['text'])} chars, "
            f"{len(separate_result['segments'])} segments "
            f"[session={session_id}]",
            duration_ms=t_transcribe.elapsed_ms,
        )
        unified_segments = separate_result["segments"]
        transcript = separate_result["text"]
        transcript_segments = json.dumps(unified_segments, ensure_ascii=False)
        segments_list = unified_segments
    else:
        _log(
            logging.WARNING,
            "transcription",
            f"Separate transcription failed, trying merged [session={session_id}]",
            duration_ms=t_transcribe.elapsed_ms,
        )

        with _Timer() as t_merge:
            transcribe_result = transcriber.transcribe(session["session_dir"])

        if not transcribe_result:
            _log(
                logging.ERROR,
                "transcription",
                f"All transcription methods failed [session={session_id}]",
                duration_ms=t_merge.elapsed_ms,
            )
            _notify_error("Transcription", app_name, "all methods failed")
            notify("Call Recorder", f"Ошибка транскрипции {app_name}")
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

        _log(
            logging.INFO,
            "transcription",
            f"Merged transcription OK [session={session_id}]",
            duration_ms=t_merge.elapsed_ms,
        )

        if isinstance(transcribe_result, dict):
            transcript = transcribe_result["text"]
            transcript_segments = json.dumps(
                transcribe_result["segments"], ensure_ascii=False
            )
            segments_list = transcribe_result["segments"]
        else:
            transcript = transcribe_result
            transcript_segments = None
            segments_list = None
        unified_segments = None
        speaker_map = None

    # ── Step 2: Speaker resolution (requires Ollama) ──
    if unified_segments and _ollama_available:
        write_status(
            "processing",
            app_name,
            session_id,
            session["started_at"],
            "resolving speakers",
        )
        with _Timer() as t_speakers:
            _log(
                logging.INFO,
                "speaker_resolution",
                f"Resolving speakers [session={session_id}, "
                f"segments={len(unified_segments)}]",
            )
            speaker_map = resolve_speakers(unified_segments)

        _log(
            logging.INFO,
            "speaker_resolution",
            f"Speaker map: {json.dumps(speaker_map, ensure_ascii=False)} "
            f"[session={session_id}]",
            duration_ms=t_speakers.elapsed_ms,
        )
    elif unified_segments and not _ollama_available:
        _log(
            logging.WARNING,
            "speaker_resolution",
            f"SKIPPED — Ollama unavailable [session={session_id}]",
        )
        speaker_map = {"SPEAKER_ME": {"confirmed": True, "source": "mic_channel"}}
    # else: speaker_map already set to None in merged-fallback branch above

    # ── Step 3: Summarize (requires Ollama + user setting) ──
    summary = None
    entities = []
    if _ollama_available and should_summarize():
        write_status(
            "processing", app_name, session_id, session["started_at"], "summarizing"
        )
        template_name = session.get("template_name", get_default_template())
        with _Timer() as t_summary:
            _log(
                logging.INFO,
                "summarization",
                f"Summarizing [session={session_id}, template={template_name}, "
                f"chars={len(transcript)}]",
            )
            summary = summarizer.summarize(
                transcript, template_name=template_name, segments=segments_list
            )

        if summary:
            _log(
                logging.INFO,
                "summarization",
                f"Summary generated: {len(json.dumps(summary))} chars JSON "
                f"[session={session_id}]",
                duration_ms=t_summary.elapsed_ms,
            )
            if isinstance(summary.get("entities"), list):
                entities = summary.pop("entities")
        else:
            _log(
                logging.WARNING,
                "summarization",
                f"Summarization returned None [session={session_id}]",
                duration_ms=t_summary.elapsed_ms,
            )
            _notify_error("Summarization", app_name, "returned empty result")
    elif not _ollama_available:
        _log(
            logging.WARNING,
            "summarization",
            f"SKIPPED — Ollama unavailable [session={session_id}]",
        )
        template_name = session.get("template_name", get_default_template())
    else:
        _log(
            logging.INFO,
            "summarization",
            f"SKIPPED — disabled by user settings [session={session_id}]",
        )
        template_name = session.get("template_name", get_default_template())

    # ── Step 4: Extract commitments (requires Ollama + speaker-resolved transcript + user setting) ──
    commitments_data = None
    if (
        unified_segments
        and speaker_map
        and _ollama_available
        and should_extract_commitments()
    ):
        write_status(
            "processing",
            app_name,
            session_id,
            session["started_at"],
            "extracting commitments",
        )
        with _Timer() as t_commitments:
            _log(
                logging.INFO,
                "commitment_extraction",
                f"Extracting commitments [session={session_id}]",
            )
            resolved_transcript = format_transcript_for_prompt(
                unified_segments, speaker_map
            )
            call_date = session.get("started_at", "")[:10]
            commitments_data = extract_commitments(
                resolved_transcript, speaker_map, call_date
            )

        n_commitments = len(commitments_data.get("commitments", []))
        if n_commitments > 0:
            _log(
                logging.INFO,
                "commitment_extraction",
                f"Extracted {n_commitments} commitments [session={session_id}]",
                duration_ms=t_commitments.elapsed_ms,
            )
        else:
            _log(
                logging.WARNING,
                "commitment_extraction",
                f"No commitments extracted "
                f"(notes: {commitments_data.get('extraction_notes', 'none')}) "
                f"[session={session_id}]",
                duration_ms=t_commitments.elapsed_ms,
            )
    elif unified_segments and not _ollama_available:
        _log(
            logging.WARNING,
            "commitment_extraction",
            f"SKIPPED — Ollama unavailable [session={session_id}]",
        )
    elif unified_segments and not should_extract_commitments():
        _log(
            logging.INFO,
            "commitment_extraction",
            f"SKIPPED — disabled by user settings [session={session_id}]",
        )

    # ── Step 5: Save to database ──
    write_status("processing", app_name, session_id, session["started_at"], "saving")
    with _Timer() as t_save:
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

        if commitments_data and commitments_data.get("commitments"):
            db.insert_commitments(session_id, commitments_data["commitments"])

    _log(
        logging.INFO,
        "save",
        f"Saved to database [session={session_id}]",
        duration_ms=t_save.elapsed_ms,
    )

    # ── Pipeline complete — summary notification ──
    total_ms = (time.monotonic() - pipeline_start) * 1000

    summary_text = ""
    if summary and summary.get("summary"):
        summary_text = f"\n{summary['summary'][:100]}"

    commitment_text = ""
    if commitments_data and commitments_data.get("commitments"):
        n = len(commitments_data["commitments"])
        commitment_text = f" | {n} обязательств"

    skipped_text = ""
    if not _ollama_available:
        skipped_text = " [AI skipped: Ollama offline]"

    notify(
        "Call Recorder",
        f"Звонок {app_name} ({duration:.0f}с) записан."
        f"{summary_text}{commitment_text}{skipped_text}",
    )
    _log(
        logging.INFO,
        "pipeline",
        f"Pipeline complete: session={session_id}, app={app_name}, "
        f"transcript={len(transcript)} chars, "
        f"summary={'yes' if summary else 'no'}, "
        f"commitments={len(commitments_data.get('commitments', [])) if commitments_data else 0}, "
        f"ollama={'up' if _ollama_available else 'DOWN'}",
        duration_ms=total_ms,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main():
    global _ollama_available

    _log(logging.INFO, "startup", "=" * 50)
    _log(logging.INFO, "startup", "Call Recorder daemon starting")
    _log(
        logging.INFO,
        "startup",
        f"Poll interval: {POLL_INTERVAL}s, Min duration: {get_min_call_duration()}s",
    )
    _log(
        logging.INFO,
        "startup",
        f"User settings: transcribe={should_transcribe()}, "
        f"summarize={should_summarize()}, commitments={should_extract_commitments()}, "
        f"template={get_default_template()}",
    )
    _log(
        logging.INFO,
        "startup",
        f"Log rotation: {LOG_MAX_BYTES // 1024 // 1024}MB x {LOG_BACKUP_COUNT} backups",
    )

    # ── Ollama health check at startup ──
    _ollama_available = check_ollama()
    if _ollama_available:
        _log(logging.INFO, "startup", "Ollama health check: OK")
    else:
        _log(
            logging.WARNING,
            "startup",
            "Ollama health check: FAILED — daemon will record and transcribe "
            "but skip AI features (summarization, speaker resolution, commitments)",
        )
        notify(
            "Other Voices",
            "Ollama not running. Recording works, but no AI summary/commitments.",
        )

    # Export templates for Swift app
    try:
        templates_path = DATA_DIR / "templates.json"
        templates_path.write_text(export_templates_json(), encoding="utf-8")
        _log(logging.INFO, "startup", f"Templates exported to {templates_path}")
    except Exception as e:
        _log(logging.WARNING, "startup", f"Failed to export templates: {e}")

    detector = CallDetector()
    recorder = AudioRecorder()
    transcriber = Transcriber()
    summarizer = Summarizer()
    db = Database()

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        _log(logging.INFO, "signal", f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    notify("Call Recorder", "Демон запущен, мониторинг звонков активен")
    write_status("idle")

    _log(logging.INFO, "startup", "=" * 50)

    try:
        while running:
            in_call, app_name = detector.check()

            if in_call and not recorder.is_recording:
                # Call started — re-check Ollama each time
                _ollama_available = check_ollama()
                _log(
                    logging.INFO,
                    "detection",
                    f"Call detected: {app_name} "
                    f"[ollama={'up' if _ollama_available else 'DOWN'}]",
                )
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
                _log(logging.INFO, "detection", "Call ended, stopping recording")
                session = recorder.stop()
                if session:
                    try:
                        process_recording(session, transcriber, summarizer, db)
                    except Exception as e:
                        _log(
                            logging.ERROR,
                            "pipeline",
                            f"Pipeline CRASHED: {e} "
                            f"[session={session.get('session_id', '?')}]",
                        )
                        _notify_error(
                            "Pipeline",
                            session.get("app_name", "Unknown"),
                            str(e)[:80],
                        )
                write_status("idle")

            time.sleep(POLL_INTERVAL)

    except Exception as e:
        _log(logging.ERROR, "daemon", f"Daemon fatal error: {e}")
        log.exception("Full traceback:")
        raise
    finally:
        if recorder.is_recording:
            _log(logging.INFO, "shutdown", "Stopping active recording before exit...")
            session = recorder.stop()
            if session:
                try:
                    process_recording(session, transcriber, summarizer, db)
                except Exception as e:
                    _log(
                        logging.ERROR,
                        "shutdown",
                        f"Final pipeline failed: {e}",
                    )
        _log(logging.INFO, "shutdown", "Call Recorder daemon stopped")
        write_status("stopped")
        notify("Call Recorder", "Демон остановлен")


if __name__ == "__main__":
    main()
