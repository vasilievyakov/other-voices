# Meeting Commitment Intelligence — Полный гайд

> Документ для агента, который будет реализовывать commitment tracking в Other Voices.
> Содержит: архитектуру пайплайна, best practices из исследований, 5 промптов.

---

## Часть 1: Архитектура пайплайна

### Как это встраивается в Other Voices

Other Voices уже пишет **два отдельных аудиофайла**:
- `mic.wav` — только голос владельца (через AVAudioEngine)
- `system.wav` — голоса всех собеседников (через ScreenCaptureKit)

Это нужно использовать. Текущий `transcriber.py` их сразу склеивает — это ошибка, которая уничтожает информацию о том, кто говорит.

**Новый пайплайн:**

```
daemon.py обнаружил звонок
    ↓
AudioCapture.swift               [без изменений]
    → mic.wav    (владелец, 100% точность)
    → system.wav (все собеседники)

transcriber.py                   [ИЗМЕНЕНИЕ: раздельная транскрипция]
    → mlx_whisper(mic.wav)     → transcript_me.json
    → mlx_whisper(system.wav)  → transcript_others.json
    → merge_by_timestamp()     → unified_transcript.json

        Формат unified_transcript:
        [
          {"start": 1.2, "end": 3.4, "speaker": "SPEAKER_ME",    "text": "Хорошо, я пришлю к пятнице"},
          {"start": 3.8, "end": 5.1, "speaker": "SPEAKER_OTHER", "text": "Отлично, буду ждать"},
          ...
        ]

speaker_resolver.py              [НОВЫЙ модуль]
    Если pyannote установлен:
        → system.wav → pyannote diarization-3.1
        → SPEAKER_OTHER_1, SPEAKER_OTHER_2 сегменты с таймстампами
    Если нет:
        → весь system.wav = один SPEAKER_OTHER (приемлемо для 1:1 звонков)
    → unified_transcript + Prompt 0 → speaker_map.json

        Формат speaker_map:
        {
          "SPEAKER_ME":      {"confirmed": true,  "source": "mic_channel"},
          "SPEAKER_OTHER_1": {"name": "Елена",    "confidence": 0.85, "source": "direct_address"},
          "SPEAKER_OTHER_2": {"name": null,        "confidence": 0.0,  "source": null}
        }

summarizer.py                    [МИНИМАЛЬНОЕ ИЗМЕНЕНИЕ]
    → unified_transcript + speaker_map → Ollama → summary JSON

commitment_extractor.py          [НОВЫЙ модуль]
    → unified_transcript + speaker_map → Prompt 3 (Карпати) по умолчанию
    → если JSON упал → retry с Prompt 1 (Муратии)
    → таймаут 30 сек, иначе skip (не блокирует пайплайн)
    → commitments.json

database.py                      [ДОБАВИТЬ таблицу]
    CREATE TABLE commitments (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      call_id      INTEGER REFERENCES calls(id),
      direction    TEXT CHECK(direction IN ('outgoing','incoming')),
      who_label    TEXT,
      who_name     TEXT,
      to_label     TEXT,
      to_name      TEXT,
      text         TEXT NOT NULL,
      deadline     TEXT,
      deadline_conf TEXT,
      significance  TEXT,
      status       TEXT DEFAULT 'open'
                        CHECK(status IN ('open','done','dismissed')),
      created_at   TEXT DEFAULT (datetime('now')),
      resolved_at  TEXT
    );

SwiftUI                          [НОВЫЕ компоненты]
    → CommitmentsView      — все открытые обязательства по всем звонкам
    → CommitmentBadge      — счётчик на SidebarView (outgoing / incoming)
    → NotificationService  — macOS уведомления по дедлайнам
```

### Когда вызывается какой промпт

| Шаг | Модуль | Промпт | Условие |
|-----|--------|--------|---------|
| 1 | speaker_resolver.py | Prompt 0 | После merge транскриптов |
| 2 | commitment_extractor.py | Prompt 3 (Карпати) | Первый вызов, по умолчанию |
| 2b | commitment_extractor.py | Prompt 1 (Муратии) | Fallback если JSON невалидный |
| Ручной | UI кнопка | Любой на выбор | Пользователь нажал "re-extract" |

### Псевдокод daemon.py

