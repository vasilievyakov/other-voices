"""Tests for src.summarizer — mock urllib.request.urlopen.

Enterprise coverage: input validation, output parsing, resilience, templates.
"""

import json
from io import BytesIO
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from src.summarizer import Summarizer


def _mock_ollama(response_text):
    """Create a mock urlopen response in /api/chat format."""
    body = json.dumps(
        {
            "message": {"role": "assistant", "content": response_text},
        }
    ).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# =============================================================================
# Input Validation (5 tests)
# =============================================================================


class TestSummarizerInput:
    def setup_method(self):
        self.summarizer = Summarizer()

    def test_none_returns_none(self):
        """None transcript returns None."""
        assert self.summarizer.summarize(None) is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert self.summarizer.summarize("") is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only transcript returns None."""
        assert self.summarizer.summarize("   \n\t  ") is None

    def test_short_transcript_returns_none(self):
        """Transcript < 50 chars (stripped) returns None."""
        assert self.summarizer.summarize("Short text under fifty") is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_exactly_50_chars_proceeds(self, mock_urlopen):
        """Transcript of exactly 50 chars (stripped) calls Ollama."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        text = "A" * 50
        result = self.summarizer.summarize(text)
        assert result is not None
        mock_urlopen.assert_called_once()


# =============================================================================
# Output Parsing (7 tests)
# =============================================================================


class TestSummarizerOutput:
    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_valid_json_parsed(self, mock_urlopen):
        """Valid JSON from Ollama is parsed into dict (plus additive coverage)."""
        expected = {
            "summary": "Test summary",
            "key_points": ["point 1"],
            "decisions": ["decision 1"],
            "action_items": ["task 1"],  # no @owner → survives validation
            "participants": ["Alice"],
        }
        mock_urlopen.return_value = _mock_ollama(json.dumps(expected))
        result = self.summarizer.summarize("A" * 100)
        # summarize adds the additive "coverage" key; strip it for comparison.
        assert result["coverage"] == "full"
        result_wo_coverage = {k: v for k, v in result.items() if k != "coverage"}
        assert result_wo_coverage == expected

    @patch("src.summarizer.urllib.request.urlopen")
    def test_markdown_json_wrapper_stripped(self, mock_urlopen):
        """```json ... ``` wrapper is stripped before parsing."""
        inner = {
            "summary": "Wrapped",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }
        wrapped = f"```json\n{json.dumps(inner)}\n```"
        mock_urlopen.return_value = _mock_ollama(wrapped)
        result = self.summarizer.summarize("A" * 100)
        assert result["summary"] == "Wrapped"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_markdown_wrapper_no_json_tag(self, mock_urlopen):
        """``` ... ``` wrapper without json tag is also stripped."""
        inner = {
            "summary": "Plain wrapped",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "participants": [],
        }
        wrapped = f"```\n{json.dumps(inner)}\n```"
        mock_urlopen.return_value = _mock_ollama(wrapped)
        result = self.summarizer.summarize("A" * 100)
        assert result["summary"] == "Plain wrapped"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_invalid_json_fallback(self, mock_urlopen):
        """Invalid JSON returns fallback dict with raw text as summary."""
        mock_urlopen.return_value = _mock_ollama("This is not JSON at all")
        result = self.summarizer.summarize("A" * 100)
        assert result is not None
        assert result["summary"] == "This is not JSON at all"
        assert result["key_points"] == []
        assert result["decisions"] == []
        assert result["action_items"] == []
        assert result["participants"] == []

    @patch("src.summarizer.urllib.request.urlopen")
    def test_truncation_at_12000(self, mock_urlopen):
        """Long text is truncated to 12k before sending to Ollama."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        long_text = "A" * 60000
        self.summarizer.summarize(long_text)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        prompt = payload["messages"][0]["content"]
        # Prompt includes SUMMARY_PROMPT prefix + transcript (max 50000)
        assert len(prompt) < 60000

    @patch("src.summarizer.urllib.request.urlopen")
    def test_empty_response_returns_none(self, mock_urlopen):
        """Empty Ollama response returns None (no content to parse)."""
        mock_urlopen.return_value = _mock_ollama("")
        result = self.summarizer.summarize("A" * 100)
        assert result is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_cyrillic_json_parsed(self, mock_urlopen):
        """Cyrillic text in JSON response is parsed correctly."""
        expected = {
            "summary": "Обсудили план запуска",
            "key_points": ["Дедлайн в пятницу"],
            "decisions": ["Используем Python"],
            "action_items": ["Написать ТЗ (@Вася)"],
            "participants": ["Вася", "Петя"],
        }
        mock_urlopen.return_value = _mock_ollama(
            json.dumps(expected, ensure_ascii=False)
        )
        result = self.summarizer.summarize("А" * 100)
        assert result["summary"] == "Обсудили план запуска"
        assert result["participants"] == ["Вася", "Петя"]


# =============================================================================
# Resilience (5 tests)
# =============================================================================


class TestSummarizerResilience:
    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_url_error_returns_none(self, mock_urlopen):
        """URLError (Ollama unavailable) returns None."""
        mock_urlopen.side_effect = URLError("Connection refused")
        result = self.summarizer.summarize("A" * 100)
        assert result is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_timeout_error_returns_none(self, mock_urlopen):
        """TimeoutError returns None."""
        mock_urlopen.side_effect = TimeoutError("Request timed out")
        result = self.summarizer.summarize("A" * 100)
        assert result is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_ollama_model_in_request(self, mock_urlopen):
        """Request payload includes correct model name."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert "model" in payload
        assert payload["stream"] is False

    @patch("src.summarizer.urllib.request.urlopen")
    def test_temperature_is_low(self, mock_urlopen):
        """Request uses low temperature for deterministic output."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["options"]["temperature"] <= 0.5

    @patch("src.summarizer.urllib.request.urlopen")
    def test_content_type_json(self, mock_urlopen):
        """Request has Content-Type: application/json header."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100)

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"


