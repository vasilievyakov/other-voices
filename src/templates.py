"""Call Recorder — template registry and prompt builder."""

import json
import re


TEMPLATES = {
    "default": {
        "name": "default",
        "display_name": "Default",
        "description": "Standard call summary with key points, decisions, and action items",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "key_points", "label": "Key Points", "type": "list"},
            {"key": "decisions", "label": "Decisions", "type": "list"},
            {"key": "action_items", "label": "Action Items", "type": "list"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
    "sales_call": {
        "name": "sales_call",
        "display_name": "Sales Call",
        "description": "Sales-focused: objections, budget signals, decision makers, next steps",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "objections", "label": "Objections", "type": "list"},
            {"key": "budget_signals", "label": "Budget Signals", "type": "list"},
            {"key": "decision_makers", "label": "Decision Makers", "type": "list"},
            {"key": "next_steps", "label": "Next Steps", "type": "list"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
    "one_on_one": {
        "name": "one_on_one",
        "display_name": "1-on-1",
        "description": "One-on-one meeting: feedback, blockers, goals, mood",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "feedback", "label": "Feedback", "type": "list"},
            {"key": "blockers", "label": "Blockers", "type": "list"},
            {"key": "goals", "label": "Goals", "type": "list"},
            {"key": "mood", "label": "Mood", "type": "text"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
    "standup": {
        "name": "standup",
        "display_name": "Standup",
        "description": "Daily standup: done yesterday, doing today, blockers",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "done_yesterday", "label": "Done Yesterday", "type": "list"},
            {"key": "doing_today", "label": "Doing Today", "type": "list"},
            {"key": "blockers", "label": "Blockers", "type": "list"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
    "interview": {
        "name": "interview",
        "display_name": "Interview",
        "description": "Interview debrief: strengths, concerns, culture fit, recommendation",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "strengths", "label": "Strengths", "type": "list"},
            {"key": "concerns", "label": "Concerns", "type": "list"},
            {"key": "culture_fit", "label": "Culture Fit", "type": "text"},
            {"key": "recommendation", "label": "Recommendation", "type": "text"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
    "brainstorm": {
        "name": "brainstorm",
        "display_name": "Brainstorm",
        "description": "Brainstorming session: ideas, feasibility, next steps",
        "sections": [
            {"key": "summary", "label": "Summary", "type": "text"},
            {"key": "ideas", "label": "Ideas", "type": "list"},
            {"key": "feasibility", "label": "Feasibility Notes", "type": "list"},
            {"key": "next_steps", "label": "Next Steps", "type": "list"},
            {"key": "participants", "label": "Participants", "type": "list"},
        ],
    },
}


def get_template(name: str) -> dict | None:
    """Get a template by name. Returns None if not found."""
    return TEMPLATES.get(name)


def list_templates() -> list[dict]:
    """Return all templates as a list."""
    return list(TEMPLATES.values())


def _detect_language(text: str) -> str:
    """Detect if text is primarily Cyrillic → 'ru', otherwise 'en'."""
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", text[:500]))
    latin = len(re.findall(r"[a-zA-Z]", text[:500]))
    return "ru" if cyrillic > latin else "en"


def _build_json_schema(template: dict) -> str:
    """Build JSON schema example from template sections."""
    schema = {}
    for section in template["sections"]:
        if section["type"] == "text":
            schema[section["key"]] = f"<{section['label'].lower()}>"
        else:
            schema[section["key"]] = [f"<{section['label'].lower()} item>"]
    return json.dumps(schema, ensure_ascii=False, indent=2)


def _format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS timestamp."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _format_transcript_with_timestamps(
    transcript: str, segments: list[dict] | None
) -> str:
    """Format transcript with [M:SS] timestamps from segments if available."""
    if not segments:
        return transcript
    lines = []
    for seg in segments:
        start = _format_timestamp(seg.get("start", 0.0))
        end = _format_timestamp(seg.get("end", 0.0))
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{start}-{end}] {text}")
    return "\n".join(lines) if lines else transcript


def build_prompt(
    template_name: str,
    transcript: str,
    notes: str | None = None,
    segments: list[dict] | None = None,
) -> str:
    """Build a full prompt for Ollama from template, transcript, and optional notes.

    Falls back to 'default' if template not found.
    When segments with timestamps are provided, includes [M:SS] markers and
    instructs the model to cite timestamps in key_points.
    """
    template = TEMPLATES.get(template_name, TEMPLATES["default"])
    lang = _detect_language(transcript)
    schema = _build_json_schema(template)
    has_timestamps = bool(segments)

    if lang == "ru":
        intro = (
            "Ты анализируешь транскрипт звонка. Извлеки структурированную информацию."
        )
        json_instruction = "Ответь строго в JSON формате (без markdown):"
        empty_instruction = 'Если какое-то поле не определяется из транскрипта, используй пустой список [] для списков или пустую строку "" для текста.'
        entity_instruction = 'Также извлеки упомянутых людей и компании в поле "entities": [{"name": "Имя", "type": "person"}, {"name": "Компания", "type": "company"}]. Если не найдено — пустой список [].'
        lang_instruction = "Отвечай на том же языке, что и транскрипт."
        transcript_label = "ТРАНСКРИПТ:"
        notes_label = "ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ (используй как руководство для анализа):"
        citation_instruction = "Транскрипт содержит метки времени [M:SS]. Для каждого key_point добавь ссылку на временной интервал в формате [M:SS] в начале пункта."
    else:
        intro = "You are analyzing a call transcript. Extract structured information."
        json_instruction = "Respond strictly in JSON format (no markdown):"
        empty_instruction = 'If a field cannot be determined from the transcript, use an empty list [] for lists or an empty string "" for text.'
        entity_instruction = 'Also extract mentioned people and companies into an "entities" field: [{"name": "Name", "type": "person"}, {"name": "Company", "type": "company"}]. If none found, use an empty list [].'
        lang_instruction = "Respond in the same language as the transcript."
        transcript_label = "TRANSCRIPT:"
        notes_label = "USER NOTES (use as guidance for analysis):"
        citation_instruction = "The transcript contains [M:SS] timestamps. For each key_point, include a timestamp reference [M:SS] at the beginning of the point."

    parts = [
        intro,
        "",
        json_instruction,
        schema,
        "",
        empty_instruction,
        entity_instruction,
        lang_instruction,
    ]

    if has_timestamps:
        parts.append(citation_instruction)

    if notes:
        parts.extend(["", notes_label, notes])

    formatted_transcript = _format_transcript_with_timestamps(transcript, segments)
    parts.extend(["", transcript_label, formatted_transcript])

    return "\n".join(parts)


def export_templates_json() -> str:
    """Export all templates as a JSON string (for Swift app consumption)."""
    return json.dumps(list_templates(), ensure_ascii=False, indent=2)
