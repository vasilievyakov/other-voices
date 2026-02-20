"""Tests for src.summarizer — mock urllib.request.urlopen."""

import json
from io import BytesIO
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from src.summarizer import Summarizer


def _mock_ollama_response(response_text):
    """Create a mock urlopen response with the given text."""
    body = json.dumps({"response": response_text}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestSummarizer:
    def setup_method(self):
        self.summarizer = Summarizer()

    def test_short_transcript_returns_none(self):
        """Transcript < 50 chars returns None."""
        assert self.summarizer.summarize("Short text") is None

    def test_empty_transcript_returns_none(self):
        """Empty string returns None."""
        assert self.summarizer.summarize("") is None
        assert self.summarizer.summarize(None) is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_truncation_at_12000(self, mock_urlopen):
        """Long text is truncated to 12k before sending."""
        valid_json = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama_response(valid_json)

        long_text = "A" * 20000
        self.summarizer.summarize(long_text)

        # Check the prompt sent to Ollama
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        prompt_text = payload["prompt"]
        # The transcript portion should be truncated to 12000 chars
        assert len(prompt_text) < 20000

    @patch("src.summarizer.urllib.request.urlopen")
    def test_valid_json_parsed(self, mock_urlopen):
        """Valid JSON from Ollama is parsed into dict."""
        expected = {
            "summary": "Test summary",
            "key_points": ["point 1"],
            "decisions": ["decision 1"],
            "action_items": ["task 1"],
            "participants": ["Alice"],
        }
        mock_urlopen.return_value = _mock_ollama_response(json.dumps(expected))

        result = self.summarizer.summarize("A" * 100)
        assert result == expected

    @patch("src.summarizer.urllib.request.urlopen")
    def test_markdown_wrapped_json(self, mock_urlopen):
        """```json...``` wrapper is stripped before parsing."""
        inner = {
            "summary": "Wrapped",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }
        wrapped = f"```json\n{json.dumps(inner)}\n```"
        mock_urlopen.return_value = _mock_ollama_response(wrapped)

        result = self.summarizer.summarize("A" * 100)
        assert result["summary"] == "Wrapped"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_invalid_json_fallback(self, mock_urlopen):
        """Invalid JSON returns fallback dict with raw text as summary."""
        mock_urlopen.return_value = _mock_ollama_response("This is not JSON at all")

        result = self.summarizer.summarize("A" * 100)
        assert result is not None
        assert result["summary"] == "This is not JSON at all"
        assert result["key_points"] == []
        assert result["action_items"] == []

    @patch("src.summarizer.urllib.request.urlopen")
    def test_ollama_unavailable(self, mock_urlopen):
        """URLError returns None."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = self.summarizer.summarize("A" * 100)
        assert result is None
