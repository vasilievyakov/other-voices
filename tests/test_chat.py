"""Tests for src.chat — ChatEngine with mocked Ollama."""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.chat import ChatEngine
from src.database import Database


@pytest.fixture
def chat_db(tmp_path):
    """Database with a sample call for chat tests."""
    db = Database(db_path=tmp_path / "chat_test.db")
    db.insert_call(
        session_id="chat1",
        app_name="Zoom",
        started_at="2025-02-20T10:00:00",
        ended_at="2025-02-20T10:30:00",
        duration_seconds=1800.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript="We discussed the quarterly plan. Vasya will handle the deployment by Friday.",
        summary={
            "summary": "Discussed quarterly plan",
            "action_items": ["Deploy by Friday (@Vasya)"],
        },
    )
    return db


@pytest.fixture
def engine(chat_db):
    return ChatEngine(db=chat_db)


# =============================================================================
# Context Building (4 tests)
# =============================================================================


class TestContextBuilding:
    def test_build_context_for_call(self, engine):
        """Per-call context includes transcript and summary."""
        ctx = engine._build_context(session_id="chat1")
        assert "quarterly plan" in ctx
        assert "Zoom" in ctx

    def test_build_context_missing_call(self, engine):
        """Missing session returns error message."""
        ctx = engine._build_context(session_id="nonexistent")
        assert "No call found" in ctx

    def test_build_context_global_search(self, engine):
        """Global context searches across calls."""
        ctx = engine._build_context(query="quarterly")
        assert "quarterly" in ctx

    def test_build_context_global_no_results(self, engine):
        """Global search with no results."""
        ctx = engine._build_context(query="xyznonexistent")
        assert "No relevant calls" in ctx


# =============================================================================
# Ask (5 tests)
# =============================================================================


class TestAsk:
    @patch("src.chat.urllib.request.urlopen")
    def test_ask_returns_answer(self, mock_urlopen, engine):
        """Successful ask returns answer string."""
        response = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "Vasya will deploy by Friday.",
                }
            }
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        answer = engine.ask("What did Vasya promise?", session_id="chat1")
        assert answer == "Vasya will deploy by Friday."

    @patch("src.chat.urllib.request.urlopen")
    def test_ask_saves_messages(self, mock_urlopen, engine, chat_db):
        """Ask saves both user and assistant messages to DB."""
        response = json.dumps(
            {"message": {"role": "assistant", "content": "The answer."}}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        engine.ask("Question?", session_id="chat1")

        messages = chat_db.get_chat_messages("chat1", scope="call")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Question?"
        assert messages[1]["role"] == "assistant"

    @patch("src.chat.urllib.request.urlopen")
    def test_ask_ollama_error(self, mock_urlopen, engine):
        """Ollama unavailable returns None."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        answer = engine.ask("Question?", session_id="chat1")
        assert answer is None

    @patch("src.chat.urllib.request.urlopen")
    def test_ask_empty_response(self, mock_urlopen, engine):
        """Empty Ollama response returns None."""
        response = json.dumps(
            {"message": {"role": "assistant", "content": ""}}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        answer = engine.ask("Question?", session_id="chat1")
        assert answer is None

    @patch("src.chat.urllib.request.urlopen")
    def test_ask_global_scope(self, mock_urlopen, engine, chat_db):
        """Global ask uses 'global' scope for messages."""
        response = json.dumps(
            {"message": {"role": "assistant", "content": "Global answer."}}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        engine.ask("Global question?")

        # Global messages are stored with scope='global'
        messages = chat_db.get_chat_messages(None, scope="global")
        assert len(messages) == 2


# =============================================================================
# Chat History (3 tests)
# =============================================================================


class TestChatHistory:
    def test_empty_history(self, engine):
        """No messages returns empty list."""
        history = engine._get_history("chat1", "call")
        assert history == []

    def test_history_loaded(self, engine, chat_db):
        """Previously saved messages are loaded into history."""
        chat_db.insert_chat_message("chat1", "user", "First question", "call")
        chat_db.insert_chat_message("chat1", "assistant", "First answer", "call")

        history = engine._get_history("chat1", "call")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_clear_chat(self, engine, chat_db):
        """Clear chat removes all messages for session."""
        chat_db.insert_chat_message("chat1", "user", "Q", "call")
        chat_db.insert_chat_message("chat1", "assistant", "A", "call")

        chat_db.clear_chat("chat1")
        messages = chat_db.get_chat_messages("chat1", "call")
        assert messages == []
