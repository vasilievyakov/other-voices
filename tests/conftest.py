"""Shared fixtures for call-recorder enterprise tests."""

import json
from datetime import datetime, timedelta

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.database import Database


def _dt(days_ago, hour, minute=0):
    """Return datetime `days_ago` days before today at given hour."""
    return (
        datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        - timedelta(days=days_ago)
    )


# Deterministic session IDs / timestamps derived from "yesterday" and "2 days ago"
# so that days=365 filters always include them.
_d1 = _dt(1, 10)  # yesterday 10:00
_d2 = _dt(1, 14)  # yesterday 14:00
_d3 = _dt(2, 9)   # 2 days ago 09:00
_d4 = _dt(1, 12)  # yesterday 12:00

SID1 = _d1.strftime("%Y%m%d_%H%M%S")  # Zoom call with action items
SID2 = _d2.strftime("%Y%m%d_%H%M%S")  # Google Meet (no action items)
SID3 = _d3.strftime("%Y%m%d_%H%M%S")  # Telegram (no transcript)
SID4 = _d4.strftime("%Y%m%d_%H%M%S")  # sample_session


@pytest.fixture
def tmp_db(tmp_path):
    """Clean database on a temp path."""
    return Database(db_path=tmp_path / "test.db")


@pytest.fixture
def populated_db(tmp_db):
    """Database pre-loaded with 3 calls spanning 2 days."""
    calls = [
        {
            "session_id": SID1,
            "app_name": "Zoom",
            "started_at": _d1.isoformat(),
            "ended_at": (_d1 + timedelta(minutes=30)).isoformat(),
            "duration_seconds": 1800.0,
            "system_wav_path": f"/rec/{SID1}/system.wav",
            "mic_wav_path": f"/rec/{SID1}/mic.wav",
            "transcript": "Обсудили запуск проекта Альфа и распределили задачи между командой",
            "summary": {
                "summary": "Обсудили запуск проекта Альфа",
                "key_points": ["Дедлайн через месяц"],
                "decisions": ["Используем Python"],
                "action_items": ["Написать ТЗ (@Вася, пятница)"],
                "participants": ["Вася", "Петя"],
            },
        },
        {
            "session_id": SID2,
            "app_name": "Google Meet",
            "started_at": _d2.isoformat(),
            "ended_at": (_d2 + timedelta(minutes=15)).isoformat(),
            "duration_seconds": 900.0,
            "system_wav_path": None,
            "mic_wav_path": None,
            "transcript": "Quick sync about deployment pipeline and staging environment",
            "summary": {
                "summary": "Quick sync about deployment",
                "key_points": ["Staging ready"],
                "decisions": [],
                "action_items": [],
                "participants": ["Alice"],
            },
        },
        {
            "session_id": SID3,
            "app_name": "Telegram",
            "started_at": _d3.isoformat(),
            "ended_at": (_d3 + timedelta(minutes=5)).isoformat(),
            "duration_seconds": 300.0,
            "system_wav_path": None,
            "mic_wav_path": None,
            "transcript": None,
            "summary": None,
        },
    ]
    for c in calls:
        tmp_db.insert_call(**c)
    return tmp_db


@pytest.fixture
def sample_session(tmp_path):
    """Session dict as returned by recorder.stop()."""
    session_dir = tmp_path / SID4
    session_dir.mkdir()
    return {
        "session_id": SID4,
        "app_name": "Zoom",
        "started_at": _d4.isoformat(),
        "ended_at": (_d4 + timedelta(minutes=45)).isoformat(),
        "duration_seconds": 2700.0,
        "session_dir": str(session_dir),
        "system_wav": str(session_dir / "system.wav"),
        "mic_wav": str(session_dir / "mic.wav"),
    }


@pytest.fixture
def sample_summary():
    """Summary dict as returned by Ollama."""
    return {
        "summary": "Обсудили архитектуру нового сервиса",
        "key_points": ["Микросервисы", "gRPC"],
        "decisions": ["Используем Go"],
        "action_items": ["Подготовить RFC (@Вася)"],
        "participants": ["Вася", "Маша"],
    }


def make_proc(name, pid=1000, connections=None):
    """Helper to create mock psutil process objects."""
    proc = MagicMock()
    proc.info = {"name": name}
    proc.pid = pid
    if connections is not None:
        proc.net_connections.return_value = connections
    else:
        proc.net_connections.return_value = []
    return proc


def make_conn(ip, port=12345):
    """Create a mock UDP connection with remote address."""
    conn = MagicMock()
    conn.raddr = MagicMock()
    conn.raddr.ip = ip
    conn.raddr.port = port
    return conn


def make_conn_no_raddr():
    """Create a mock UDP connection without remote address (listening socket)."""
    conn = MagicMock()
    conn.raddr = None
    return conn


@pytest.fixture(autouse=True)
def _no_live_commitments_llm(monkeypatch):
    """Unit tests must never call the live Ollama from commitments2.

    Tests that need extraction behavior inject an llm stub explicitly or
    patch src.daemon.extract_commitments."""
    import src.commitments2 as c2

    monkeypatch.setattr(c2, "_call_llm", lambda prompt, temperature=0.25: None)
