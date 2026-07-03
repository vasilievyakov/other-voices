"""Call Recorder — template registry and prompt builder."""

import json
import re


# =============================================================================
# Template Definitions
# =============================================================================

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


# =============================================================================
# Timestamp Helpers
# =============================================================================


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


# =============================================================================
# Prompt Building — Schema Placeholders
# =============================================================================


def _detect_language(text: str) -> str:
    """Detect if text is primarily Cyrillic → 'ru', otherwise 'en'."""
    cyrillic = len(re.findall(r"[а-яА-ЯёЁ]", text[:500]))
    latin = len(re.findall(r"[a-zA-Z]", text[:500]))
    return "ru" if cyrillic > latin else "en"


# Descriptive placeholders for schema fields — tell the 7B model exactly
# what quality output looks like, right in the schema itself.
_HINTS = {
    # --- Common fields ---
    "participants": {
        "en": ["<name if spoken, else the speaker label e.g. SPEAKER_1>"],
        "ru": ["<имя если названо, иначе метка спикера, напр. SPEAKER_1>"],
    },
    "key_points": {
        "en": ["<[MM:SS] specific fact with names/numbers — one sentence>"],
        "ru": ["<[MM:SS] конкретный факт с именами/числами — одно предложение>"],
    },
    "decisions": {
        "en": ["<[MM:SS] firm decision explicitly stated in the transcript>"],
        "ru": ["<[MM:SS] решение, явно принятое в транскрипте>"],
    },
    "action_items": {
        "en": [
            "<[MM:SS] @Owner: explicit commitment — Owner is a name said or a speaker label>"
        ],
        "ru": [
            "<[MM:SS] @Исполнитель: явное обязательство — имя из транскрипта или метка спикера>"
        ],
    },
    "summary": {
        "en": "<2-3 sentences: purpose, outcome, what's next. Plain text only.>",
        "ru": "<2-3 предложения: зачем звонок, результат, что дальше. Только текст.>",
    },
    "title": {
        "en": "<5-8 words: WHO + WHAT + OUTCOME>",
        "ru": "<5-8 слов: КТО + ЧТО + РЕЗУЛЬТАТ>",
    },
    # --- Sales ---
    "objections": {
        "en": ["<resistance or concern — quote the prospect's words>"],
        "ru": ["<возражение — цитируй слова клиента>"],
    },
    "budget_signals": {
        "en": ["<explicit mention of money/budget — quote exact words>"],
        "ru": ["<явное упоминание денег/бюджета — точная цитата>"],
    },
    "decision_makers": {
        "en": ["<Name (role in purchase decision)>"],
        "ru": ["<Имя (роль в решении о покупке)>"],
    },
    "next_steps": {
        "en": ["<[MM:SS] @Owner: concrete action agreed in the transcript>"],
        "ru": [
            "<[MM:SS] @Исполнитель: конкретное действие, согласованное в транскрипте>"
        ],
    },
    # --- 1-on-1 ---
    "feedback": {
        "en": ["<Manager→Report or Report→Manager: specific feedback>"],
        "ru": ["<Руководитель→Сотрудник или наоборот: обратная связь>"],
    },
    "blockers": {
        "en": ["<specific obstacle blocking progress>"],
        "ru": ["<конкретное препятствие для прогресса>"],
    },
    "goals": {
        "en": ["<specific goal or development target>"],
        "ru": ["<конкретная цель или задача развития>"],
    },
    "mood": {
        "en": "<observable signals: energy, stress, engagement. Not inferred emotions.>",
        "ru": "<наблюдаемые сигналы: энергия, стресс, вовлечённость. Не домыслы.>",
    },
    # --- Standup ---
    "done_yesterday": {
        "en": ["<completed task — verb + what — max 8 words>"],
        "ru": ["<завершённая задача — глагол + что — макс. 8 слов>"],
    },
    "doing_today": {
        "en": ["<planned task — verb + what — max 8 words>"],
        "ru": ["<запланированная задача — глагол + что — макс. 8 слов>"],
    },
    # --- Interview ---
    "strengths": {
        "en": ["<competency + evidence from the interview>"],
        "ru": ["<компетенция + пример из интервью>"],
    },
    "concerns": {
        "en": ["<gap + evidence — job-relevant only>"],
        "ru": ["<пробел + доказательство — только по работе>"],
    },
    "culture_fit": {
        "en": "<candidate's stated work preferences only. If not discussed: ''>",
        "ru": "<только высказанные кандидатом предпочтения. Если не обсуждалось: ''>",
    },
    "recommendation": {
        "en": "<interviewer's explicit assessment ONLY. If none: 'No recommendation stated.'>",
        "ru": "<ТОЛЬКО явная оценка интервьюера. Если нет: 'Рекомендации не прозвучало.'>",
    },
    # --- Brainstorm ---
    "ideas": {
        "en": ["<Idea — one line description. Only ideas that got real attention.>"],
        "ru": ["<Идея — описание. Только идеи, получившие реальное внимание.>"],
    },
    "feasibility": {
        "en": ["<Idea: feasibility concern explicitly raised in discussion>"],
        "ru": ["<Идея: проблема реализуемости, явно озвученная>"],
    },
}