```python
async def process_call(session_dir):
    # 1. Раздельная транскрипция
    transcript_me     = transcriber.transcribe(mic_wav)
    transcript_others = transcriber.transcribe(system_wav)
    unified           = merge_by_timestamp(transcript_me, "SPEAKER_ME",
                                           transcript_others, "SPEAKER_OTHER")

    # 2. Speaker resolution
    speaker_map = speaker_resolver.resolve(unified)
    # → {"SPEAKER_OTHER_1": {"name": "Елена", "confidence": 0.85}}

    # 3. Суммаризация и commitment extraction параллельно
    summary     = summarizer.summarize(unified, speaker_map, template)
    commitments = commitment_extractor.extract(unified, speaker_map)

    # 4. Сохранение
    db.save_call(session_dir, summary, commitments)

    # 5. Уведомления по дедлайнам
    notification_service.schedule(commitments)
```

---

## Часть 2: Лучшие практики (из исследований)

### Speaker Diarization

**Инструменты и когда использовать:**

| Инструмент | Лучший сценарий | DER (2 спикера) | Установка |
|------------|----------------|-----------------|-----------|
| pyannote 3.1 | 3+ спикеров | ~0.25 | pip + HuggingFace токен |
| NeMo MSDD | 2 спикера | ~0.16 | pip + NVIDIA GPU желательно |
| WhisperX | Хочешь всё в одном | ~0.25–0.30 | pip, использует pyannote внутри |

Для типичного call recording (2 человека): **NeMo** точнее. Для конференций 3+ человек: **pyannote**.

**Критически важно**: не применяй diarization к смешанному аудио если есть раздельные треки. Раздельные треки (mic.wav / system.wav) дают DER = 0% для разделения "я / не-я" — никакой алгоритм не даст лучше.

**Merge по таймстампам (рабочий код):**

```python
def merge_by_timestamp(segments_me, segments_others):
    """Объединяем транскрипты с разных треков по времени."""
    all_segments = (
        [{**s, "speaker": "SPEAKER_ME"}    for s in segments_me] +
        [{**s, "speaker": "SPEAKER_OTHER"} for s in segments_others]
    )
    return sorted(all_segments, key=lambda x: x["start"])

def assign_pyannote_speakers(segments_other, diarization_result):
    """Назначаем pyannote-лейблы сегментам system.wav."""
    diarize_df = pd.DataFrame([
        {"start": t.start, "end": t.end, "speaker": spk}
        for t, _, spk in diarization_result.itertracks(yield_label=True)
    ])
    for seg in segments_other:
        mid = (seg["start"] + seg["end"]) / 2
        candidates = diarize_df[
            (diarize_df["start"] <= mid) & (diarize_df["end"] >= mid)
        ]
        seg["speaker"] = candidates.iloc[0]["speaker"] if len(candidates) > 0 \
                         else "SPEAKER_OTHER_UNKNOWN"
    return segments_other
```

**Минимальная длина для надёжного diarization**: ~10–15 секунд аудио на спикера. Сегменты < 3 секунд не используй как базу для кластеризации — применяй diarization к полному аудио и потом ищи, к какому сегменту относится временной диапазон.

**Настройка для коротких пауз** (разговорная речь):
```python
pipeline._segmentation.min_duration_on  = 0.1   # мин. длина speech-сегмента
pipeline._segmentation.min_duration_off = 0.2   # мин. пауза = смена спикера
```

---

### Speaker Resolution из транскрипта

**Три типа паттернов (в порядке убывания уверенности):**

| Тип | Пример | Confidence |
|-----|--------|-----------|
| Самопредставление | "Добрый день, это Елена" | 0.95 |
| Прямое обращение + ответ | "Елена, ты смотрела?" → следующий спикер отвечает | 0.85 |
| Прямое обращение | "Иван, как ты думаешь?" | 0.70 |
| Третье лицо → микрофон | "Дайте слово Дмитрию" → следующий спикер | 0.65 |
| Умозаключение из контекста | | 0.40 |

**Схема вычисления confidence:**
```python
def speaker_confidence(evidence_type, ambiguous=False):
    scores = {
        "self_introduction": 0.95,
        "direct_address_confirmed": 0.85,
        "direct_address": 0.70,
        "third_person_intro": 0.65,
        "contextual": 0.40,
    }
    base = scores.get(evidence_type, 0.30)
    return base * 0.7 if ambiguous else base
```

---

### Лингвистические маркеры обязательств

**Английский:**

