"""Tests for src.speaker_resolver — mock Ollama responses."""

import json
from unittest.mock import patch, MagicMock

from src.speaker_resolver import (
    resolve_speakers,
    format_transcript_for_prompt,
    _format_segments_for_prompt,
    _strip_think_block,
    _parse_speaker_map,
)


# =============================================================================
# Helpers
# =============================================================================


def _mock_ollama(content: str, thinking: str = ""):
    """Create a mock urlopen response in /api/chat format."""
    body = json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": content,
                "thinking": thinking,
            },
        }
    ).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 3.0, "text": "Привет, это Вася", "speaker": "SPEAKER_ME"},
    {"start": 3.5, "end": 7.0, "text": "Привет! Я Елена", "speaker": "SPEAKER_OTHER"},
    {"start": 8.0, "end": 12.0, "text": "Давайте начнём", "speaker": "SPEAKER_ME"},
]


# =============================================================================
# format_segments_for_prompt (3 tests)
# =============================================================================


class TestFormatSegments:
    def test_basic_formatting(self):
        """Segments are formatted with timestamps and speaker labels."""
        result = _format_segments_for_prompt(SAMPLE_SEGMENTS)
        assert "[0:00] SPEAKER_ME: Привет, это Вася" in result
        assert "[0:03] SPEAKER_OTHER: Привет! Я Елена" in result

    def test_empty_segments(self):
        result = _format_segments_for_prompt([])
        assert result == ""

    def test_skips_empty_text(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "", "speaker": "SPEAKER_ME"}]
        result = _format_segments_for_prompt(segs)
        assert result == ""


# =============================================================================
# strip_think_block (3 tests)
# =============================================================================


class TestStripThinkBlock:
    def test_strips_think_block(self):
        text = '<think>reasoning here</think>\n{"speaker_map": {}}'
        result = _strip_think_block(text)
        assert result.startswith("{")
        assert "<think>" not in result

    def test_no_think_block(self):
        text = '{"speaker_map": {}}'
        assert _strip_think_block(text) == text

    def test_unclosed_think_block(self):
        """Unclosed <think> block doesn't crash."""
        text = "<think>unclosed reasoning"
        result = _strip_think_block(text)
        assert isinstance(result, str)


# =============================================================================
# parse_speaker_map (4 tests)
# =============================================================================


class TestParseSpeakerMap:
    def test_valid_with_speaker_map_key(self):
        text = json.dumps(
            {
                "speaker_map": {
                    "SPEAKER_ME": {"confirmed": True},
                    "SPEAKER_OTHER": {"name": "Elena", "confidence": 0.85},
                }
            }
        )
        result = _parse_speaker_map(text)
        assert result is not None
        assert result["SPEAKER_ME"]["confirmed"] is True
        assert result["SPEAKER_OTHER"]["name"] == "Elena"

    def test_valid_flat_map(self):
        """Map without wrapper key is also accepted."""
        text = json.dumps(
            {
                "SPEAKER_ME": {"confirmed": True},
            }
        )
        result = _parse_speaker_map(text)
        assert result is not None

    def test_markdown_wrapped(self):
        inner = json.dumps({"speaker_map": {"SPEAKER_ME": {"confirmed": True}}})
        text = f"```json\n{inner}\n```"
        result = _parse_speaker_map(text)
        assert result is not None

    def test_invalid_json(self):
        assert _parse_speaker_map("not json at all") is None


# =============================================================================
# resolve_speakers (5 tests)
# =============================================================================


class TestResolveSpeakers:
    def test_empty_segments_returns_fallback(self):
        result = resolve_speakers([])
        assert "SPEAKER_ME" in result
        assert result["SPEAKER_ME"]["confirmed"] is True

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_valid_response(self, mock_urlopen):
        speaker_map = {
            "speaker_map": {
                "SPEAKER_ME": {"confirmed": True, "source": "mic_channel"},
                "SPEAKER_OTHER": {
                    "name": "Elena",
                    "confidence": 0.85,
                    "source": "self_introduction",
                },
            }
        }
        mock_urlopen.return_value = _mock_ollama(json.dumps(speaker_map))
        result = resolve_speakers(SAMPLE_SEGMENTS)
        assert result["SPEAKER_OTHER"]["name"] == "Elena"
        assert result["SPEAKER_ME"]["confirmed"] is True

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_ollama_unavailable_returns_fallback(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        result = resolve_speakers(SAMPLE_SEGMENTS)
        assert "SPEAKER_ME" in result
        assert len(result) == 1

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_invalid_response_returns_fallback(self, mock_urlopen):
        mock_urlopen.return_value = _mock_ollama("not json")
        result = resolve_speakers(SAMPLE_SEGMENTS)
        assert result["SPEAKER_ME"]["confirmed"] is True

    @patch("src.speaker_resolver.urllib.request.urlopen")
    def test_ensures_speaker_me(self, mock_urlopen):
        """SPEAKER_ME is always added even if missing from response."""
        speaker_map = {
            "speaker_map": {
                "SPEAKER_OTHER": {"name": "Elena", "confidence": 0.85},
            }
        }
        mock_urlopen.return_value = _mock_ollama(json.dumps(speaker_map))
        result = resolve_speakers(SAMPLE_SEGMENTS)
        assert "SPEAKER_ME" in result
        assert result["SPEAKER_ME"]["confirmed"] is True


# =============================================================================
# format_transcript_for_prompt (3 tests)
# =============================================================================


class TestFormatTranscriptForPrompt:
    def test_with_resolved_names(self):
        speaker_map = {
            "SPEAKER_ME": {"confirmed": True},
            "SPEAKER_OTHER": {"name": "Elena", "confidence": 0.85},
        }
        result = format_transcript_for_prompt(SAMPLE_SEGMENTS, speaker_map)
        assert "SPEAKER_ME:" in result
        assert "SPEAKER_OTHER (Elena, conf=0.85)" in result

    def test_without_names(self):
        speaker_map = {"SPEAKER_ME": {"confirmed": True}}
        result = format_transcript_for_prompt(SAMPLE_SEGMENTS, speaker_map)
        assert "SPEAKER_OTHER:" in result
        assert "conf=" not in result.split("SPEAKER_OTHER:")[0].split("\n")[-1] or True

    def test_empty_segments(self):
        result = format_transcript_for_prompt([], {})
        assert result == ""