def _build_json_schema(template: dict, lang: str) -> str:
    """Build JSON schema with descriptive placeholders, fields properly ordered.

    Order: participants → content fields → summary → title → entities.
    This ordering means the model extracts facts first, then synthesizes.
    """
    schema = {}

    # 1. Participants first (ground the model in who is speaking)
    schema["participants"] = _HINTS.get("participants", {}).get(lang, ["<participant>"])

    # 2. Content fields (everything except summary and participants)
    for section in template["sections"]:
        key = section["key"]
        if key in ("summary", "participants"):
            continue
        hint = _HINTS.get(key, {}).get(lang)
        if hint is not None:
            schema[key] = hint
        elif section["type"] == "text":
            schema[key] = f"<{section['label'].lower()}>"
        else:
            schema[key] = [f"<{section['label'].lower()} item>"]

    # 3. Summary and title last (synthesize from extracted facts)
    schema["summary"] = _HINTS.get("summary", {}).get(lang, "<summary>")
    schema["title"] = _HINTS.get("title", {}).get(lang, "<title>")

    # 4. Entities always present in schema (not as separate instruction)
    schema["entities"] = [{"name": "<name>", "type": "<person|company|product|tool>"}]

    return json.dumps(schema, ensure_ascii=False, indent=2)


# =============================================================================
# Prompt Building — Template-Specific Config
# =============================================================================

# Preambles: one sentence that sets the model's frame BEFORE it sees the schema.
_PREAMBLES = {
    "sales_call": {
        "en": "This is a SALES call. Extract commercial intelligence, not general discussion.",
        "ru": "Это ПРОДАЖНЫЙ звонок. Извлекай коммерческую информацию, а не общее содержание.",
    },
    "one_on_one": {
        "en": "This is a 1-on-1 meeting. Read for what the person is NOT saying as much as what they are.",
        "ru": "Это встреча 1-на-1. Обращай внимание не только на сказанное, но и на умолчания.",
    },
    "standup": {
        "en": "This is a daily standup. Compress ruthlessly.",
        "ru": "Это ежедневный стендап. Сжимай максимально.",
    },
    "interview": {
        "en": "This is a post-interview debrief. Be precise and honest. Vague assessments are useless.",
        "ru": "Это разбор после интервью. Будь точным и честным. Расплывчатые оценки бесполезны.",
    },
    "brainstorm": {
        "en": "This is a brainstorm. Identify what survived, not everything that was said.",
        "ru": "Это брейнсторм. Определи, какие идеи выжили, а не перечисляй всё сказанное.",
    },
}