| Маркер | Сила | Commitment? |
|--------|------|------------|
| "I will / I'll" + действие | Сильное | Да |
| "I'm going to" | Сильное | Да |
| "I'll handle / take care of" | Сильное | Да |
| "I'll try", "I might" | Слабое | Да, с низким confidence |
| "We should", "Someone needs to" | Нет assignee | Нет |
| "Maybe I'll" | Предположение | Нет |

**Русский (важная особенность — вид глагола):**

| Маркер | Сила | Commitment? |
|--------|------|------------|
| "Я **сделаю** / отправлю / подготовлю" (совершенный вид) | Сильное | Да |
| "Берусь / беру на себя" | Очень сильное | Да |
| "Давай я займусь" | Сильное | Да |
| "Я **буду делать**" (несовершенный вид) | Слабее | Да, но ниже confidence |
| "Постараюсь / попробую" | Слабое | Да, confidence 0.3–0.4 |
| "Нам нужно / надо бы" | Нет assignee | Нет |
| "Мы должны" | Коллективное | Нет (нет конкретного исполнителя) |
| "Я подумаю" | Контекстно-зависимо | Только если явное обещание |

**Правило для русского**: совершенный вид будущего времени ("сделаю") — более сильный маркер commitment чем несовершенный ("буду делать").

**Паттерны дедлайнов:**
```python
DEADLINE_PATTERNS = {
    "ru": [
        r"до (конца дня|пятницы|понедельника|среды|следующей недели|конца месяца)",
        r"к (пятнице|понедельнику|среде|следующей неделе|завтрашнему дню|вечеру)",
        r"(сегодня|завтра|в пятницу|на этой неделе|в следующем месяце)",
        r"через (\d+) (дней?|недель?|часов?)",
        r"как можно скорее|срочно|ASAP",
    ],
    "en": [
        r"by (end of )?(today|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|the week|next week)",
        r"before (the meeting|end of day|EOD|COB)",
        r"(this|next) (Monday|Tuesday|Wednesday|Thursday|Friday|week|month)",
        r"in (\d+) (days?|weeks?|hours?)",
        r"ASAP|as soon as possible|urgently",
    ]
}
```

---

### JSON Extraction для 7B моделей (Ollama qwen2.5)

Из исследований StructuredRAG и ThinkJSON:
- **temperature=0** обязателен для extraction — устраняет вариативность формата
- **Nested objects и arrays** — самые сложные для 7B, используй flat структуру где можно
- **Brief CoT перед JSON** увеличивает faithfulness на 16.8% (SCoT, arxiv)
- **Inline комментарии в schema** работают лучше отдельного описания для 7B моделей

**Шаблон "думай кратко → выдай JSON"** (для 7B):
```
Think step by step:
1. Find all first-person future-tense statements
2. Check each has a specific actor (not "we")
3. Find deadline if present

Then output JSON:
{ ... }
Start with {. No other text.
```

---

## Часть 3: Промпты

### Как передавать контекст в каждый промпт

Перед отправкой промпта добавляй в конец:

```
SPEAKER MAP (pre-resolved):
{speaker_map_json}

TRANSCRIPT:
{unified_transcript_text}

CALL DATE: {call_date}
```

Формат `unified_transcript_text` для вставки в промпт:
```
[00:01:23] SPEAKER_ME: Хорошо, я пришлю тебе предложение до пятницы.
[00:01:31] SPEAKER_OTHER_1 (Елена, conf=0.85): Отлично, буду ждать.
[00:01:45] SPEAKER_OTHER_2: Я тоже посмотрю к понедельнику.
```

---

### Prompt 0: Speaker Resolution

Запускается первым. Принимает raw unified_transcript (с SPEAKER_ME / SPEAKER_OTHER_N).
Возвращает speaker_map. Результат используется всеми последующими промптами.

