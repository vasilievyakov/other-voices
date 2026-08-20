"""Tests for src.doctor — preflight check (cli.py doctor).

One command between "sat down at the Mac" and "the system is alive".
Every check is a pure function with injectable inputs; no network except
the injected Ollama ping. Real DB / status.json are never touched here.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.doctor import (
    FAIL,
    OK,
    STALE_AFTER,
    WARN,
    Check,
    check_audit,
    check_binaries,
    check_calendar,
    check_database,
    check_launchagent,
    check_ollama_alive,
    check_status,
    collect_checks,
    format_report,
    kickstart_command,
    run_doctor,
)

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# Helpers
# =============================================================================


def _make_bin(tmp_path, name, executable=True):
    p = tmp_path / name
    p.write_bytes(b"#!/bin/sh\n")
    if executable:
        p.chmod(0o755)
    else:
        p.chmod(0o644)
    return p


def _full_db(tmp_path):
    """Real schema via Database migrations + 1 call, 2 commitments (1 open)."""
    from src.database import Database

    db = Database(db_path=tmp_path / "calls.db")
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO calls (session_id, app_name, started_at, ended_at,"
            " duration_seconds) VALUES ('s1','Zoom','2026-08-19T10:00:00',"
            "'2026-08-19T10:30:00',1800)"
        )
        conn.execute(
            "INSERT INTO commitments (session_id, direction, who_label, text,"
            " status) VALUES ('s1','outgoing','ME','пришлю доску','open')"
        )
        conn.execute(
            "INSERT INTO commitments (session_id, direction, who_label, text,"
            " status) VALUES ('s1','incoming','OTHER','пришлет бриф','done')"
        )
    return db.db_path


def _write_status(path, age_seconds=30, state="idle", now=NOW, **extra):
    ts = (now - timedelta(seconds=age_seconds)).isoformat(timespec="milliseconds")
    payload = {
        "daemon_pid": 123,
        "timestamp": ts,
        "state": state,
        "mic_only_streak": 0,
        "platform_canary": [],
        "extraction_canary": None,
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _audit_md(marks):
    """Markdown in the audit_commitments export format, one row per mark."""
    blocks = []
    for i, mark in enumerate(marks, 1):
        blocks.append(
            f"## {i} <!-- id:{i} session:sess_{i} status:open -->\n"
            f"Цитата: «фраза {i}»\n"
            f"Текст: фраза {i}\n"
            f"Дата звонка: 2026-08-01\n"
            f"Вердикт: {mark}\n"
        )
    return "\n".join(blocks)


# =============================================================================
# Check.line — output format
# =============================================================================


class TestLineFormat:
    def test_ok_line(self):
        assert Check(OK, "Ollama", "доступен").line == "ok   — Ollama: доступен"

    def test_warn_line(self):
        assert Check(WARN, "демон", "мертв").line == "warn — демон: мертв"

    def test_fail_line(self):
        assert Check(FAIL, "БД", "нет таблиц").line == "fail — БД: нет таблиц"


# =============================================================================
# 1. Binaries
# =============================================================================


class TestCheckBinaries:
    def test_all_present_executable(self, tmp_path):
        bins = [_make_bin(tmp_path, n) for n in ("call-signal", "audio-capture")]
        results = check_binaries(bins)
        assert [r.status for r in results] == [OK, OK]
        assert results[0].component == "bin/call-signal"

    def test_missing_binary_fails(self, tmp_path):
        bins = [_make_bin(tmp_path, "call-signal"), tmp_path / "audio-capture"]
        results = check_binaries(bins)
        assert results[0].status == OK
        assert results[1].status == FAIL
        assert "отсутствует" in results[1].detail

    def test_not_executable_fails(self, tmp_path):
        bins = [_make_bin(tmp_path, "calendar-peek", executable=False)]
        results = check_binaries(bins)
        assert results[0].status == FAIL
        assert "не исполняем" in results[0].detail

    def test_defaults_are_three_project_binaries(self):
        results = check_binaries()
        names = [r.component for r in results]
        assert names == ["bin/call-signal", "bin/audio-capture", "bin/calendar-peek"]


# =============================================================================
# 2. Ollama
# =============================================================================


class TestCheckOllama:
    def test_available(self):
        r = check_ollama_alive(ping=lambda: True, model="test-model")
        assert r.status == OK
        assert "test-model" in r.detail

    def test_unavailable_is_warn_not_fail(self):
        r = check_ollama_alive(ping=lambda: False, model="test-model")
        assert r.status == WARN
        assert "test-model" in r.detail

    def test_default_model_from_config(self):
        from src.config import OLLAMA_MODEL

        r = check_ollama_alive(ping=lambda: True)
        assert OLLAMA_MODEL in r.detail


# =============================================================================
# 3. Database
# =============================================================================


class TestCheckDatabase:
    def test_missing_file_fails(self, tmp_path):
        r = check_database(tmp_path / "nope.db")
        assert r.status == FAIL
        assert "отсутствует" in r.detail

    def test_full_schema_ok_with_counts(self, tmp_path):
        r = check_database(_full_db(tmp_path))
        assert r.status == OK
        assert "звонков: 1" in r.detail
        assert "открытых обязательств: 1" in r.detail

    def test_missing_tables_fail(self, tmp_path):
        p = tmp_path / "bad.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE calls (session_id TEXT)")
        conn.commit()
        conn.close()
        r = check_database(p)
        assert r.status == FAIL
        assert "commitments" in r.detail
        assert "speaker_names" in r.detail

    def test_missing_commitment_columns_fail(self, tmp_path):
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE calls (session_id TEXT)")
        conn.execute("CREATE TABLE commitments (id INTEGER, text TEXT)")
        conn.execute("CREATE TABLE speaker_names (session_id TEXT)")
        conn.commit()
        conn.close()
        r = check_database(p)
        assert r.status == FAIL
        assert "title" in r.detail
        assert "deadline_date" in r.detail

    def test_read_only_never_writes(self, tmp_path):
        """The doctor must not touch the DB — mtime stays intact."""
        p = _full_db(tmp_path)
        before = p.stat().st_mtime_ns
        check_database(p)
        assert p.stat().st_mtime_ns == before


# =============================================================================
# 4. status.json
# =============================================================================


class TestCheckStatus:
    def test_missing_file_warn_dead(self, tmp_path):
        results, alive = check_status(tmp_path / "status.json", now=NOW)
        assert alive is False
        assert len(results) == 1
        assert results[0].status == WARN
        assert "не запускался" in results[0].detail

    def test_fresh_heartbeat_ok_alive(self, tmp_path):
        p = _write_status(tmp_path / "status.json", age_seconds=30, state="idle")
        results, alive = check_status(p, now=NOW)
        assert alive is True
        assert results[0].status == OK
        assert results[0].component == "демон"
        assert "state=idle" in results[0].detail
        assert len(results) == 1  # no canary warns

    def test_stale_heartbeat_warn_dead(self, tmp_path):
        p = _write_status(
            tmp_path / "status.json", age_seconds=STALE_AFTER + 120, state="idle"
        )
        results, alive = check_status(p, now=NOW)
        assert alive is False
        assert results[0].status == WARN
        assert "мертв" in results[0].detail

    def test_boundary_at_stale_after_still_alive(self, tmp_path):
        p = _write_status(tmp_path / "status.json", age_seconds=STALE_AFTER)
        _, alive = check_status(p, now=NOW)
        assert alive is True

    def test_state_stopped_warn_dead(self, tmp_path):
        p = _write_status(tmp_path / "status.json", age_seconds=30, state="stopped")
        results, alive = check_status(p, now=NOW)
        assert alive is False
        assert results[0].status == WARN
        assert "остановлен" in results[0].detail

    def test_corrupt_json_fails(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text("{broken", encoding="utf-8")
        results, alive = check_status(p, now=NOW)
        assert alive is False
        assert results[0].status == FAIL

    def test_bad_timestamp_fails(self, tmp_path):
        p = tmp_path / "status.json"
        p.write_text(json.dumps({"timestamp": "yesterday", "state": "idle"}))
        results, alive = check_status(p, now=NOW)
        assert alive is False
        assert results[0].status == FAIL

    def test_canaries_each_produce_warn(self, tmp_path):
        p = _write_status(
            tmp_path / "status.json",
            age_seconds=30,
            state="idle",
            mic_only_streak=3,
            platform_canary=["Zoom", "Telegram"],
            extraction_canary="20260819_100000",
        )
        results, alive = check_status(p, now=NOW)
        assert alive is True
        statuses = [r.status for r in results]
        assert statuses == [OK, WARN, WARN, WARN]
        text = " | ".join(r.detail for r in results)
        assert "3" in text
        assert "Zoom, Telegram" in text
        assert "20260819_100000" in text

    def test_older_status_format_without_canary_keys(self, tmp_path):
        """A status.json written by an older daemon has no extraction_canary."""
        p = tmp_path / "status.json"
        ts = (NOW - timedelta(seconds=30)).isoformat(timespec="milliseconds")
        p.write_text(json.dumps({"timestamp": ts, "state": "idle"}))
        results, alive = check_status(p, now=NOW)
        assert alive is True
        assert len(results) == 1


# =============================================================================
# 5. LaunchAgent
# =============================================================================


class TestCheckLaunchAgent:
    def test_missing_plist_fails(self, tmp_path):
        r = check_launchagent(tmp_path / "x.plist", daemon_alive=True)
        assert r.status == FAIL

    def test_plist_and_alive_ok(self, tmp_path):
        p = tmp_path / "com.user.call-recorder.plist"
        p.write_text("<plist/>")
        r = check_launchagent(p, daemon_alive=True)
        assert r.status == OK

    def test_plist_but_dead_warn_with_exact_kickstart(self, tmp_path):
        p = tmp_path / "com.user.call-recorder.plist"
        p.write_text("<plist/>")
        r = check_launchagent(p, daemon_alive=False)
        assert r.status == WARN
        expected = f"launchctl kickstart -k gui/{os.getuid()}/com.user.call-recorder"
        assert expected in r.detail

    def test_kickstart_command_exact(self):
        assert (
            kickstart_command(501)
            == "launchctl kickstart -k gui/501/com.user.call-recorder"
        )


# =============================================================================
# 6. Calendar
# =============================================================================


class TestCheckCalendar:
    def test_present_ok_mentions_first_daemon_run(self, tmp_path):
        p = _make_bin(tmp_path, "calendar-peek")
        r = check_calendar(p)
        assert r.status == OK
        assert "при первом запуске демона" in r.detail

    def test_missing_warn(self, tmp_path):
        r = check_calendar(tmp_path / "calendar-peek")
        assert r.status == WARN


# =============================================================================
# 7. Blind audit
# =============================================================================


class TestCheckAudit:
    def test_missing_file_warn(self, tmp_path):
        r = check_audit(tmp_path / "precision-audit.md")
        assert r.status == WARN
        assert "отсутствует" in r.detail

    def test_unmarked_warn_reminds_15_minutes(self, tmp_path):
        p = tmp_path / "precision-audit.md"
        p.write_text(_audit_md(["_", "_", "_"]), encoding="utf-8")
        r = check_audit(p)
        assert r.status == WARN
        assert "3" in r.detail
        assert "15 минут" in r.detail

    def test_partially_marked_warn(self, tmp_path):
        p = tmp_path / "precision-audit.md"
        p.write_text(_audit_md(["+", "_", "-"]), encoding="utf-8")
        r = check_audit(p)
        assert r.status == WARN
        assert "2 из 3" in r.detail

    def test_fully_marked_ok(self, tmp_path):
        p = tmp_path / "precision-audit.md"
        p.write_text(_audit_md(["+", "-", "+"]), encoding="utf-8")
        r = check_audit(p)
        assert r.status == OK
        assert "3" in r.detail

    def test_annotated_verdicts_count_as_marked(self, tmp_path):
        """parse_verdicts takes the first char: «- дубль» is a valid '-'."""
        p = tmp_path / "precision-audit.md"
        p.write_text(_audit_md(["+ точно", "- дубль"]), encoding="utf-8")
        r = check_audit(p)
        assert r.status == OK

    def test_no_rows_warn(self, tmp_path):
        p = tmp_path / "precision-audit.md"
        p.write_text("# пустой файл\n", encoding="utf-8")
        r = check_audit(p)
        assert r.status == WARN


# =============================================================================
# Report: summary line, next step, exit code
# =============================================================================


def _c(status, component="x", detail="d"):
    return Check(status, component, detail)


class TestFormatReport:
    def test_summary_counts_and_exit_zero_with_warns(self):
        text, code = format_report([_c(OK), _c(WARN), _c(OK)])
        assert "2 ok, 1 warn, 0 fail" in text
        assert code == 0

    def test_fail_gives_exit_one(self):
        text, code = format_report([_c(OK), _c(FAIL, "БД", "нет таблиц")])
        assert "1 ok, 0 warn, 1 fail" in text
        assert code == 1

    def test_next_step_prefers_fail(self):
        text, _ = format_report(
            [
                _c(FAIL, "БД", "нет таблиц: commitments"),
                _c(WARN, "аудит", "не размечен"),
            ]
        )
        step = text.splitlines()[-1]
        assert "Следующий шаг" in step
        assert "БД" in step

    def test_next_step_dead_daemon_gives_kickstart(self):
        text, _ = format_report(
            [_c(WARN, "демон", "мертв"), _c(WARN, "аудит", "не размечен")]
        )
        step = text.splitlines()[-1]
        assert "launchctl kickstart -k gui/" in step

    def test_next_step_audit_when_daemon_fine(self):
        text, _ = format_report([_c(OK, "демон"), _c(WARN, "аудит", "не размечен")])
        step = text.splitlines()[-1]
        assert "15 минут" in step

    def test_all_ok_says_system_alive(self):
        text, code = format_report([_c(OK), _c(OK)])
        assert code == 0
        assert "жива" in text.splitlines()[-1]

    def test_every_check_line_present(self):
        text, _ = format_report([_c(OK, "a", "1"), _c(WARN, "b", "2")])
        assert "ok   — a: 1" in text
        assert "warn — b: 2" in text


# =============================================================================
# collect_checks + run_doctor (integration on a tmp sandbox)
# =============================================================================


@pytest.fixture
def sandbox(tmp_path):
    """A healthy install except: daemon stopped, audit unmarked."""
    bins = [
        _make_bin(tmp_path, "call-signal"),
        _make_bin(tmp_path, "audio-capture"),
        _make_bin(tmp_path, "calendar-peek"),
    ]
    db_path = _full_db(tmp_path)
    status_path = _write_status(
        tmp_path / "status.json", age_seconds=3600, state="stopped"
    )
    plist = tmp_path / "com.user.call-recorder.plist"
    plist.write_text("<plist/>")
    audit = tmp_path / "precision-audit.md"
    audit.write_text(_audit_md(["_", "_"]), encoding="utf-8")
    return {
        "bins": bins,
        "ping": lambda: True,
        "db_path": db_path,
        "status_path": status_path,
        "plist_path": plist,
        "calendar_bin": bins[2],
        "audit_path": audit,
        "now": NOW,
    }


class TestCollectChecks:
    def test_known_warns_no_fails(self, sandbox):
        checks = collect_checks(**sandbox)
        assert [c.status for c in checks].count(FAIL) == 0
        warn_components = [c.component for c in checks if c.status == WARN]
        assert "демон" in warn_components
        assert "LaunchAgent" in warn_components
        assert "аудит" in warn_components

    def test_order_binaries_first_audit_last(self, sandbox):
        checks = collect_checks(**sandbox)
        assert checks[0].component == "bin/call-signal"
        assert checks[-1].component == "аудит"


class TestRunDoctor:
    def test_exit_zero_with_known_warns(self, sandbox):
        out = []
        code = run_doctor(print_fn=out.append, **sandbox)
        assert code == 0
        text = "\n".join(out)
        assert "6 ok, 3 warn, 0 fail" in text
        assert "launchctl kickstart -k gui/" in text

    def test_exit_one_on_fail(self, sandbox):
        sandbox["db_path"] = sandbox["db_path"].parent / "nope.db"
        out = []
        code = run_doctor(print_fn=out.append, **sandbox)
        assert code == 1


# =============================================================================
# CLI routing: cli.py doctor
# =============================================================================


class TestCliDoctor:
    def test_doctor_runs_before_database_and_exits_with_code(self, monkeypatch):
        """doctor must not construct Database(): auto-migration would make
        the schema check vacuous."""
        import cli

        monkeypatch.setattr(sys, "argv", ["cli.py", "doctor"])
        with (
            patch("src.doctor.run_doctor", return_value=0) as rd,
            patch("cli.Database") as db_cls,
        ):
            with pytest.raises(SystemExit) as exc:
                cli.main()
        assert exc.value.code == 0
        rd.assert_called_once()
        db_cls.assert_not_called()

    def test_doctor_propagates_exit_one(self, monkeypatch):
        import cli

        monkeypatch.setattr(sys, "argv", ["cli.py", "doctor"])
        with patch("src.doctor.run_doctor", return_value=1):
            with pytest.raises(SystemExit) as exc:
                cli.main()
        assert exc.value.code == 1

    def test_help_mentions_doctor(self, monkeypatch, capsys):
        import cli

        monkeypatch.setattr(sys, "argv", ["cli.py"])
        with pytest.raises(SystemExit):
            cli.main()
        assert "doctor" in capsys.readouterr().out