# Detailed per-field instructions for each template.
# Anti-hallucination: participants may be speaker labels or empty; action_items /
# decisions must be explicitly present with a [MM:SS] reference; empty lists are
# allowed and preferred over invention. See also _EVIDENCE_RULES below.
_FIELD_RULES = {
    "default": {
        "en": (
            "FIELD RULES:\n"
            "- participants: only people actually named or speaking in the transcript. "
            "Format: 'Name (role)' when a name is spoken, otherwise the speaker label as-is "
            "(SPEAKER_ME, SPEAKER_1). Do NOT invent names or placeholder people. "
            "An empty list [] is allowed if nobody can be identified.\n"
            "- key_points: 3-7 specific facts with names/numbers/dates, each prefixed with its "
            "[MM:SS] timestamp. One sentence each. NOT topic labels. "
            "BAD: 'API discussed'. GOOD: '[12:03] Client deadline is May 15, no extension possible'.\n"
            "- decisions: ONLY firm decisions explicitly stated that CLOSE a question, each prefixed "
            "with [MM:SS]. Not opinions, not topics discussed. If none: [].\n"
            "- action_items: ONLY commitments explicitly made in the transcript. "
            "Format: '[MM:SS] @Name: task [by deadline]'. The owner must be a name said in the "
            "transcript or a speaker label. If none: [] (do not invent a task or an owner).\n"
            "- summary: exactly 2-3 sentences. 1) Why this call happened. 2) Main outcome or decision. "
            "3) What remains unresolved. Plain text only — no markdown, no bullets.\n"
            "- title: 5-8 words. WHO + WHAT + OUTCOME. Never generic: no 'meeting', 'discussion', 'call'. "
            "GOOD: 'Q3 Budget Approved, Hiring Frozen'.\n"
            "- entities: people, companies, products, tools actually mentioned. "
            "Type: person/company/product/tool. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: только реально названные или говорящие в транскрипте. "
            "Формат: «Имя (роль)», если имя произнесено, иначе метка спикера как есть "
            "(SPEAKER_ME, SPEAKER_1). НЕ придумывай имён и людей-заглушек. "
            "Пустой список [] допустим, если никого нельзя определить.\n"
            "- key_points: 3-7 конкретных фактов с именами/числами/датами, каждый с меткой [MM:SS] "
            "в начале. По одному предложению. НЕ названия тем. "
            "Плохо: «Обсуждение API». Хорошо: «[12:03] Дедлайн клиента — 15 мая, перенос невозможен».\n"
            "- decisions: ТОЛЬКО явно принятые решения, которые ЗАКРЫВАЮТ вопрос, каждое с меткой "
            "[MM:SS]. Не мнения, не обсуждения. Если нет: [].\n"
            "- action_items: ТОЛЬКО обязательства, явно данные в транскрипте. "
            "Формат: «[MM:SS] @Имя: задача [к сроку]». Исполнитель — имя из транскрипта или метка "
            "спикера. Если нет: [] (не выдумывай задачу или исполнителя).\n"
            "- summary: ровно 2-3 предложения. 1) Зачем был звонок. 2) Главный результат или решение. "
            "3) Что нерешено. Только текст — без markdown, без списков.\n"
            "- title: 5-8 слов. КТО + ЧТО + РЕЗУЛЬТАТ. Не общие слова: не «встреча», не «обсуждение». "
            "Хорошо: «Бюджет Q3 одобрен, найм заморожен».\n"
            "- entities: реально упомянутые люди, компании, продукты, инструменты. "
            "Тип: person/company/product/tool. Если нет: []."
        ),
    },
    "sales_call": {
        "en": (
            "FIELD RULES:\n"
            "- participants: only people actually on the call. 'Name (role/company)' when named, "
            "otherwise the speaker label. Do NOT invent people. Empty list [] allowed.\n"
            "- objections: explicit resistance or doubt from the prospect. Quote their words with "
            "[MM:SS]. Categorize: PRICE/TIMING/TRUST/FIT. If none: [].\n"
            "- budget_signals: any mention of money, budget, pricing capacity. Quote exact words with "
            "[MM:SS]. If none: [].\n"
            "- decision_makers: who makes the buying decision, only if stated. 'Name (role)'. "
            "If unclear: [].\n"
            "- next_steps: ONLY concrete time-bound commitments explicitly agreed. "
            "'[MM:SS] @Name: action [by when]'. Owner is a name said or a speaker label. "
            'Not vague "follow up". If none: [] (do not invent).\n'
            "- summary: 1 sentence. Who, buying stage, most important commercial signal.\n"
            "- title: prospect name + stage. 'Acme Corp — Budget Objection, Proposal Requested'.\n"
            "- entities: people, companies, products actually mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: только реальные участники. «Имя (роль/компания)», если названо, иначе "
            "метка спикера. НЕ придумывай людей. Пустой список [] допустим.\n"
            "- objections: явное сопротивление или сомнение клиента. Цитируй их слова с меткой [MM:SS]. "
            "Категория: ЦЕНА/СРОКИ/ДОВЕРИЕ/СООТВЕТСТВИЕ. Если нет: [].\n"
            "- budget_signals: любое упоминание денег, бюджета, ценовых возможностей. Точные цитаты с "
            "[MM:SS]. Если нет: [].\n"
            "- decision_makers: кто принимает решение о покупке, только если сказано. «Имя (роль)». "
            "Если неясно: [].\n"
            "- next_steps: ТОЛЬКО конкретные обязательства со сроками, явно согласованные. "
            "«[MM:SS] @Имя: действие [к когда]». Исполнитель — имя из транскрипта или метка спикера. "
            "Не размытое «продолжить общение». Если нет: [] (не выдумывай).\n"
            "- summary: 1 предложение. Кто, стадия воронки, главный коммерческий сигнал.\n"
            "- title: имя клиента + стадия. «Acme Corp — возражение по цене, запрошено КП».\n"
            "- entities: реально упомянутые люди, компании, продукты. Если нет: []."
        ),
    },
    "one_on_one": {
        "en": (
            "FIELD RULES:\n"
            "- participants: only the people actually present. 'Name (role)' when named, otherwise "
            "the speaker label. Do NOT invent people. Empty list [] allowed.\n"
            "- feedback: both directions. Prefix: 'Manager→Report:' or 'Report→Manager:'. "
            "Only specific evaluative feedback actually voiced, with [MM:SS]. If none: [].\n"
            "- blockers: specific obstacles actually raised. Include systemic blockers. With [MM:SS]. "
            "If none: [].\n"
            "- goals: commitments or development targets actually discussed, with [MM:SS]. "
            "If none: [].\n"
            "- mood: 1 sentence. Observable behavioral signals only — energy, stress, engagement. "
            "Quote the transcript. Do NOT infer emotions or psychological states.\n"
            "- summary: 1 sentence capturing the person's current professional state.\n"
            "- title: include person's name. 'Alex 1-on-1 — Reorg Concerns, Promotion Timeline'.\n"
            "- entities: people, teams, projects actually mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: только реально присутствующие. «Имя (роль)», если названо, иначе метка "
            "спикера. НЕ придумывай людей. Пустой список [] допустим.\n"
            "- feedback: в обе стороны. Префикс: «Руководитель→Сотрудник:» или «Сотрудник→Руководитель:». "
            "Только конкретная оценочная обратная связь, реально прозвучавшая, с [MM:SS]. Если нет: [].\n"
            "- blockers: конкретные препятствия, реально озвученные. Включай системные блокеры. "
            "С [MM:SS]. Если нет: [].\n"
            "- goals: обязательства или цели развития, реально обсуждённые, с [MM:SS]. Если нет: [].\n"
            "- mood: 1 предложение. Только наблюдаемые сигналы — энергия, стресс, вовлечённость. "
            "Цитируй транскрипт. НЕ выводы об эмоциях.\n"
            "- summary: 1 предложение о текущем профессиональном состоянии.\n"
            "- title: укажи имя. «1-на-1 с Алексом — тревога по реорганизации, сроки повышения».\n"
            "- entities: реально упомянутые люди, команды, проекты. Если нет: []."
        ),
    },
    "standup": {
        "en": (
            "FIELD RULES:\n"
            "- participants: first names actually spoken, otherwise speaker labels. "
            "Do NOT invent people. Empty list [] allowed.\n"
            "- done_yesterday: completed items only, actually reported. Verb + what. Max 8 words each. "
            "'[MM:SS] Shipped login page to staging.' NOT 'Worked on login page.'\n"
            "- doing_today: planned items actually stated. Same format with [MM:SS].\n"
            "- blockers: genuine blockers actually raised, not risks or concerns. With [MM:SS]. "
            "If none: [].\n"
            "- summary: 1 sentence, max 15 words. Team state today.\n"
            "- title: date + focus area. 'Feb 20 Standup — Auth Blocked, 3 Items Done'.\n"
            "- entities: projects, tools actually mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: реально прозвучавшие имена, иначе метки спикеров. НЕ придумывай людей. "
            "Пустой список [] допустим.\n"
            "- done_yesterday: только завершённые задачи, реально названные. Глагол + что. Максимум 8 слов. "
            "«[MM:SS] Выкатили авторизацию на стейджинг». НЕ «Работали над авторизацией».\n"
            "- doing_today: запланированные задачи, реально названные. Тот же формат с [MM:SS].\n"
            "- blockers: только реальные блокеры, реально озвученные, не риски. С [MM:SS]. Если нет: [].\n"
            "- summary: 1 предложение, максимум 15 слов. Состояние команды.\n"
            "- title: дата + направление. «Стендап 20 фев — блокер авторизации, 3 задачи выполнены».\n"
            "- entities: реально упомянутые проекты, инструменты. Если нет: []."
        ),
    },
    "interview": {
        "en": (
            "FIELD RULES:\n"
            "- participants: candidate + interviewers actually present. 'Name (role)' when named, "
            "otherwise the speaker label. Do NOT invent people. Empty list [] allowed.\n"
            "- strengths: specific competency + evidence from the interview, with [MM:SS]. "
            "'Competency: X. Evidence: what they demonstrated.' Job-relevant only. Only those actually shown.\n"
            "- concerns: specific gap + evidence, with [MM:SS]. Job-relevant only. "
            "No inferences about personality or background. Only concerns actually observed.\n"
            "- culture_fit: candidate's OWN stated work preferences only. Quote them. "
            "If not discussed: empty string.\n"
            "- recommendation: interviewer's EXPLICIT stated assessment only. "
            "Do NOT generate your own opinion. If none stated: 'No explicit recommendation recorded.'\n"
            "- summary: 1 sentence. Candidate, role, overall signal (strong/mixed/weak).\n"
            "- title: candidate + role + signal. "
            "'Sarah K — Backend Lead — Strong Technical, Communication Concern'.\n"
            "- entities: candidate, company, technologies actually discussed. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: кандидат + интервьюеры, реально присутствующие. «Имя (роль)», если названо, "
            "иначе метка спикера. НЕ придумывай людей. Пустой список [] допустим.\n"
            "- strengths: конкретная компетенция + доказательство из интервью, с [MM:SS]. "
            "«Компетенция: X. Доказательство: что продемонстрировал». Только по работе. Только реально показанные.\n"
            "- concerns: конкретный пробел + доказательство, с [MM:SS]. Только по работе. "
            "Без выводов о личности. Только реально замеченные.\n"
            "- culture_fit: ТОЛЬКО высказанные кандидатом предпочтения. Цитируй. "
            "Если не обсуждалось: пустая строка.\n"
            "- recommendation: ТОЛЬКО явная оценка интервьюера. НЕ генерируй своё мнение. "
            "Если не было: 'Рекомендации не прозвучало.'\n"
            "- summary: 1 предложение. Кандидат, роль, сигнал (сильный/смешанный/слабый).\n"
            "- title: кандидат + роль + сигнал. "
            "«Саша К — Lead Backend — сильная техника, вопросы по коммуникации».\n"
            "- entities: реально обсуждённые кандидат, компания, технологии. Если нет: []."
        ),
    },
    "brainstorm": {
        "en": (
            "FIELD RULES:\n"
            "- participants: everyone who actually contributed. Speaker labels when unnamed. "
            "Do NOT invent people. Empty list [] allowed.\n"
            "- ideas: ideas that got sustained attention (not passing mentions), with [MM:SS]. "
            "'Idea — one line description'. Only ideas actually raised.\n"
            "- feasibility: ONLY concerns explicitly raised during discussion, with [MM:SS], "
            "not your assessment. 'Idea: concern raised'. If none discussed: [].\n"
            "- next_steps: ONLY concrete actions explicitly agreed. '[MM:SS] @Name: what [by when]'. "
            "Owner is a name said or a speaker label. Not 'explore further'. If none: [].\n"
            "- summary: 1 sentence. Session direction and most promising outcome.\n"
            "- title: topic + direction. 'Growth Brainstorm — Referral Program Selected'.\n"
            "- entities: products, tools, companies actually discussed. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: все, кто реально участвовал. Метки спикеров, если без имени. "
            "НЕ придумывай людей. Пустой список [] допустим.\n"
            "- ideas: идеи, получившие реальное внимание (не мимолётные), с [MM:SS]. "
            "«Идея — описание». Только реально прозвучавшие идеи.\n"
            "- feasibility: ТОЛЬКО проблемы, явно озвученные в обсуждении, с [MM:SS], "
            "не твоя оценка. «Идея: озвученная проблема». Если не обсуждалось: [].\n"
            "- next_steps: ТОЛЬКО конкретные действия, явно согласованные. «[MM:SS] @Имя: что [к когда]». "
            "Исполнитель — имя из транскрипта или метка спикера. Не 'изучить подробнее'. Если нет: [].\n"
            "- summary: 1 предложение. Направление сессии и самый перспективный результат.\n"
            "- title: тема + направление. «Брейнсторм по росту — выбрана реферальная программа».\n"
            "- entities: реально обсуждённые продукты, инструменты, компании. Если нет: []."
        ),
    },
}