```
You are analyzing a meeting transcript to identify the real names of speakers.

SPEAKER_ME is already identified — it's the person who owns this app (confirmed via mic channel).
Your job: identify the real names of SPEAKER_OTHER_1, SPEAKER_OTHER_2, etc.

IDENTIFICATION PATTERNS (in order of reliability):
1. SELF-INTRODUCTION (confidence: 0.95)
   Examples: "This is Elena", "My name is Alexander", "Hi, I'm John"
   Russian: "Это Елена", "Меня зовут Александр", "Добрый день, я Иван"

2. DIRECT ADDRESS + RESPONSE (confidence: 0.85)
   If SPEAKER_A says "[Name], can you..." and SPEAKER_B responds immediately → SPEAKER_B = Name
   Russian: "Елена, ты смотрела?" → следующий спикер отвечает → этот спикер = Елена

3. DIRECT ADDRESS without response confirmation (confidence: 0.70)
   "Thanks, Michael" — we know a Michael is present, but which speaker?

4. THIRD-PERSON INTRODUCTION → takes floor (confidence: 0.65)
   "Let me pass the floor to Dmitry" → next speaker = Dmitry
   Russian: "Дайте слово Дмитрию" → следующий спикер = Дмитрий

5. CONTEXTUAL INFERENCE (confidence: 0.40)
   Name appears in conversation but linkage to speaker is indirect.

RULES:
- SPEAKER_ME is always confirmed=true, source="mic_channel", no name inference needed
- If a name cannot be determined — return name: null, confidence: 0.0
- If the same speaker is addressed by two different names — pick the one with higher confidence
- Do not infer names from email addresses, company names, or product names

OUTPUT — valid JSON only, start with {:

{
  "speaker_map": {
    "SPEAKER_ME": {
      "confirmed": true,
      "source": "mic_channel"
    },
    "SPEAKER_OTHER_1": {
      "name": "<first name or full name from transcript>",
      "confidence": 0.0-1.0,
      "source": "self_introduction" | "direct_address_confirmed" | "direct_address" | "third_person_intro" | "contextual" | null,
      "evidence": "<exact quote from transcript that identified this speaker>"
    }
  },
  "resolution_notes": "<any ambiguities or edge cases>"
}
```

---

### Prompt 1: Mira Murati — Продуктовая надёжность

**Философия:** Система работает только если работает всегда. Каждый edge case — это пользователь, который потерял обязательство. Ambiguity — враг. Если модель не уверена — она должна сказать это явно. Структура вывода настолько жёсткая, что сломать её невозможно.

```
You are a commitment extraction engine for a meeting intelligence system. Your only job is to identify, classify, and structure every commitment made during a call.

A commitment is any statement where a person explicitly or implicitly agrees to deliver something to someone by a point in time. Includes: direct promises ("I will send"), agreements ("yes, I'll handle that"), and soft commitments ("I'll try to get this to you by end of week").

Do NOT extract:
- General intentions without a specific owner ("we should probably...")
- Past actions already completed ("I sent you that yesterday")
- Hypotheticals without acceptance ("if we decide to go that route, I could...")
- Meeting agenda topics discussed without conclusion
- Questions or requests (unless the response contains a commitment)

COMMITMENT STRENGTH (Russian-specific rule):
- Perfective future tense: "сделаю", "отправлю", "подготовлю" → confidence boost +0.15
- Imperfective future: "буду делать" → lower baseline confidence
- "Постараюсь", "попробую" → weak commitment, confidence 0.3–0.4
- "Мы должны", "нам нужно" → NOT a commitment (no specific assignee)

INPUT:
You will receive:
1. SPEAKER MAP — pre-resolved names with confidence scores
2. TRANSCRIPT — with speaker labels and timestamps

DIRECTION LOGIC:
- direction="outgoing" if SPEAKER_ME made the commitment (they owe something)
- direction="incoming" if someone else committed to SPEAKER_ME (they are owed something)
- direction="third_party" if neither side is SPEAKER_ME

FOR EACH COMMITMENT extract:
1. direction: "outgoing" | "incoming" | "third_party"
2. committer_label: speaker label (e.g. "SPEAKER_ME", "SPEAKER_OTHER_1")
3. committer_name: from speaker_map if confidence ≥ 0.6, else null
4. committer_name_confidence: inherited from speaker_map confidence
5. recipient_label: who the commitment was made TO
6. recipient_name: from speaker_map or transcript, else null
7. commitment_text: clean action command. Format: "[Verb] [object] [to recipient if named]". Max 25 words.
8. verbatim_quote: exact phrase from transcript
9. timestamp: from transcript
10. deadline_raw: exact deadline phrase from transcript, null if none
11. deadline_type: "explicit_date" | "relative_day" | "relative_week" | "relative_month" | "implied_urgent" | "none"
12. deadline_confidence: "high" (day stated) | "medium" (timeframe stated) | "low" (urgency implied) | "none"
13. commitment_confidence: 0.0–1.0 (how certain this is a real commitment)
14. conditional: true if depends on a condition ("if X then I'll Y")
15. condition_text: the condition if conditional=true, else null

OUTPUT — valid JSON only, start with {:
{
  "commitments": [
    {
      "id": 1,
      "direction": "outgoing" | "incoming" | "third_party",
      "committer_label": "...",
      "committer_name": "<from speaker_map>" | null,
      "committer_name_confidence": 0.0-1.0,
      "recipient_label": "...",
      "recipient_name": "<from transcript>" | null,
      "commitment_text": "...",
      "verbatim_quote": "...",
      "timestamp": "...",
      "deadline_raw": "..." | null,
      "deadline_type": "...",
      "deadline_confidence": "...",
      "commitment_confidence": 0.0-1.0,
      "conditional": false,
      "condition_text": null
    }
  ],
  "extraction_notes": "any ambiguities encountered"
}

If no commitments: {"commitments": [], "extraction_notes": "No commitments detected"}.
No markdown. No text before or after JSON. Start with {
```

