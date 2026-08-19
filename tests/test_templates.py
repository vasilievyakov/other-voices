"""Tests for src.templates — template registry and prompt builder."""

import json

from src.templates import (
    TEMPLATES,
    get_template,
    list_templates,
    build_prompt,
    export_templates_json,
    _detect_language,
    _build_json_schema,
    _format_timestamp,
    _format_transcript_with_timestamps,
)


# =============================================================================
# Template Registry (6 tests)
# =============================================================================


class TestTemplateRegistry:
    def test_all_templates_have_required_keys(self):
        """Every template has name, display_name, description, sections."""
        for name, tmpl in TEMPLATES.items():
            assert tmpl["name"] == name
            assert "display_name" in tmpl
            assert "description" in tmpl
            assert isinstance(tmpl["sections"], list)
            assert len(tmpl["sections"]) >= 2

    def test_all_sections_have_required_keys(self):
        """Every section has key, label, type."""
        for name, tmpl in TEMPLATES.items():
            for section in tmpl["sections"]:
                assert "key" in section, f"Missing key in {name}"
                assert "label" in section, f"Missing label in {name}"
                assert section["type"] in ("text", "list"), f"Bad type in {name}"

    def test_default_template_has_standard_sections(self):
        """Default template has the 5 original sections."""
        default = TEMPLATES["default"]
        keys = [s["key"] for s in default["sections"]]
        assert "summary" in keys
        assert "key_points" in keys
        assert "decisions" in keys
        assert "action_items" in keys
        assert "participants" in keys

    def test_get_template_existing(self):
        """get_template returns the template dict."""
        tmpl = get_template("sales_call")
        assert tmpl is not None
        assert tmpl["name"] == "sales_call"

    def test_get_template_nonexistent(self):
        """get_template returns None for unknown name."""
        assert get_template("nonexistent") is None

    def test_list_templates_returns_all(self):
        """list_templates returns all registered templates."""
        templates = list_templates()
        assert len(templates) == len(TEMPLATES)
        names = {t["name"] for t in templates}
        assert "default" in names
        assert "sales_call" in names
        assert "interview" in names


# =============================================================================
# Language Detection (4 tests)
# =============================================================================


class TestLanguageDetection:
    def test_cyrillic_detected(self):
        assert _detect_language("Привет, давайте обсудим проект") == "ru"

    def test_latin_detected(self):
        assert _detect_language("Hello, let's discuss the project") == "en"

    def test_mixed_mostly_cyrillic(self):
        assert _detect_language("Обсудили деплой проекта на стейджинг сервер") == "ru"

    def test_empty_string(self):
        assert _detect_language("") == "en"


# =============================================================================
# Prompt Builder (7 tests)
# =============================================================================


