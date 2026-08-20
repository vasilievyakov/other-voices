"""Call Recorder — preflight doctor.

One command between "sat down at the Mac" and "the system is alive":
cli.py doctor walks every load-bearing part — binaries, Ollama, DB schema,
daemon heartbeat, LaunchAgent, calendar helper, blind audit — and prints one
line per component plus the owner's single next step.

Every check is a pure function with injectable inputs so unit tests never
touch the live system. The only network call is check_ollama() from
src.config (5s timeout). The database is opened strictly read-only
(mode=ro) — the doctor must never migrate or write anything.

Output line format:  "ok   — компонент: детали"  (statuses: ok | warn | fail)
Exit code: 0 when there are no fails (warns allowed), 1 otherwise.
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import (
    AUDIO_CAPTURE_BIN,
    CALENDAR_PEEK_BIN,
    CALL_SIGNAL_BIN,
    DB_PATH,
    HEARTBEAT_INTERVAL,
    OLLAMA_MODEL,
    STATUS_PATH,
    check_ollama,
)
from scripts.audit_commitments import AUDIT_PATH, parse_verdicts

OK = "ok"
WARN = "warn"
FAIL = "fail"

# Heartbeat is written every HEARTBEAT_INTERVAL (60s); three missed beats
# means the daemon is dead or stopped, not merely busy.
STALE_AFTER = 3 * HEARTBEAT_INTERVAL  # 180 seconds

PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.user.call-recorder.plist"

REQUIRED_TABLES = ("calls", "commitments", "speaker_names")
REQUIRED_COMMITMENT_COLUMNS = ("title", "deadline_date")


@dataclass
class Check:
    status: str  # OK | WARN | FAIL
    component: str
    detail: str

    @property
    def line(self) -> str:
        return f"{self.status:4} — {self.component}: {self.detail}"


def kickstart_command(uid: int | None = None) -> str:
    """The exact command that revives the daemon under launchd."""
    if uid is None:
        uid = os.getuid()
    return f"launchctl kickstart -k gui/{uid}/com.user.call-recorder"


# ---------------------------------------------------------------------------
# 1. Binaries
# ---------------------------------------------------------------------------


def check_binaries(bins: list[Path] | None = None) -> list[Check]:
    if bins is None:
        bins = [CALL_SIGNAL_BIN, AUDIO_CAPTURE_BIN, CALENDAR_PEEK_BIN]
    results = []
    for p in bins:
        p = Path(p)
        name = f"bin/{p.name}"
        if not p.exists():
            results.append(Check(FAIL, name, "отсутствует — собери: ./setup.sh"))
        elif not os.access(p, os.X_OK):
            results.append(Check(FAIL, name, f"не исполняемый — chmod +x {p}"))
        else:
            results.append(Check(OK, name, "на месте, исполняемый"))
    return results


# ---------------------------------------------------------------------------
# 2. Ollama
# ---------------------------------------------------------------------------


def check_ollama_alive(ping=check_ollama, model: str = OLLAMA_MODEL) -> Check:
    if ping():
        return Check(OK, "Ollama", f"доступен, модель {model}")
    return Check(
        WARN,
        "Ollama",
        f"недоступен (модель {model}) — выжимки и обязательства не будут"
        " извлекаться; запусти: ollama serve",
    )


# ---------------------------------------------------------------------------
# 3. Database (read-only, no migrations)
# ---------------------------------------------------------------------------


def check_database(db_path: Path = DB_PATH) -> Check:
    db_path = Path(db_path)
    if not db_path.exists():
        return Check(FAIL, "БД", f"{db_path} отсутствует")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return Check(FAIL, "БД", f"не открывается: {e}")
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            return Check(FAIL, "БД", f"нет таблиц: {', '.join(missing)}")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(commitments)")}
        missing_cols = [c for c in REQUIRED_COMMITMENT_COLUMNS if c not in cols]
        if missing_cols:
            return Check(
                FAIL, "БД", f"в commitments нет колонок: {', '.join(missing_cols)}"
            )
        n_calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        n_open = conn.execute(
            "SELECT COUNT(*) FROM commitments WHERE status='open'"
        ).fetchone()[0]
        return Check(
            OK,
            "БД",
            f"схема полная; звонков: {n_calls}, открытых обязательств: {n_open}",
        )
    except sqlite3.Error as e:
        return Check(FAIL, "БД", f"ошибка чтения: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. status.json: heartbeat + canaries
# ---------------------------------------------------------------------------


def check_status(
    status_path: Path = STATUS_PATH, now: datetime | None = None
) -> tuple[list[Check], bool]:
    """Returns (checks, daemon_alive)."""
    if now is None:
        now = datetime.now(timezone.utc)
    p = Path(status_path)
    if not p.exists():
        return [
            Check(WARN, "status.json", "отсутствует — демон еще ни разу не запускался")
        ], False
    try:
        status = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [Check(FAIL, "status.json", f"не читается: {e}")], False

    checks: list[Check] = []
    ts_raw = status.get("timestamp")
    age = None
    try:
        ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
    except (TypeError, ValueError):
        pass
    state = status.get("state", "?")

    if age is None:
        checks.append(
            Check(FAIL, "демон", f"битый timestamp в status.json: {ts_raw!r}")
        )
        alive = False
    elif state == "stopped":
        checks.append(
            Check(
                WARN,
                "демон",
                f"остановлен штатно (state=stopped, heartbeat {int(age)} с назад)",
            )
        )
        alive = False
    elif age > STALE_AFTER:
        checks.append(
            Check(
                WARN,
                "демон",
                f"мертв: heartbeat {int(age)} с назад"
                f" (порог {STALE_AFTER} с), state={state}",
            )
        )
        alive = False
    else:
        checks.append(
            Check(OK, "демон", f"жив: heartbeat {int(age)} с назад, state={state}")
        )
        alive = True

    streak = status.get("mic_only_streak") or 0
    if streak:
        checks.append(
            Check(
                WARN,
                "канарейка mic-only",
                f"{streak} звонков подряд без канала собеседника —"
                " проверь захват системного звука",
            )
        )
    platforms = status.get("platform_canary") or []
    if platforms:
        checks.append(
            Check(
                WARN,
                "канарейка платформ",
                f"за неделю ни одного звонка: {', '.join(platforms)} —"
                " возможна регрессия детекции",
            )
        )
    extraction = status.get("extraction_canary")
    if extraction:
        checks.append(
            Check(
                WARN,
                "канарейка извлечения",
                f"0 кандидатов в длинном звонке {extraction} —"
                " извлечение могло ослепнуть",
            )
        )
    return checks, alive


# ---------------------------------------------------------------------------
# 5. LaunchAgent
# ---------------------------------------------------------------------------


def check_launchagent(
    plist_path: Path = PLIST_PATH, daemon_alive: bool = False
) -> Check:
    p = Path(plist_path)
    if not p.exists():
        return Check(
            FAIL, "LaunchAgent", f"{p} отсутствует — установи через ./setup.sh"
        )
    if not daemon_alive:
        return Check(
            WARN,
            "LaunchAgent",
            f"plist на месте, демон не работает — запусти: {kickstart_command()}",
        )
    return Check(OK, "LaunchAgent", "plist на месте, демон работает")


# ---------------------------------------------------------------------------
# 6. Calendar helper
# ---------------------------------------------------------------------------


def check_calendar(bin_path: Path = CALENDAR_PEEK_BIN) -> Check:
    if Path(bin_path).exists():
        return Check(
            OK,
            "календарь",
            "bin/calendar-peek на месте; доступ к Календарю"
            " проверится при первом запуске демона",
        )
    return Check(
        WARN,
        "календарь",
        "bin/calendar-peek отсутствует — брифы перед встречами работать не будут",
    )


# ---------------------------------------------------------------------------
# 7. Blind precision audit
# ---------------------------------------------------------------------------


def check_audit(audit_path: Path | None = None) -> Check:
    path = Path(audit_path) if audit_path is not None else AUDIT_PATH
    if not path.exists():
        return Check(
            WARN,
            "аудит",
            f"{path.name} отсутствует — выгрузи:"
            " .venv/bin/python scripts/audit_commitments.py",
        )
    verdicts = parse_verdicts(path.read_text(encoding="utf-8"))
    if not verdicts:
        return Check(
            WARN, "аудит", f"в {path.name} нет строк для разметки — перевыгрузи"
        )
    total = len(verdicts)
    marked = sum(1 for m in verdicts.values() if m in ("+", "-"))
    if marked == 0:
        return Check(
            WARN,
            "аудит",
            f"не размечен: {total} строк ждут вердикта — это 15 минут",
        )
    if marked < total:
        return Check(
            WARN, "аудит", f"размечено {marked} из {total} — доразметь, это 15 минут"
        )
    return Check(OK, "аудит", f"размечен полностью: {total} строк")


# ---------------------------------------------------------------------------
# Assembly and report
# ---------------------------------------------------------------------------


def collect_checks(
    *,
    bins: list[Path] | None = None,
    ping=None,
    db_path: Path | None = None,
    status_path: Path | None = None,
    plist_path: Path | None = None,
    calendar_bin: Path | None = None,
    audit_path: Path | None = None,
    now: datetime | None = None,
) -> list[Check]:
    checks = list(check_binaries(bins))
    checks.append(check_ollama_alive(ping if ping is not None else check_ollama))
    checks.append(check_database(db_path if db_path is not None else DB_PATH))
    status_checks, alive = check_status(
        status_path if status_path is not None else STATUS_PATH, now=now
    )
    checks.extend(status_checks)
    checks.append(
        check_launchagent(
            plist_path if plist_path is not None else PLIST_PATH,
            daemon_alive=alive,
        )
    )
    checks.append(
        check_calendar(calendar_bin if calendar_bin is not None else CALENDAR_PEEK_BIN)
    )
    checks.append(check_audit(audit_path))
    return checks


# Components whose warn means "the daemon is not running" — the owner's next
# step is then always the same kickstart command.
_DAEMON_COMPONENTS = ("демон", "LaunchAgent", "status.json")


def next_step(checks: list[Check]) -> str:
    fails = [c for c in checks if c.status == FAIL]
    if fails:
        c = fails[0]
        return f"Следующий шаг: {c.component} — {c.detail}"
    warns = {c.component: c for c in checks if c.status == WARN}
    for name in _DAEMON_COMPONENTS:
        if name in warns:
            return f"Следующий шаг: подними демона — {kickstart_command()}"
    if "аудит" in warns:
        return "Следующий шаг: разметь eval/precision-audit.md — это 15 минут"
    if warns:
        c = next(iter(warns.values()))
        return f"Следующий шаг: {c.component} — {c.detail}"
    return "Система жива — можно работать."


def format_report(checks: list[Check]) -> tuple[str, int]:
    """Render the full report; returns (text, exit_code)."""
    n_ok = sum(1 for c in checks if c.status == OK)
    n_warn = sum(1 for c in checks if c.status == WARN)
    n_fail = sum(1 for c in checks if c.status == FAIL)
    lines = [c.line for c in checks]
    lines.append("")
    lines.append(f"{n_ok} ok, {n_warn} warn, {n_fail} fail")
    lines.append(next_step(checks))
    return "\n".join(lines), (1 if n_fail else 0)


def run_doctor(print_fn=print, **overrides) -> int:
    """Run all checks, print the report, return the exit code."""
    text, code = format_report(collect_checks(**overrides))
    print_fn(text)
    return code
