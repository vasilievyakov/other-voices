"""Tests for src.commitment_extractor — mock Ollama responses."""

import json
from unittest.mock import patch, MagicMock

from src.commitment_extractor import (
    extract_commitments,
    list_prompts,
    _build_full_prompt,
    _parse_json,
    _call_ollama,
    _deduplicate_commitments,
)


# =============================================================================
# Helpers
# =============================================================================


def _mock_ollama(content: str):
    """Create a mock urlopen response in /api/chat format."""
    body = json.dumps(
        {
            "message": {"role": "assistant", "content": content},
        }
    ).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


SAMPLE_SPEAKER_MAP = {
    "SPEAKER_ME": {"confirmed": True, "source": "mic_channel"},
    "SPEAKER_OTHER": {"name": "Elena", "confidence": 0.85},
}

VALID_KARPATHY_RESPONSE = json.dumps(
    {
        "commitments": [
            {
                "id": 1,
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "who_name": None,
                "to_whom": "SPEAKER_OTHER",
                "to_whom_name": "Elena",
                "what": "Send revised proposal",
                "deadline": "к пятнице",
                "quote": "Я отправлю тебе предложение к пятнице",
                "timestamp": "00:03:42",
                "uncertain": False,
            }
        ]
    }
)

VALID_MURATI_RESPONSE = json.dumps(
    {
        "commitments": [
            {
                "id": 1,
                "direction": "incoming",
                "committer_label": "SPEAKER_OTHER",
                "committer_name": "Elena",
                "recipient_label": "SPEAKER_ME",
                "recipient_name": None,
                "commitment_text": "Review the document",
                "verbatim_quote": "Я посмотрю документ",
                "timestamp": "00:05:10",
                "deadline_raw": None,
                "deadline_type": "none",
                "commitment_confidence": 0.8,
                "conditional": False,
                "condition_text": None,
            }
        ],
        "extraction_notes": "",
    }
)


# =============================================================================
# _build_full_prompt (3 tests)
# =============================================================================


class TestBuildPrompt:
    def test_includes_all_parts(self):
        result = _build_full_prompt(
            "Find commitments.",
            "transcript text here",
            SAMPLE_SPEAKER_MAP,
            "2025-02-20",
        )
        assert "Find commitments." in result
        assert "SPEAKER MAP" in result
        assert "Elena" in result
        assert "CALL DATE: 2025-02-20" in result
        assert "TRANSCRIPT:" in result
        assert "transcript text here" in result

    def test_none_date(self):
        result = _build_full_prompt("prompt", "text", {}, None)
        assert "CALL DATE: unknown" in result

    def test_empty_speaker_map(self):
        result = _build_full_prompt("prompt", "text", {}, "2025-01-01")
        assert "SPEAKER MAP" in result


# =============================================================================
# _parse_json (5 tests)
# =============================================================================


class TestParseJson:
    def test_valid_json(self):
        result = _parse_json(VALID_KARPATHY_RESPONSE)
        assert result is not None
        assert len(result["commitments"]) == 1

    def test_strips_think_block(self):
        text = f"<think>reasoning</think>\n{VALID_KARPATHY_RESPONSE}"
        result = _parse_json(text)
        assert result is not None
        assert len(result["commitments"]) == 1

    def test_strips_markdown(self):
        text = f"```json\n{VALID_KARPATHY_RESPONSE}\n```"
        result = _parse_json(text)
        assert result is not None

    def test_invalid_json(self):
        assert _parse_json("not json at all") is None

    def test_missing_commitments_key(self):
        """JSON dict without 'commitments' key is rejected."""
        assert _parse_json('{"summary": "test"}') is None


# =============================================================================
# extract_commitments (6 tests)
# =============================================================================


TRANSCRIPT_100 = "SPEAKER_ME [00:01:00]: " + "A" * 80  # >50 chars for validation