class TestBuildPrompt:
    def test_default_template_contains_transcript(self):
        """Prompt includes the transcript text."""
        prompt = build_prompt("default", "Hello world meeting content")
        assert "Hello world meeting content" in prompt

    def test_default_template_contains_json_schema(self):
        """Prompt includes JSON schema keys from default template."""
        prompt = build_prompt("default", "Some transcript text here enough")
        assert "summary" in prompt
        assert "key_points" in prompt
        assert "action_items" in prompt

    def test_sales_template_has_sales_sections(self):
        """Sales template prompt includes sales-specific keys."""
        prompt = build_prompt("sales_call", "Sales meeting transcript")
        assert "objections" in prompt
        assert "budget_signals" in prompt
        assert "decision_makers" in prompt

    def test_notes_included_in_prompt(self):
        """User notes are included in the prompt."""
        prompt = build_prompt(
            "default", "Transcript here", notes="Focus on action items"
        )
        assert "Focus on action items" in prompt

    def test_no_notes_no_notes_section(self):
        """Without notes, no notes label in prompt."""
        prompt = build_prompt("default", "Transcript here")
        assert "NOTES" not in prompt.upper() or "USER NOTES" not in prompt

    def test_cyrillic_transcript_russian_prompt(self):
        """Cyrillic transcript → Russian-language instructions."""
        prompt = build_prompt(
            "default", "Обсудили запуск проекта и распределили задачи"
        )
        assert "ТРАНСКРИПТ" in prompt

    def test_english_transcript_english_prompt(self):
        """English transcript → English instructions."""
        prompt = build_prompt(
            "default", "We discussed the project launch and assigned tasks"
        )
        assert "TRANSCRIPT" in prompt

    def test_unknown_template_falls_back_to_default(self):
        """Unknown template name falls back to default."""
        prompt = build_prompt("nonexistent_template", "Some transcript")
        assert "summary" in prompt
        assert "key_points" in prompt

    def test_segments_add_timestamps_to_transcript(self):
        """When segments provided, transcript is formatted with [M:SS] markers."""
        segments = [
            {"start": 0.0, "end": 5.2, "text": "Hello everyone"},
            {"start": 5.2, "end": 12.0, "text": "Let's discuss the project"},
        ]
        prompt = build_prompt(
            "default", "Hello everyone Let's discuss the project", segments=segments
        )
        assert "[0:00-0:05]" in prompt
        assert "[0:05-0:12]" in prompt
        assert "Hello everyone" in prompt

    def test_segments_add_citation_instruction(self):
        """When segments provided, the segment citation instruction is included."""
        segments = [{"start": 0.0, "end": 5.0, "text": "test"}]
        prompt = build_prompt(
            "default", "test transcript content here enough", segments=segments
        )
        # Segment-specific citation instruction (distinct from the always-on
        # evidence rules which also mention [MM:SS]).
        assert "Reference them in key_points" in prompt

    def test_no_segments_no_citation_instruction(self):
        """Without segments, the segment-specific citation instruction is absent."""
        prompt = build_prompt("default", "test transcript content here enough")
        assert "Reference them in key_points" not in prompt


# =============================================================================
# JSON Schema Builder (2 tests)
# =============================================================================


class TestJsonSchema:
    def test_text_fields_are_strings(self):
        """Text-type sections produce string placeholders."""
        schema_str = _build_json_schema(TEMPLATES["default"], "en")
        schema = json.loads(schema_str)
        assert isinstance(schema["summary"], str)

    def test_list_fields_are_lists(self):
        """List-type sections produce list placeholders."""
        schema_str = _build_json_schema(TEMPLATES["default"], "en")
        schema = json.loads(schema_str)
        assert isinstance(schema["key_points"], list)


# =============================================================================
# Export (2 tests)
# =============================================================================


class TestExport:
    def test_export_is_valid_json(self):
        """export_templates_json returns valid JSON."""
        result = export_templates_json()
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_export_contains_all_templates(self):
        """Exported JSON contains all templates."""
        parsed = json.loads(export_templates_json())
        names = {t["name"] for t in parsed}
        for name in TEMPLATES:
            assert name in names


# =============================================================================
# Timestamp Formatting (5 tests)
# =============================================================================


class TestTimestampFormatting:
    def test_format_timestamp_zero(self):
        assert _format_timestamp(0.0) == "0:00"

    def test_format_timestamp_seconds(self):
        assert _format_timestamp(5.2) == "0:05"

    def test_format_timestamp_minutes(self):
        assert _format_timestamp(65.0) == "1:05"

    def test_format_transcript_with_segments(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello"},
            {"start": 5.0, "end": 10.0, "text": "World"},
        ]
        result = _format_transcript_with_timestamps("Hello World", segments)
        assert "[0:00-0:05] Hello" in result
        assert "[0:05-0:10] World" in result

    def test_format_transcript_without_segments(self):
        result = _format_transcript_with_timestamps("Plain text", None)
        assert result == "Plain text"


# =============================================================================
# Anti-Hallucination Rules (11 tests)
# =============================================================================

_EN_TEXT = "English meeting transcript with enough content to detect language here"
_RU_TEXT = "Обсудили запуск проекта и распределили задачи между участниками команды"


