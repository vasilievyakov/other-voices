"""Shared fixtures for call-recorder enterprise tests."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.database import Database


@pytest.fixture
def tmp_db(tmp_path):
    """Clean database on a temp path."""
    return Database(db_path=tmp_path / "test.db")


@pytest.fixture
def populated_db(tmp_db):
    """Database pre-loaded with 3 calls spanning 2 days."""
    calls = [
        {
            "session_id": "20250220_100000",
            "app_name": "Zoom",
            "started_at": "2025-02-20T10:00:00",
            "ended_at": "2025-02-20T10:30:00",
            "duration_seconds": 1800.0,
            "system_wav_path": "/rec/20250220_100000/system.wav",
            "mic_wav_path": "/rec/20250220_100000/mic.wav",
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
            "session_id": "20250220_140000",
            "app_name": "Google Meet",
            "started_at": "2025-02-20T14:00:00",
            "ended_at": "2025-02-20T14:15:00",
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
            "session_id": "20250219_090000",
            "app_name": "Telegram",
            "started_at": "2025-02-19T09:00:00",
            "ended_at": "2025-02-19T09:05:00",
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
    session_dir = tmp_path / "20250220_120000"
    session_dir.mkdir()
    return {
        "session_id": "20250220_120000",
        "app_name": "Zoom",
        "started_at": "2025-02-20T12:00:00",
        "ended_at": "2025-02-20T12:45:00",
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