# =============================================================================
# Evidence rules — appended for EVERY template. This is the core
# anti-hallucination contract: extract only what is in the transcript, allow
# empty lists, and never guess the missing side of a one-sided recording.
# =============================================================================
_EVIDENCE_RULES = {
    "en": (
        "EVIDENCE RULES (apply to every field):\n"
        "- Use ONLY what is actually in the transcript. Do NOT invent people, names, "
        "decisions, tasks, deadlines, or numbers.\n"
        "- participants: list only names actually spoken. When a speaker has no name, "
        "use the speaker label as-is (SPEAKER_ME, SPEAKER_1, ...). Do NOT invent "
        "placeholder people such as 'Speaker 1' / 'Participant 2'. If nobody can be "
        "identified, an empty list [] is correct.\n"
        "- action_items: include ONLY commitments explicitly stated. Each item starts "
        "with its [MM:SS] timestamp and names an owner that is a name said in the "
        "transcript or a speaker label. An EMPTY list [] is the correct answer when no "
        "explicit commitment was made — prefer [] over inventing a task or an owner.\n"
        "- decisions: include ONLY decisions explicitly made, each starting with its "
        "[MM:SS] timestamp. An empty list [] is correct when nothing was decided.\n"
        "- If the transcript contains only ONE side of the conversation (for example only "
        "SPEAKER_ME speaks), do NOT guess what the other side said, asked, decided, or "
        "committed to. Summarize only what the present speaker actually says."
    ),
    "ru": (
        "ПРАВИЛА ДОКАЗАТЕЛЬНОСТИ (для всех полей):\n"
        "- Используй ТОЛЬКО то, что реально есть в транскрипте. НЕ выдумывай людей, имена, "
        "решения, задачи, сроки и числа.\n"
        "- participants: перечисляй только реально прозвучавшие имена. Если у говорящего "
        "нет имени — используй его метку как есть (SPEAKER_ME, SPEAKER_1, ...). НЕ придумывай "
        "людей-заглушек вроде «Говорящий 1» / «Участник 2». Если никого нельзя определить — "
        "правильный ответ пустой список [].\n"
        "- action_items: только обязательства, явно озвученные. Каждый пункт начинается с "
        "метки [MM:SS] и указывает исполнителя — имя из транскрипта или метку спикера. "
        "ПУСТОЙ список [] — правильный ответ, если явных обязательств не было; пустой список "
        "лучше выдуманной задачи или исполнителя.\n"
        "- decisions: только явно принятые решения, каждое начинается с метки [MM:SS]. "
        "Пустой список [] корректен, если ничего не решено.\n"
        "- Если в транскрипте только ОДНА сторона разговора (например, говорит только "
        "SPEAKER_ME) — НЕ додумывай, что сказала, спросила, решила или пообещала другая "
        "сторона. Резюмируй только то, что реально произносит присутствующий говорящий."
    ),
}