class TestExtractCommitments:
    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_karpathy_success(self, mock_urlopen):
        """First attempt (Karpathy) succeeds."""
        mock_urlopen.return_value = _mock_ollama(VALID_KARPATHY_RESPONSE)
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert len(result["commitments"]) == 1
        assert result["commitments"][0]["what"] == "Send revised proposal"

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_karpathy_fails_murati_succeeds(self, mock_urlopen):
        """Karpathy returns invalid JSON, falls back to Murati."""
        mock_urlopen.side_effect = [
            _mock_ollama("invalid json garbage"),
            _mock_ollama(VALID_MURATI_RESPONSE),
        ]
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert len(result["commitments"]) == 1

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_both_fail(self, mock_urlopen):
        """Both prompts fail → empty commitments list."""
        mock_urlopen.return_value = _mock_ollama("not json")
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert result["commitments"] == []
        assert "extraction_notes" in result

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_ollama_unavailable(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert result["commitments"] == []
        assert "unavailable" in result.get("extraction_notes", "").lower()

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_empty_commitments_list(self, mock_urlopen):
        """Model returns empty commitments list → accepted."""
        mock_urlopen.return_value = _mock_ollama(json.dumps({"commitments": []}))
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert result["commitments"] == []

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_murati_format_accepted(self, mock_urlopen):
        """Murati format (direction instead of type) is valid."""
        mock_urlopen.return_value = _mock_ollama(VALID_MURATI_RESPONSE)
        result = extract_commitments(TRANSCRIPT_100, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert len(result["commitments"]) == 1
        assert result["commitments"][0]["direction"] == "incoming"


# =============================================================================
# list_prompts (2 tests)
# =============================================================================


class TestListPrompts:
    def test_returns_two_prompts(self):
        prompts = list_prompts()
        assert len(prompts) == 2

    def test_prompt_names(self):
        prompts = list_prompts()
        names = [p["name"] for p in prompts]
        assert "karpathy" in names
        assert "murati" in names


# =============================================================================
# _deduplicate_commitments (4 tests)
# =============================================================================


class TestDeduplicateCommitments:
    def test_removes_exact_duplicates(self):
        commitments = [
            {"what": "Send proposal", "who": "SPEAKER_ME", "to_whom": "SPEAKER_OTHER"},
            {"what": "Send proposal", "who": "SPEAKER_ME", "to_whom": "SPEAKER_OTHER"},
        ]
        result = _deduplicate_commitments(commitments)
        assert len(result) == 1

    def test_keeps_different_commitments(self):
        commitments = [
            {"what": "Send proposal", "who": "SPEAKER_ME", "to_whom": "SPEAKER_OTHER"},
            {
                "what": "Review document",
                "who": "SPEAKER_OTHER",
                "to_whom": "SPEAKER_ME",
            },
        ]
        result = _deduplicate_commitments(commitments)
        assert len(result) == 2

    def test_case_insensitive(self):
        commitments = [
            {"what": "Send Proposal", "who": "SPEAKER_ME", "to_whom": "SPEAKER_OTHER"},
            {"what": "send proposal", "who": "SPEAKER_ME", "to_whom": "SPEAKER_OTHER"},
        ]
        result = _deduplicate_commitments(commitments)
        assert len(result) == 1

    def test_murati_format_dedup(self):
        """Deduplication works with Murati field names too."""
        commitments = [
            {
                "commitment_text": "Review doc",
                "committer_label": "A",
                "recipient_label": "B",
            },
            {
                "commitment_text": "Review doc",
                "committer_label": "A",
                "recipient_label": "B",
            },
            {
                "commitment_text": "Send file",
                "committer_label": "B",
                "recipient_label": "A",
            },
        ]
        result = _deduplicate_commitments(commitments)
        assert len(result) == 2


# =============================================================================
# extract_commitments — chunked (4 tests)
# =============================================================================


class TestExtractCommitmentsChunked:
    def _make_long_transcript(self, chars: int = 60000) -> str:
        """Create a transcript longer than CHUNK_MAX_CHARS."""
        line = "SPEAKER_ME [00:01:00]: Это строка транскрипта для тестирования.\n"
        repeats = chars // len(line) + 1
        return line * repeats

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_long_transcript_chunked(self, mock_urlopen):
        """Transcript >25K chars is split and processed in chunks."""
        mock_urlopen.return_value = _mock_ollama(VALID_KARPATHY_RESPONSE)
        transcript = self._make_long_transcript(60000)
        result = extract_commitments(transcript, SAMPLE_SPEAKER_MAP, "2025-02-20")
        assert "_chunks" in result
        assert result["_chunks"] >= 2
        assert len(result["commitments"]) >= 1

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_short_transcript_not_chunked(self, mock_urlopen):
        """Transcript <25K chars is processed in one pass."""
        mock_urlopen.return_value = _mock_ollama(VALID_KARPATHY_RESPONSE)
        result = extract_commitments(
            "short transcript text", SAMPLE_SPEAKER_MAP, "2025-02-20"
        )
        assert "_chunks" not in result

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_chunked_deduplicates(self, mock_urlopen):
        """Same commitment from overlapping chunks is deduplicated."""
        mock_urlopen.return_value = _mock_ollama(VALID_KARPATHY_RESPONSE)
        transcript = self._make_long_transcript(60000)
        result = extract_commitments(transcript, SAMPLE_SPEAKER_MAP, "2025-02-20")
        # Each chunk returns the same commitment — should be deduplicated
        assert len(result["commitments"]) == 1
        assert result["commitments"][0]["id"] == 1

    @patch("src.commitment_extractor.urllib.request.urlopen")
    def test_chunked_ids_sequential(self, mock_urlopen):
        """Commitment IDs are sequential after merge."""
        # Different commitments per chunk so they don't get deduped
        resp_a = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "what": "Send proposal",
                        "who": "SPEAKER_ME",
                        "to_whom": "SPEAKER_OTHER",
                    },
                ]
            }
        )
        resp_b = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "what": "Review document",
                        "who": "SPEAKER_OTHER",
                        "to_whom": "SPEAKER_ME",
                    },
                ]
            }
        )
        resp_c = json.dumps(
            {
                "commitments": [
                    {
                        "id": 1,
                        "what": "Schedule meeting",
                        "who": "SPEAKER_ME",
                        "to_whom": "SPEAKER_OTHER",
                    },
                ]
            }
        )
        # 60K = ~3 chunks, each gets one karpathy attempt
        mock_urlopen.side_effect = [
            _mock_ollama(resp_a),
            _mock_ollama(resp_b),
            _mock_ollama(resp_c),
        ]
        transcript = self._make_long_transcript(60000)
        result = extract_commitments(transcript, SAMPLE_SPEAKER_MAP, "2025-02-20")
        ids = [c["id"] for c in result["commitments"]]
        assert ids == list(range(1, len(ids) + 1))
        assert len(ids) == 3

    def test_empty_transcript(self):
        """Empty or very short transcript returns early."""
        result = extract_commitments("", {})
        assert result["commitments"] == []
        assert "too short" in result.get("extraction_notes", "")