class TestAntiHallucinationRules:
    def test_evidence_rules_in_every_template_en(self):
        """Every template's EN prompt carries the evidence rules block."""
        for name in TEMPLATES:
            prompt = build_prompt(name, _EN_TEXT)
            assert "EVIDENCE RULES" in prompt, name
            assert "Do NOT invent people" in prompt, name

    def test_evidence_rules_in_every_template_ru(self):
        """Every template's RU prompt carries the evidence rules block."""
        for name in TEMPLATES:
            prompt = build_prompt(name, _RU_TEXT)
            assert "ПРАВИЛА ДОКАЗАТЕЛЬНОСТИ" in prompt, name
            assert "НЕ выдумывай людей" in prompt, name

    def test_one_side_rule_present_en(self):
        """General one-sided rule is present in EN prompt."""
        prompt = build_prompt("default", _EN_TEXT)
        assert "only ONE side of the conversation" in prompt

    def test_one_side_rule_present_ru(self):
        """General one-sided rule is present in RU prompt."""
        prompt = build_prompt("default", _RU_TEXT)
        assert "только ОДНА сторона разговора" in prompt

    def test_participants_no_placeholder_invention_en(self):
        """EN prompt no longer forces placeholder participants."""
        prompt = build_prompt("default", _EN_TEXT)
        assert "Never []" not in prompt
        assert "['Speaker 1', 'Speaker 2']" not in prompt
        assert "Do NOT invent placeholder people" in prompt

    def test_participants_no_placeholder_invention_ru(self):
        """RU prompt no longer forces placeholder participants."""
        prompt = build_prompt("default", _RU_TEXT)
        assert "Никогда не []" not in prompt
        assert "НЕ придумывай людей-заглушек" in prompt

    def test_action_items_empty_allowed_and_timestamped_en(self):
        """EN action_items rule allows empty and requires [MM:SS]."""
        prompt = build_prompt("default", _EN_TEXT)
        assert "MM:SS" in prompt
        assert "EMPTY list [] is the correct answer" in prompt

    def test_action_items_empty_allowed_ru(self):
        """RU action_items rule allows empty list explicitly."""
        prompt = build_prompt("default", _RU_TEXT)
        assert "MM:SS" in prompt
        assert "ПУСТОЙ список [] — правильный ответ" in prompt

    def test_speaker_labels_referenced(self):
        """Prompt tells the model to fall back on speaker labels."""
        prompt = build_prompt("default", _EN_TEXT)
        assert "SPEAKER_1" in prompt
        assert "SPEAKER_ME" in prompt

    def test_one_sided_flag_prepends_notice_en(self):
        """one_sided=True prepends the EN one-sided notice; default omits it."""
        on = build_prompt("default", _EN_TEXT, one_sided=True)
        off = build_prompt("default", _EN_TEXT)
        assert "ONE-SIDED RECORDING" in on
        assert "only SPEAKER_ME's side was recorded" in on  # reminder too
        assert "ONE-SIDED RECORDING" not in off

    def test_one_sided_flag_prepends_notice_ru(self):
        """one_sided=True prepends the RU one-sided notice."""
        on = build_prompt("default", _RU_TEXT, one_sided=True)
        off = build_prompt("default", _RU_TEXT)
        assert "ОДНОСТОРОННЯЯ ЗАПИСЬ" in on
        assert "ОДНОСТОРОННЯЯ ЗАПИСЬ" not in off


class TestOneSidedOwnPromises:
    def test_notice_allows_own_commitments(self):
        from src.templates import _ONE_SIDED_NOTICE

        for lang in ("ru", "en"):
            notice = _ONE_SIDED_NOTICE[lang]
            assert "чаще всего будут пустыми" not in notice
            assert "usually be empty" not in notice
        assert "собственные слова" in _ONE_SIDED_NOTICE["ru"]

    def test_prompt_asks_for_commitments(self):
        from src.templates import build_prompt

        prompt = build_prompt("default", "Обсудили бюджет и сроки проекта на год")
        assert "commitments" in prompt