---

### Prompt 2: Ilya Sutskever — Глубокое обучение

**Философия:** Обязательство — это семантический паттерн: агент + действие + получатель + временная метка. Модель должна рассуждать цепочкой: кто говорит → что обещается → кому → когда. Chain-of-thought снижает галлюцинации на структурированных задачах. Few-shot примеры учат не правилу, а дистрибуции.

```
You are an expert at semantic role labeling applied to conversational commitment detection.

THEORETICAL FRAMEWORK:
A commitment act has semantic roles:
- AGENT: person who takes on the obligation
- PATIENT: what is being committed to (the deliverable)
- BENEFICIARY: who receives the deliverable
- TEMPORAL: deadline or timeframe
- CONDITION: precondition (optional)

The key challenge: direction from SPEAKER_ME's perspective.
- SPEAKER_ME is AGENT → outgoing (they owe something)
- SPEAKER_ME is BENEFICIARY → incoming (they are owed something)
- Neither → third_party

LINGUISTIC MARKERS — CONFIDENCE LEVELS:

Strong markers (commitment_confidence ≥ 0.85):
EN: "I will/I'll [verb]", "I promise", "I commit to", "I'll handle", "Leave it with me"
RU: "Я сделаю/отправлю/подготовлю" (perfective), "Беру на себя", "Давай я займусь"

Medium markers (0.50–0.84):
EN: "I'll try to", "I plan to", "I should be able to", "I'll make sure"
RU: "Постараюсь", "Планирую", "Я буду делать" (imperfective)

Weak markers (0.25–0.49, include but flag):
EN: "Maybe I'll", "I might", "At some point I'll"
RU: "Может быть я", "Если получится", "Я подумаю"

NOT a commitment (do not extract):
EN: "We should", "Someone needs to", "It would be nice to"
RU: "Нам нужно", "Мы должны", "Надо бы"

DEADLINE EXTRACTION:
When you find a commitment, scan ±5 utterances for temporal anchors:
- Absolute: specific date, day of week
- Relative: "by end of week", "within 2 days", "before our next call"
- Milestone: "before the launch", "after you send me X"
- Urgent: "ASAP", "срочно" → deadline_type: "implied_urgent"

SPEAKER RESOLUTION:
Use the provided SPEAKER MAP. Only assign names when speaker_map confidence ≥ 0.6.
If confidence < 0.6 → use label only, name = null.

CHAIN OF THOUGHT (brief, internal reasoning before JSON):
For each candidate commitment:
Step 1: Who is the AGENT? (who made the promise)
Step 2: Specific action verb + object?
Step 3: Who is the BENEFICIARY?
Step 4: Is this a real obligation or just a suggestion?
Step 5: Is SPEAKER_ME the AGENT or BENEFICIARY?
Step 6: Deadline?

FEW-SHOT EXAMPLES:

Example A — outgoing, strong:
Input: "[00:03:12] SPEAKER_ME: Да, я отправлю тебе контракт до конца дня."
→ direction: "outgoing", commitment_text: "Send the contract", deadline_raw: "до конца дня", commitment_confidence: 0.92

Example B — incoming, strong:
Input: "[00:07:44] SPEAKER_OTHER_1: Хорошо, я изучу это и дам тебе фидбек к среде."
→ direction: "incoming", commitment_text: "Review and provide feedback", deadline_raw: "к среде", commitment_confidence: 0.90

Example C — NOT a commitment:
Input: "[00:12:03] SPEAKER_ME: Мы должны как-нибудь поговорить об этом подробнее."
→ extract nothing. "мы должны" has no specific assignee. "как-нибудь" has no deadline.

Example D — conditional:
Input: "[00:15:20] SPEAKER_ME: Если ты пришлёшь мне данные, я подготовлю презентацию к пятнице."
→ direction: "outgoing", conditional: true, condition_text: "After receiving data from counterpart", deadline_raw: "к пятнице"

OUTPUT — valid JSON, start with {:
{
  "speaker_map_used": {"SPEAKER_OTHER_1": "<name>", ...},
  "commitments": [
    {
      "id": 1,
      "direction": "outgoing" | "incoming" | "third_party",
      "agent_label": "...",
      "agent_name": "<from speaker_map if conf≥0.6>" | null,
      "beneficiary_label": "...",
      "beneficiary_name": "<from speaker_map if conf≥0.6>" | null,
      "commitment_text": "...",
      "verbatim_quote": "...",
      "timestamp": "...",
      "deadline_raw": "..." | null,
      "deadline_type": "explicit_date" | "relative_day" | "relative_week" | "implied_urgent" | "none",
      "commitment_confidence": 0.0-1.0,
      "conditional": false,
      "condition_text": null
    }
  ],
  "extraction_notes": "..."
}
```

