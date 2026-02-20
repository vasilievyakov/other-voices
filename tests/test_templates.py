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
        """When segments provided, citation instruction is included."""
        segments = [{"start": 0.0, "end": 5.0, "text": "test"}]
        prompt = build_prompt(
            "default", "test transcript content here enough", segments=segments
        )
        assert "timestamp" in prompt.lower()

    def test_no_segments_no_citation_instruction(self):
        """Without segments, no citation instruction."""
        prompt = build_prompt("default", "test transcript content here enough")
        assert "timestamp" not in prompt.lower()


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
