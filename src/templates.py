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
        "en": ["<Name (role if mentioned)>"],
        "ru": ["<Имя (роль если упомянута)>"],
    },
    "key_points": {
        "en": ["<specific fact with names/numbers — one sentence>"],
        "ru": ["<конкретный факт с именами/числами — одно предложение>"],
    },
    "decisions": {
        "en": ["<firm decision that closes a question>"],
        "ru": ["<принятое решение, закрывающее вопрос>"],
    },
    "action_items": {
        "en": ["<@Name: specific task [by deadline if stated]>"],
        "ru": ["<@Имя: задача [к сроку если назван]>"],
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
        "en": ["<@Name: specific action [by when]>"],
        "ru": ["<@Имя: конкретное действие [к когда]>"],
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
_FIELD_RULES = {
    "default": {
        "en": (
            "FIELD RULES:\n"
            "- participants: everyone who spoke or was named. Format: 'Name (role)'. If no names: ['Speaker 1', 'Speaker 2']. Never [].\n"
            "- key_points: 3-7 specific facts with names/numbers/dates. One sentence each. NOT topic labels. "
            "BAD: 'API discussed'. GOOD: 'Client deadline is May 15, no extension possible'.\n"
            "- decisions: ONLY firm decisions that CLOSE a question. Not opinions, not topics discussed. "
            'If none: ["No decisions made."].\n'
            "- action_items: tasks with a named owner. Format: '@Name: task [by deadline]'. "
            'Exclude vague suggestions. If none: ["No action items assigned."].\n'
            "- summary: exactly 2-3 sentences. 1) Why this call happened. 2) Main outcome or decision. "
            "3) What remains unresolved. Plain text only — no markdown, no bullets.\n"
            "- title: 5-8 words. WHO + WHAT + OUTCOME. Never generic: no 'meeting', 'discussion', 'call'. "
            "GOOD: 'Q3 Budget Approved, Hiring Frozen'.\n"
            "- entities: people, companies, products, tools. Type: person/company/product/tool. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: все кто говорил или был назван. Формат: «Имя (роль)». Если имён нет: "
            '["Говорящий 1", "Говорящий 2"]. Никогда не [].\n'
            "- key_points: 3-7 конкретных фактов с именами/числами/датами. По одному предложению. "
            "НЕ названия тем. Плохо: «Обсуждение API». Хорошо: «Дедлайн клиента — 15 мая, перенос невозможен».\n"
            "- decisions: ТОЛЬКО принятые решения, которые ЗАКРЫВАЮТ вопрос. Не мнения, не обсуждения. "
            'Если нет: ["Решений не принято."].\n'
            "- action_items: задачи с конкретным исполнителем. Формат: «@Имя: задача [к сроку]». "
            'Без размытых предложений. Если нет: ["Задач не назначено."].\n'
            "- summary: ровно 2-3 предложения. 1) Зачем был звонок. 2) Главный результат или решение. "
            "3) Что нерешено. Только текст — без markdown, без списков.\n"
            "- title: 5-8 слов. КТО + ЧТО + РЕЗУЛЬТАТ. Не общие слова: не «встреча», не «обсуждение». "
            "Хорошо: «Бюджет Q3 одобрен, найм заморожен».\n"
            "- entities: люди, компании, продукты, инструменты. Тип: person/company/product/tool. Если нет: []."
        ),
    },
    "sales_call": {
        "en": (
            "FIELD RULES:\n"
            "- participants: all people on the call. 'Name (role/company)'. Never [].\n"
            "- objections: explicit resistance or doubt from the prospect. Quote their words. "
            'Categorize: PRICE/TIMING/TRUST/FIT. If none: ["No objections raised."].\n'
            "- budget_signals: any mention of money, budget, pricing capacity. Quote exact words. "
            'If none: ["Budget not discussed."].\n'
            "- decision_makers: who makes the buying decision. 'Name (role)'. "
            'If unclear: ["Decision process not clarified."].\n'
            "- next_steps: concrete time-bound commitments. '@Name: action [by when]'. "
            'Not vague "follow up". If none: ["No next steps agreed."].\n'
            "- summary: 1 sentence. Who, buying stage, most important commercial signal.\n"
            "- title: prospect name + stage. 'Acme Corp — Budget Objection, Proposal Requested'.\n"
            "- entities: people, companies, products mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: все участники. «Имя (роль/компания)». Никогда не [].\n"
            "- objections: явное сопротивление или сомнение клиента. Цитируй их слова. "
            'Категория: ЦЕНА/СРОКИ/ДОВЕРИЕ/СООТВЕТСТВИЕ. Если нет: ["Возражений не было."].\n'
            "- budget_signals: любое упоминание денег, бюджета, ценовых возможностей. Точные цитаты. "
            'Если нет: ["Бюджет не обсуждался."].\n'
            "- decision_makers: кто принимает решение о покупке. «Имя (роль)». "
            'Если неясно: ["Процесс решения не прояснён."].\n'
            "- next_steps: конкретные обязательства со сроками. «@Имя: действие [к когда]». "
            'Не размытое «продолжить общение». Если нет: ["Следующих шагов не согласовано."].\n'
            "- summary: 1 предложение. Кто, стадия воронки, главный коммерческий сигнал.\n"
            "- title: имя клиента + стадия. «Acme Corp — возражение по цене, запрошено КП».\n"
            "- entities: люди, компании, продукты. Если нет: []."
        ),
    },
    "one_on_one": {
        "en": (
            "FIELD RULES:\n"
            "- participants: both people. 'Name (role)'. Never [].\n"
            "- feedback: both directions. Prefix: 'Manager→Report:' or 'Report→Manager:'. "
            'Only specific evaluative feedback. If none: ["No feedback exchanged."].\n'
            "- blockers: specific obstacles preventing progress. Include systemic blockers. "
            'If none: ["No blockers surfaced."].\n'
            "- goals: commitments, development targets discussed. "
            'If none: ["No goals set or reviewed."].\n'
            "- mood: 1 sentence. Observable behavioral signals only — energy, stress, engagement. "
            "Quote the transcript. Do NOT infer emotions or psychological states.\n"
            "- summary: 1 sentence capturing the person's current professional state.\n"
            "- title: include person's name. 'Alex 1-on-1 — Reorg Concerns, Promotion Timeline'.\n"
            "- entities: people, teams, projects mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: оба участника. «Имя (роль)». Никогда не [].\n"
            "- feedback: в обе стороны. Префикс: «Руководитель→Сотрудник:» или «Сотрудник→Руководитель:». "
            'Только конкретная оценочная обратная связь. Если нет: ["Обратной связи не было."].\n'
            "- blockers: конкретные препятствия для прогресса. Включай системные блокеры. "
            'Если нет: ["Блокеров не озвучено."].\n'
            "- goals: обязательства, цели развития. "
            'Если нет: ["Цели не обсуждались."].\n'
            "- mood: 1 предложение. Только наблюдаемые сигналы — энергия, стресс, вовлечённость. "
            "Цитируй транскрипт. НЕ выводы об эмоциях.\n"
            "- summary: 1 предложение о текущем профессиональном состоянии.\n"
            "- title: укажи имя. «1-на-1 с Алексом — тревога по реорганизации, сроки повышения».\n"
            "- entities: люди, команды, проекты. Если нет: []."
        ),
    },
    "standup": {
        "en": (
            "FIELD RULES:\n"
            "- participants: first names only. Never [].\n"
            "- done_yesterday: completed items only. Verb + what. Max 8 words each. "
            "'Shipped login page to staging.' NOT 'Worked on login page.'\n"
            "- doing_today: planned items. Same format.\n"
            "- blockers: genuine blockers preventing work, not risks or concerns. "
            'If none: ["No blockers."]. Never empty.\n'
            "- summary: 1 sentence, max 15 words. Team state today.\n"
            "- title: date + focus area. 'Feb 20 Standup — Auth Blocked, 3 Items Done'.\n"
            "- entities: projects, tools mentioned. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: только имена. Никогда не [].\n"
            "- done_yesterday: только завершённые задачи. Глагол + что. Максимум 8 слов. "
            "«Выкатили авторизацию на стейджинг». НЕ «Работали над авторизацией».\n"
            "- doing_today: запланированные задачи. Тот же формат.\n"
            "- blockers: только реальные блокеры, не риски. "
            'Если нет: ["Блокеров нет."]. Никогда не пустой.\n'
            "- summary: 1 предложение, максимум 15 слов. Состояние команды.\n"
            "- title: дата + направление. «Стендап 20 фев — блокер авторизации, 3 задачи выполнены».\n"
            "- entities: проекты, инструменты. Если нет: []."
        ),
    },
    "interview": {
        "en": (
            "FIELD RULES:\n"
            "- participants: candidate + interviewers. 'Name (role)'. Never [].\n"
            "- strengths: specific competency + evidence. "
            "'Competency: X. Evidence: what they demonstrated.' Job-relevant only. 3-5 items.\n"
            "- concerns: specific gap + evidence. Job-relevant only. "
            "No inferences about personality or background. 2-4 items.\n"
            "- culture_fit: candidate's OWN stated work preferences only. Quote them. "
            "If not discussed: empty string.\n"
            "- recommendation: interviewer's EXPLICIT stated assessment only. "
            "Do NOT generate your own opinion. If none stated: 'No explicit recommendation recorded.'\n"
            "- summary: 1 sentence. Candidate, role, overall signal (strong/mixed/weak).\n"
            "- title: candidate + role + signal. "
            "'Sarah K — Backend Lead — Strong Technical, Communication Concern'.\n"
            "- entities: candidate, company, technologies discussed. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: кандидат + интервьюеры. «Имя (роль)». Никогда не [].\n"
            "- strengths: конкретная компетенция + доказательство. "
            "«Компетенция: X. Доказательство: что продемонстрировал». Только по работе. 3-5 пунктов.\n"
            "- concerns: конкретный пробел + доказательство. Только по работе. "
            "Без выводов о личности. 2-4 пункта.\n"
            "- culture_fit: ТОЛЬКО высказанные кандидатом предпочтения. Цитируй. "
            "Если не обсуждалось: пустая строка.\n"
            "- recommendation: ТОЛЬКО явная оценка интервьюера. НЕ генерируй своё мнение. "
            "Если не было: 'Рекомендации не прозвучало.'\n"
            "- summary: 1 предложение. Кандидат, роль, сигнал (сильный/смешанный/слабый).\n"
            "- title: кандидат + роль + сигнал. "
            "«Саша К — Lead Backend — сильная техника, вопросы по коммуникации».\n"
            "- entities: кандидат, компания, технологии. Если нет: []."
        ),
    },
    "brainstorm": {
        "en": (
            "FIELD RULES:\n"
            "- participants: everyone who contributed ideas. Never [].\n"
            "- ideas: ideas that got sustained attention (not passing mentions). "
            "'Idea — one line description'. 3-7 items.\n"
            "- feasibility: ONLY concerns explicitly raised during discussion, "
            "not your assessment. 'Idea: concern raised'. If none discussed: [].\n"
            "- next_steps: concrete actions. '@Name: what [by when]'. Not 'explore further'.\n"
            "- summary: 1 sentence. Session direction and most promising outcome.\n"
            "- title: topic + direction. 'Growth Brainstorm — Referral Program Selected'.\n"
            "- entities: products, tools, companies discussed. If none: []."
        ),
        "ru": (
            "ПРАВИЛА ПОЛЕЙ:\n"
            "- participants: все кто предлагал идеи. Никогда не [].\n"
            "- ideas: идеи, получившие реальное внимание (не мимолётные). "
            "«Идея — описание». 3-7 пунктов.\n"
            "- feasibility: ТОЛЬКО проблемы, явно озвученные в обсуждении, "
            "не твоя оценка. «Идея: озвученная проблема». Если не обсуждалось: [].\n"
            "- next_steps: конкретные действия. «@Имя: что [к когда]». Не 'изучить подробнее'.\n"
            "- summary: 1 предложение. Направление сессии и самый перспективный результат.\n"
            "- title: тема + направление. «Брейнсторм по росту — выбрана реферальная программа».\n"
            "- entities: продукты, инструменты, компании. Если нет: []."
        ),
    },
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
                    "Q3 budget overrun of $200k identified",
                    "Hiring freeze effective immediately across all departments",
                    "Marketing budget cut from $500k to $400k for Q4",
                    "Product roadmap shifted to retention over growth features",
                ],
                "decisions": [
                    "Hiring freeze approved by CEO until end of Q4",
                    "Marketing budget cut by 20%",
                ],
                "action_items": [
                    "@Anna: update job postings to reflect hiring pause by Friday",
                    "@Mark: revise Q4 roadmap and share with team by Monday",
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
                    "Перерасход бюджета Q3 на 200к",
                    "Найм заморожен с сегодняшнего дня по всем отделам",
                    "Бюджет маркетинга урезан с 500к до 400к на Q4",
                    "Дорожная карта: фокус на удержание вместо роста",
                ],
                "decisions": [
                    "Заморозка найма одобрена CEO до конца Q4",
                    "Бюджет маркетинга урезан на 20%",
                ],
                "action_items": [
                    "@Анна: обновить вакансии к пятнице",
                    "@Марк: пересмотреть дорожную карту Q4, разослать команде к понедельнику",
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
) -> str:
    """Build extraction prompt for Ollama.

    Structure (addresses "lost in the middle" problem for 7B models):
    1. Identity — extraction engine, not chatbot
    2. Template preamble — sets the analysis frame
    3. Numbered rules — format constraints
    4. Schema — with descriptive placeholders, fields ordered for quality
    5. Field rules — detailed per-template instructions
    6. One-shot example — concrete quality target
    7. Timestamp instruction (if segments available)
    8. User notes (if provided)
    9. Transcript
    10. Reminder — repeat key constraints + "Start with {"
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
            "summary = 2-3 предложения, без markdown. Начни ответ с {"
        )
    else:
        reminder = (
            "Remember: output ONLY JSON with schema fields. "
            "summary = 2-3 plain text sentences. Start your response with {"
        )

    # Assemble prompt
    parts = [identity]
    if preamble:
        parts.append(preamble)
    parts.extend(["", rules, "", schema_label, schema, "", field_rules])
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