---

### Prompt 3: Andrej Karpathy — Фундаментальная простота

**Философия:** Самый опасный момент — когда добавляешь сложность раньше, чем убедился, что простое не работает. Начни с ядра. Задача: найди обещания. Вся сложность — только там, где без неё не обойтись.

*Использовать по умолчанию. Если JSON упал или quality низкий — переходи к Prompt 1.*

```
Read this meeting transcript carefully.

SPEAKER_ME is the person who owns this app — identified via their microphone channel.
Other speakers are SPEAKER_OTHER_1, SPEAKER_OTHER_2, etc. Their names may be in the SPEAKER MAP below.

Your job: find every real promise made during this call.

A real promise is when a specific person says they will do a specific thing for someone.

TWO TYPES that matter:
1. OUTGOING — SPEAKER_ME made the promise → they need to act
2. INCOMING — someone promised SPEAKER_ME something → they are waiting

Think briefly before answering:
- Find all "I will / I'll / я сделаю / я отправлю / беру на себя" statements
- Check each one: is there a real specific actor? (not "we", not "someone")
- Is it a genuine commitment or just a casual mention?
- Then output JSON

IMPORTANT RULES:
1. Real promise = specific person + specific action + directed at someone. "We should do X" is NOT a promise.
2. Russian perfective future ("сделаю") = stronger signal than imperfective ("буду делать").
3. Deadline: copy exact words from transcript. Never interpret. "к пятнице" stays "к пятнице".
4. Names: use SPEAKER MAP names only if confidence ≥ 0.6, otherwise use speaker label.
5. Same promise stated multiple times → extract once.
6. Genuinely unsure? → include it with uncertain: true.

OUTPUT — valid JSON only, start with {:
{
  "commitments": [
    {
      "id": 1,
      "type": "outgoing" | "incoming",
      "who": "SPEAKER_ME" | "SPEAKER_OTHER_1" | "...",
      "who_name": "<from speaker_map if conf≥0.6>" | null,
      "to_whom": "SPEAKER_OTHER_1" | "SPEAKER_ME" | "...",
      "to_whom_name": "<from speaker_map if conf≥0.6>" | null,
      "what": "Send the revised proposal",
      "deadline": "<exact words from transcript>" | null,
      "quote": "<exact phrase that contains the commitment>",
      "timestamp": "00:03:42",
      "uncertain": false
    }
  ]
}
```

---

### Prompt 4: Jony Ive — Человеческий опыт

**Философия:** Мы строим чувство ответственности, не систему извлечения данных. Когда человек видит список обязательств — он должен почувствовать ясность. Каждый элемент списка: глагол + объект + получатель. Трёхсложная команда, которую мозг обрабатывает без усилий.

*Использовать для финальной формулировки commitment_text перед показом в UI.*