# =============================================================================
# Template Integration (5 tests)
# =============================================================================


class TestSummarizerTemplates:
    def setup_method(self):
        self.summarizer = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_backward_compat_default(self, mock_urlopen):
        """summarize(transcript) still works without template_name."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        result = self.summarizer.summarize("A" * 100)
        assert result is not None
        assert result["summary"] == "ok"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_sales_template_sends_prompt(self, mock_urlopen):
        """Sales template changes the prompt sent to Ollama."""
        valid = json.dumps(
            {
                "summary": "ok",
                "objections": [],
                "budget_signals": [],
                "decision_makers": [],
                "next_steps": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        result = self.summarizer.summarize("A" * 100, template_name="sales_call")
        assert result is not None

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert "objections" in payload["messages"][0]["content"]

    @patch("src.summarizer.urllib.request.urlopen")
    def test_non_default_template_num_predict(self, mock_urlopen):
        """Non-default templates use num_predict=16384."""
        valid = json.dumps({"summary": "ok", "participants": []})
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100, template_name="sales_call")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["options"]["num_predict"] == 16384

    @patch("src.summarizer.urllib.request.urlopen")
    def test_default_template_num_predict(self, mock_urlopen):
        """Default template uses num_predict=16384."""
        valid = json.dumps({"summary": "ok", "participants": []})
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["options"]["num_predict"] == 16384

    @patch("src.summarizer.urllib.request.urlopen")
    def test_notes_included_in_prompt(self, mock_urlopen):
        """Notes parameter is included in the prompt."""
        valid = json.dumps({"summary": "ok", "participants": []})
        mock_urlopen.return_value = _mock_ollama(valid)
        self.summarizer.summarize("A" * 100, notes="Focus on deadlines")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert "Focus on deadlines" in payload["messages"][0]["content"]


# =============================================================================
# Chunked Summarization (5 tests)
# =============================================================================


class TestSummarizerChunked:
    def setup_method(self):
        self.summarizer = Summarizer()

    def _make_long_text(self, chars: int = 60000) -> str:
        line = "Speaker A: This is a test line for chunking purposes.\n"
        return line * (chars // len(line) + 1)

    @patch("src.summarizer.urllib.request.urlopen")
    def test_long_transcript_uses_chunks(self, mock_urlopen):
        """Transcript >25K is split into chunks and merged."""
        chunk_summary = json.dumps(
            {
                "summary": "Chunk summary",
                "key_points": ["point 1"],
                "decisions": [],
                "action_items": [],
                "participants": ["Alice"],
            }
        )
        merge_summary = json.dumps(
            {
                "summary": "Merged summary of whole call",
                "key_points": ["point 1"],
                "decisions": [],
                "action_items": [],
                "participants": ["Alice"],
            }
        )
        # First N calls = chunk summaries, last call = merge
        mock_urlopen.side_effect = [
            _mock_ollama(chunk_summary),
            _mock_ollama(chunk_summary),
            _mock_ollama(chunk_summary),
            _mock_ollama(merge_summary),
        ]
        result = self.summarizer.summarize(self._make_long_text(60000))
        assert result is not None
        assert "_chunks" in result
        assert result["summary"] == "Merged summary of whole call"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_short_transcript_single_pass(self, mock_urlopen):
        """Transcript <25K uses single pass (no chunking)."""
        valid = json.dumps(
            {
                "summary": "ok",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        mock_urlopen.return_value = _mock_ollama(valid)
        result = self.summarizer.summarize("A" * 100)
        assert result is not None
        assert "_chunks" not in result

    @patch("src.summarizer.urllib.request.urlopen")
    def test_merge_failure_falls_back_to_mechanical(self, mock_urlopen):
        """If LLM merge fails, mechanical merge is used."""
        chunk_summary = json.dumps(
            {
                "summary": "Chunk 1",
                "key_points": ["point A"],
                "decisions": [],
                "action_items": ["task 1"],
                "participants": ["Alice"],
            }
        )
        # Chunk calls succeed, merge call returns invalid JSON
        mock_urlopen.side_effect = [
            _mock_ollama(chunk_summary),
            _mock_ollama(chunk_summary),
            _mock_ollama(chunk_summary),
            _mock_ollama("not valid json"),
        ]
        result = self.summarizer.summarize(self._make_long_text(60000))
        assert result is not None
        # Mechanical merge concatenates summaries
        assert "Chunk 1" in result["summary"]
        assert "_chunks" in result

    @patch("src.summarizer.urllib.request.urlopen")
    def test_all_chunks_fail_returns_none(self, mock_urlopen):
        """If all chunk summarizations fail, returns None."""
        mock_urlopen.side_effect = URLError("Connection refused")
        result = self.summarizer.summarize(self._make_long_text(60000))
        assert result is None

    @patch("src.summarizer.urllib.request.urlopen")
    def test_single_chunk_succeeds_used_directly(self, mock_urlopen):
        """If only one chunk succeeds out of many, use it as-is."""
        chunk_summary = json.dumps(
            {
                "summary": "Only success",
                "key_points": ["x"],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        )
        # First chunk succeeds, rest fail
        mock_urlopen.side_effect = [
            _mock_ollama(chunk_summary),
            URLError("fail"),
            URLError("fail"),
        ]
        result = self.summarizer.summarize(self._make_long_text(60000))
        assert result is not None
        assert result["summary"] == "Only success"


# =============================================================================
# Coverage Detection & One-Sided Guardrails (anti-hallucination)
# =============================================================================


def _valid(**overrides):
    """Valid summary JSON string with empty lists by default."""
    data = {
        "summary": "ok",
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "participants": [],
        "entities": [],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class TestCoverageDetection:
    def setup_method(self):
        self.s = Summarizer()

    def test_mic_only_detected(self):
        """Transcript with only SPEAKER_ME labels → mic_only."""
        t = "[0:00] SPEAKER_ME: hello\n[0:30] SPEAKER_ME: still talking to myself"
        assert self.s._detect_coverage(t) == "mic_only"

    def test_full_detected_multi_speaker(self):
        """Presence of a non-ME speaker label → full."""
        t = "[0:00] SPEAKER_ME: hi\n[0:30] SPEAKER_1: hello back to you now"
        assert self.s._detect_coverage(t) == "full"

    def test_legacy_speaker_other_is_full(self):
        """Legacy SPEAKER_OTHER counts as the other side → full."""
        t = "[0:00] SPEAKER_ME: hi\n[0:30] SPEAKER_OTHER: yes indeed"
        assert self.s._detect_coverage(t) == "full"

    def test_no_labels_is_full(self):
        """Plain transcript without speaker labels is treated as full."""
        assert (
            self.s._detect_coverage("plain transcript with no speaker labels") == "full"
        )

    def test_empty_is_full(self):
        assert self.s._detect_coverage("") == "full"


class TestCoverageField:
    def setup_method(self):
        self.s = Summarizer()

    @patch("src.summarizer.urllib.request.urlopen")
    def test_coverage_mic_only_added(self, mock_urlopen):
        """Mic-only transcript yields coverage == 'mic_only' in the summary."""
        mock_urlopen.return_value = _mock_ollama(_valid())
        t = "[0:00] SPEAKER_ME: " + "talking to myself here quite a lot today. " * 3
        result = self.s.summarize(t)
        assert result["coverage"] == "mic_only"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_coverage_full_added(self, mock_urlopen):
        """Two-sided transcript yields coverage == 'full'."""
        mock_urlopen.return_value = _mock_ollama(_valid())
        t = (
            "[0:00] SPEAKER_ME: hi there friend\n[0:30] SPEAKER_1: "
            + "hello back. " * 5
        )
        result = self.s.summarize(t)
        assert result["coverage"] == "full"

    @patch("src.summarizer.urllib.request.urlopen")
    def test_one_sided_instruction_in_prompt(self, mock_urlopen):
        """Mic-only transcript injects the one-sided notice into the prompt."""
        mock_urlopen.return_value = _mock_ollama(_valid())
        t = (
            "[0:00] SPEAKER_ME: "
            + "This is an English mic only recording talking. " * 3
        )
        self.s.summarize(t)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        content = payload["messages"][0]["content"]
        assert "ONE-SIDED RECORDING" in content

    @patch("src.summarizer.urllib.request.urlopen")
    def test_full_coverage_no_one_sided_instruction(self, mock_urlopen):
        """Two-sided transcript does NOT inject the one-sided notice."""
        mock_urlopen.return_value = _mock_ollama(_valid())
        t = (
            "[0:00] SPEAKER_ME: hi there friend\n"
            "[0:30] SPEAKER_1: " + "hello back to you here now. " * 3
        )
        self.s.summarize(t)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        content = payload["messages"][0]["content"]
        assert "ONE-SIDED RECORDING" not in content


class TestActionItemOwnerValidation:
    def setup_method(self):
        self.s = Summarizer()

    def test_direct_drop_unattested_owner(self):
        """Owner absent from transcript is dropped."""
        summary = {
            "action_items": ["[0:00] @Ghostface: do x", "[1:00] @SPEAKER_ME: real"]
        }
        transcript = "[0:00] SPEAKER_ME: I will do the real thing myself"
        out = self.s._validate_action_items(summary, transcript)
        assert out["action_items"] == ["[1:00] @SPEAKER_ME: real"]

    def test_direct_keep_attested_name(self):
        """Owner name present in transcript is kept."""
        summary = {"action_items": ["@Anna: send report"]}
        transcript = "Anna said she will send the report tomorrow"
        out = self.s._validate_action_items(summary, transcript)
        assert out["action_items"] == ["@Anna: send report"]

    def test_speaker_label_owner_kept(self):
        """A speaker-label owner counts as attested."""
        summary = {"action_items": ["[2:00] @SPEAKER_1: follow up"]}
        transcript = "[2:00] SPEAKER_1: I will follow up on that"
        out = self.s._validate_action_items(summary, transcript)
        assert out["action_items"] == ["[2:00] @SPEAKER_1: follow up"]

    def test_direct_keep_no_owner(self):
        """Item without an @owner is kept (nothing to validate)."""
        summary = {"action_items": ["prepare the deck by Friday"]}
        out = self.s._validate_action_items(summary, "no owners mentioned here")
        assert out["action_items"] == ["prepare the deck by Friday"]

    def test_empty_action_items_ok(self):
        summary = {"action_items": []}
        out = self.s._validate_action_items(summary, "transcript")
        assert out["action_items"] == []

    def test_non_string_items_kept(self):
        summary = {"action_items": [{"owner": "x"}]}
        out = self.s._validate_action_items(summary, "transcript")
        assert out["action_items"] == [{"owner": "x"}]

    @patch("src.summarizer.urllib.request.urlopen")
    def test_end_to_end_drops_fabricated_owner(self, mock_urlopen):
        """summarize() drops an action item whose owner is not in the transcript."""
        mock_urlopen.return_value = _mock_ollama(
            _valid(
                action_items=[
                    "[0:00] @Ghostface: fabricated task",
                    "[1:00] @SPEAKER_ME: the real one",
                ]
            )
        )
        transcript = "[0:00] SPEAKER_ME: " + "I will handle the real one myself. " * 3
        result = self.s.summarize(transcript)
        joined = " ".join(result["action_items"])
        assert "Ghostface" not in joined
        assert any("SPEAKER_ME" in it for it in result["action_items"])


# =============================================================================
# Structured output — Ollama format schema (primary), string repair (fallback)
# =============================================================================


class TestStructuredOutput:
    @patch("src.summarizer.urllib.request.urlopen")
    def test_payload_carries_json_schema_format(self, mock_urlopen):
        """/api/chat payload must constrain output via a JSON-schema format."""
        mock_urlopen.return_value = _mock_ollama('{"summary": "ok"}')
        s = Summarizer()
        s._call_ollama("prompt")
        request = mock_urlopen.call_args[0][0]
        payload = json.loads(request.data.decode("utf-8"))
        assert "format" in payload
        assert payload["format"]["type"] == "object"
        assert "summary" in payload["format"]["properties"]
        # templates add sections beyond the core keys — must stay allowed
        assert payload["format"].get("additionalProperties", False) is True

    @patch("src.summarizer.urllib.request.urlopen")
    def test_repair_still_works_as_fallback(self, mock_urlopen):
        """Malformed output (old Ollama, no schema support) still repairs."""
        mock_urlopen.return_value = _mock_ollama('{"summary": "ok"} trailing garbage')
        s = Summarizer()
        raw = s._call_ollama("prompt")
        assert s._parse_response(raw) == {"summary": "ok", "_repaired": True}


class TestOwnerValidationViaParticipants:
    def setup_method(self):
        self.s = Summarizer()

    def test_substring_false_accept_now_dropped(self):
        """«Максим» must not be attested by the word «максимум» (substring bug)."""
        summary = {
            "action_items": ["@Максим: собрать отчёт"],
            "participants": ["Вася"],
        }
        transcript = "мы обсуждали максимум затрат на квартал"
        out = self.s._validate_action_items(summary, transcript)
        assert out["action_items"] == []

    def test_owner_matching_participant_kept(self):
        """Owner listed in participants is attested even without transcript hit."""
        summary = {
            "action_items": ["@Максим: собрать отчёт"],
            "participants": ["Максим"],
        }
        out = self.s._validate_action_items(summary, "обсуждение бюджета")
        assert out["action_items"] == ["@Максим: собрать отчёт"]

    def test_owner_matches_token_of_full_name(self):
        """@Яков matches participant «Яков Васильев»."""
        summary = {
            "action_items": ["@Яков: прислать договор"],
            "participants": ["Яков Васильев"],
        }
        out = self.s._validate_action_items(summary, "без имён")
        assert out["action_items"] == ["@Яков: прислать договор"]

    def test_word_boundary_transcript_fallback_keeps(self):
        """No participants list → exact word in transcript still attests."""
        summary = {"action_items": ["@Anna: send report"]}
        transcript = "Anna will send the report"
        out = self.s._validate_action_items(summary, transcript)
        assert out["action_items"] == ["@Anna: send report"]

    def test_word_boundary_rejects_prefix_word(self):
        """No participants → «Максим» not attested by «максимум»."""
        summary = {"action_items": ["@Максим: собрать отчёт"]}
        out = self.s._validate_action_items(summary, "это максимум возможного")
        assert out["action_items"] == []