# Prepended near the top of the prompt when the recording captured only the local
# microphone (mic_only coverage). Placed high for maximum attention.
_ONE_SIDED_NOTICE = {
    "en": (
        "IMPORTANT — ONE-SIDED RECORDING: This transcript captured only ONE side of the "
        "call (the local microphone, SPEAKER_ME). The other participants' words were NOT "
        "recorded. Summarize only what SPEAKER_ME actually says. Do NOT invent the other "
        "side's replies, questions, decisions, or commitments. participants should contain "
        "only SPEAKER_ME unless another name is explicitly spoken. action_items and "
        "decisions will usually be empty [] — do not fabricate them."
    ),
    "ru": (
        "ВАЖНО — ОДНОСТОРОННЯЯ ЗАПИСЬ: В этом транскрипте записана только ОДНА сторона "
        "звонка (локальный микрофон, SPEAKER_ME). Слова остальных участников НЕ записаны. "
        "Резюмируй только то, что реально говорит SPEAKER_ME. НЕ придумывай реплики, вопросы, "
        "решения и обязательства другой стороны. В participants должен быть только SPEAKER_ME, "
        "если в тексте явно не названо другое имя. action_items и decisions чаще всего будут "
        "пустыми [] — не выдумывай их."
    ),
}

# One-shot examples — only for default template (most commonly used).
# The example teaches the 7B model what quality output looks like.
_EXAMPLES = {
    "default": {
        "en": json.dumps(
            {
                "participants": [
                    "Anna (CEO)",
                    "Mark (product)",
                    "Irina (marketing)",
                ],
                "key_points": [
                    "[02:14] Q3 budget overrun of $200k identified",
                    "[05:40] Hiring freeze effective immediately across all departments",
                    "[08:12] Marketing budget cut from $500k to $400k for Q4",
                    "[11:30] Product roadmap shifted to retention over growth features",
                ],
                "decisions": [
                    "[05:40] Hiring freeze approved by CEO until end of Q4",
                    "[08:12] Marketing budget cut by 20%",
                ],
                "action_items": [
                    "[06:02] @Anna: update job postings to reflect hiring pause by Friday",
                    "[12:05] @Mark: revise Q4 roadmap and share with team by Monday",
                ],
                "summary": (
                    "Team agreed to freeze hiring until Q4 due to Q3 budget overruns. "
                    "Marketing budget cut by 20%. "
                    "Next step: Mark revises roadmap by Monday."
                ),
                "title": "Hiring Freeze and Marketing Budget Cut Approved",
                "entities": [
                    {"name": "Anna", "type": "person"},
                    {"name": "Mark", "type": "person"},
                    {"name": "Irina", "type": "person"},
                ],
            },
            indent=2,
        ),
        "ru": json.dumps(
            {
                "participants": [
                    "Анна (CEO)",
                    "Марк (продукт)",
                    "Ирина (маркетинг)",
                ],
                "key_points": [
                    "[02:14] Перерасход бюджета Q3 на 200к",
                    "[05:40] Найм заморожен с сегодняшнего дня по всем отделам",
                    "[08:12] Бюджет маркетинга урезан с 500к до 400к на Q4",
                    "[11:30] Дорожная карта: фокус на удержание вместо роста",
                ],
                "decisions": [
                    "[05:40] Заморозка найма одобрена CEO до конца Q4",
                    "[08:12] Бюджет маркетинга урезан на 20%",
                ],
                "action_items": [
                    "[06:02] @Анна: обновить вакансии к пятнице",
                    "[12:05] @Марк: пересмотреть дорожную карту Q4, разослать команде к понедельнику",
                ],
                "summary": (
                    "Команда согласовала заморозку найма до Q4 из-за перерасхода бюджета. "
                    "Бюджет маркетинга урезан на 20%. "
                    "Марк пересмотрит дорожную карту к понедельнику."
                ),
                "title": "Заморозка найма и сокращение бюджета маркетинга",
                "entities": [
                    {"name": "Анна", "type": "person"},
                    {"name": "Марк", "type": "person"},
                    {"name": "Ирина", "type": "person"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    },
}


# =============================================================================
# Prompt Builder
# =============================================================================


def build_prompt(
    template_name: str,
    transcript: str,
    notes: str | None = None,
    segments: list[dict] | None = None,
    one_sided: bool = False,
) -> str:
    """Build extraction prompt for Ollama.

    Structure (addresses "lost in the middle" problem for 7B models):
    1. Identity — extraction engine, not chatbot
    1b. One-sided notice (if one_sided) — highest attention, prepended near top
    2. Template preamble — sets the analysis frame
    3. Numbered rules — format constraints
    4. Schema — with descriptive placeholders, fields ordered for quality
    5. Field rules — detailed per-template instructions
    5b. Evidence rules — anti-hallucination contract for every template
    6. One-shot example — concrete quality target
    7. Timestamp instruction (if segments available)
    8. User notes (if provided)
    9. Transcript
    10. Reminder — repeat key constraints + "Start with {"

    Args:
        one_sided: When True, the transcript captured only the local mic
            (SPEAKER_ME). A prominent notice is prepended telling the model not
            to guess the other side of the conversation.
    """
    template = TEMPLATES.get(template_name, TEMPLATES["default"])
    effective_name = template_name if template_name in TEMPLATES else "default"
    lang = _detect_language(transcript)
    schema = _build_json_schema(template, lang)
    has_timestamps = bool(segments)

    # 1. Identity
    if lang == "ru":
        identity = (
            "Ты — движок извлечения данных в JSON. "
            "Твоя ЕДИНСТВЕННАЯ задача — прочитать транскрипт и вывести один валидный JSON объект. "
            "НЕ обращайся к пользователю. НЕ объясняй действия. ТОЛЬКО JSON."
        )
    else:
        identity = (
            "You are a JSON extraction engine. "
            "Your ONLY job is to read the transcript and output a single valid JSON object. "
            "Do NOT address the user. Do NOT explain. ONLY JSON."
        )

    # 1b. One-sided notice (prepended high for attention)
    one_sided_notice = _ONE_SIDED_NOTICE[lang] if one_sided else ""

    # 2. Preamble (template-specific)
    preamble = _PREAMBLES.get(effective_name, {}).get(lang, "")

    # 3. Rules
    if lang == "ru":
        rules = (
            "ПРАВИЛА:\n"
            "1. Выводи ТОЛЬКО JSON объект — без markdown, без ```json, без текста до или после.\n"
            "2. Используй ТОЛЬКО поля из схемы ниже. НЕ добавляй лишних полей.\n"
            "3. Используй язык транскрипта для всех значений.\n"
            "4. Заполняй в порядке схемы: participants и факты первыми, summary и title — последними."
        )
    else:
        rules = (
            "RULES:\n"
            "1. Output ONLY the JSON object — no markdown, no ```json, no text before or after.\n"
            "2. Use ONLY the fields shown in the schema. Do NOT add extra fields.\n"
            "3. Use the transcript language for all values.\n"
            "4. Fill fields in schema order: participants and facts first, summary and title last."
        )

    # 4. Schema label
    if lang == "ru":
        schema_label = "СХЕМА (выводи ТОЛЬКО эти поля):"
    else:
        schema_label = "OUTPUT SCHEMA (use ONLY these fields):"

    # 5. Field rules
    field_rules = _FIELD_RULES.get(effective_name, _FIELD_RULES["default"]).get(
        lang, ""
    )

    # 5b. Evidence rules (anti-hallucination, applied to every template)
    evidence_rules = _EVIDENCE_RULES[lang]

    # 6. Example
    example_json = _EXAMPLES.get(effective_name, {}).get(lang, "")
    if example_json:
        if lang == "ru":
            example_block = f"ПРИМЕР ХОРОШЕГО ОТВЕТА:\n{example_json}"
        else:
            example_block = f"EXAMPLE OF GOOD OUTPUT:\n{example_json}"
    else:
        example_block = ""

    # 7. Timestamp instruction
    if has_timestamps:
        if lang == "ru":
            ts_instruction = (
                "Транскрипт содержит метки [M:SS]. "
                "Ссылайся на них в key_points: [M:SS] в начале пункта."
            )
        else:
            ts_instruction = (
                "Transcript has [M:SS] timestamps. "
                "Reference them in key_points: prefix each with [M:SS]."
            )
    else:
        ts_instruction = ""

    # 8. Notes
    if notes:
        if lang == "ru":
            notes_block = f"ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ:\n{notes}"
        else:
            notes_block = f"USER NOTES:\n{notes}"
    else:
        notes_block = ""

    # 9. Transcript
    formatted = _format_transcript_with_timestamps(transcript, segments)
    if lang == "ru":
        transcript_block = f"ТРАНСКРИПТ:\n{formatted}"
    else:
        transcript_block = f"TRANSCRIPT:\n{formatted}"

    # 10. Reminder (after transcript — key constraints repeated for attention)
    if lang == "ru":
        reminder = (
            "Напоминание: выведи ТОЛЬКО JSON с полями из схемы. "
            "summary = 2-3 предложения, без markdown. "
            "Не выдумывай людей, задачи и решения — используй только то, что есть в транскрипте; "
            "пустые списки допустимы. Начни ответ с {"
        )
        if one_sided:
            reminder += " Помни: записана только сторона SPEAKER_ME — не додумывай слова других участников."
    else:
        reminder = (
            "Remember: output ONLY JSON with schema fields. "
            "summary = 2-3 plain text sentences. "
            "Do not invent people, tasks, or decisions — use only what is in the transcript; "
            "empty lists are fine. Start your response with {"
        )
        if one_sided:
            reminder += " Remember: only SPEAKER_ME's side was recorded — do not guess the other side's words."

    # Assemble prompt
    parts = [identity]
    if one_sided_notice:
        parts.append(one_sided_notice)
    if preamble:
        parts.append(preamble)
    parts.extend(["", rules, "", schema_label, schema, "", field_rules])
    parts.extend(["", evidence_rules])
    if example_block:
        parts.extend(["", example_block])
    if ts_instruction:
        parts.extend(["", ts_instruction])
    if notes_block:
        parts.extend(["", notes_block])
    parts.extend(["", transcript_block, "", reminder])

    return "\n".join(parts)


def export_templates_json() -> str:
    """Export all templates as a JSON string (for Swift app consumption)."""
    return json.dumps(list_templates(), ensure_ascii=False, indent=2)