```
You are reading a meeting transcript to help a person understand what they owe to others, and what others owe to them.

This is about human accountability. A promise made in a meeting should not vanish into a transcript. It should become a clear item that a person can look at tomorrow morning and immediately know what to do.

SPEAKER_ME is the person using this tool.

EXTRACT COMMITMENTS with these principles:

PRINCIPLE 1 — CLARITY OF ACTION
Every commitment_text must be a clear action command:
GOOD: "Send the budget spreadsheet to [name or 'them']"
BAD: "Something about sending a spreadsheet"
GOOD: "Review the contract draft and provide comments"
BAD: "Contract review commitment"
The action must be specific enough that no re-reading of the transcript is needed.

PRINCIPLE 2 — NAMES OVER LABELS
Use real names from the SPEAKER MAP (confidence ≥ 0.6). If name unknown → use a human description: "the other participant" instead of "SPEAKER_OTHER_1".

PRINCIPLE 3 — HONEST DEADLINES
Copy exact words. Never convert or normalize. "к пятнице" stays "к пятнице".
A commitment without a deadline is still a commitment — mark has_deadline: false.

PRINCIPLE 4 — DIRECTION IS EVERYTHING
The most important signal for the user:
- Am I the one who needs to act? (outgoing)
- Am I the one who waits, and follows up if nothing happens? (incoming)

PRINCIPLE 5 — REMOVE NOISE
Don't extract topics discussed, things that "should" happen with no owner, or past actions.
Only extract moments where someone's word was given.

PRINCIPLE 6 — WEIGHT
- "high": involves money, legal, client relationship, or stated as urgent
- "medium": regular work deliverable with deadline
- "low": casual or nice-to-have

OUTPUT — valid JSON, start with {:
{
  "commitments": [
    {
      "id": 1,
      "direction": "outgoing" | "incoming",
      "commitment_text": "Send the revised proposal to [name or 'them']",
      "committer_name": "<name from speaker_map if conf≥0.6, else null>",
      "recipient_name": "<name from speaker_map or transcript, else null>",
      "deadline": "<exact words from transcript>" | null,
      "has_deadline": true | false,
      "significance": "high" | "medium" | "low",
      "verbatim": "<exact quote>",
      "timestamp": "00:14:22"
    }
  ],
  "headline": "One sentence: the most important commitment from this call."
}
```

---

## Часть 4: Выбор промпта и обработка ошибок

### Когда какой промпт

| Ситуация | Промпт |
|----------|--------|
| Стандартный вызов | Prompt 3 (Карпати) |
| JSON невалидный после Prompt 3 | Prompt 1 (Муратии) |
| Сложный звонок (3+ участника, условные обязательства) | Prompt 2 (Суцкевер) |
| Форматирование текста для UI | Prompt 4 (Айв) |
| Pre-processing: кто есть кто | Prompt 0 (Speaker Resolution) |

### Retry стратегия

```python
def extract_commitments(unified_transcript, speaker_map):
    # Попытка 1: простой промпт
    result = call_ollama(PROMPT_KARPATHY, unified_transcript, speaker_map,
                         temperature=0)
    if is_valid_json(result):
        return result

    # Попытка 2: строгий промпт
    result = call_ollama(PROMPT_MURATI, unified_transcript, speaker_map,
                         temperature=0)
    if is_valid_json(result):
        return result

    # Fallback: пустой список
    return {"commitments": [], "extraction_notes": "extraction failed after 2 attempts"}
```

### Ожидаемые проблемы

| Проблема | Решение |
|----------|---------|
| Модель путает incoming/outgoing | Усиль примеры в Prompt 2, особенно Example B |
| Дедлайны не извлекаются | Добавь паттерны из DEADLINE_PATTERNS в промпт |
| Слишком много false positives | Prompt 3 строже фильтрует — используй его |
| commitment_text нечёткий | Прогони через Prompt 4 как второй шаг |
| JSON невалидный | temperature=0 + retry с Prompt 1 |
| "мы должны" попадает в commitments | Добавь explicit example C из Prompt 2 |

### Зависимости

| Зависимость | Зачем | Обязательна? |
|-------------|-------|--------------|
| mlx_whisper | Раздельная транскрипция mic.wav + system.wav | Да (уже есть) |
| pyannote.audio 3.1 | Diarization внутри system.wav (3+ участника) | Нет — без неё все собеседники = SPEAKER_OTHER |
| HuggingFace токен | Нужен для pyannote моделей | Только с pyannote |
| NeMo | Лучше для 2-спикерных звонков (ниже DER) | Нет, опционально |
| HeidelTime | Нормализация дат ("к пятнице" → 2026-02-28) | Нет, опционально |
