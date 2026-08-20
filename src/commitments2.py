"""Call Recorder — commitment extraction v2: narrow, staged, verified.

Night-build core (2026-08-20). The old path asked one big summarization call
to also produce commitments — the field competed with seven others and died
in decoding (5→2→0 on identical input). This module decomposes the task:

  stage 1 (code):  regex candidates over merged turns — commissive verbs,
                   cohortatives («давайте синхронимся»), immediacy deictics
                   («сейчас скину»), modal reinforcement;
  stage 2 (LLM):   one NARROW classification call per candidate with a ±1-turn
                   context window, repeated `votes` times; consensus >= 2 of 3
                   is confident, a single yes-vote is KEPT but flagged
                   uncertain (visibility over silent drops — board rule);
  stage 3 (code):  verbatim-quote verification (exact after normalization,
                   fuzzy fallback), committer attestation, dedup by quote
                   overlap.

Nothing here writes to the database; the daemon feeds the result to
insert_commitments (Karpathy format: type/who/what/...).
"""

import difflib
import json
import logging
import re
import urllib.request

from .config import OLLAMA_MODEL, OLLAMA_URL
from .summarizer import Summarizer

log = logging.getLogger("call-recorder")

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")

# Stage-1 candidate patterns (case-insensitive). Soft commissives are first-
# class: «давайте синхронимся» is linguistically as binding as «пришлю».
CANDIDATE_PATTERNS = [
    # hard commissives: 1st person future perfective
    re.compile(
        r"\b(пришлю|скину|отправлю|подготовлю|сделаю|передам|созвонюсь|напишу|"
        r"проверю|уточню|согласую|оформлю|заплачу|перезвоню|занесу|организую|"
        r"соберу|запишу|поставлю|добавлю|посмотрю|вышлю|поделюсь)\b",
        re.IGNORECASE,
    ),
    # cohortative / joint-action invitation — the "soft" promises
    re.compile(
        r"\b(давай(?:те)?)\b.{0,30}\b(синхрон\w+|созвон\w+|встрет\w+|обсуд\w+|"
        r"сдела\w+|посмотр\w+|провед\w+|запиш\w+)",
        re.IGNORECASE,
    ),
    # immediacy deictic
    re.compile(
        r"\b(сейчас|щас|прямо сейчас|сегодня же)\b.{0,20}\b(скину|пришлю|сделаю|"
        r"отправлю|напишу|поставлю)\b",
        re.IGNORECASE,
    ),
    # modal reinforcement — only WITH an action verb («Да, да, обязательно.»
    # без глагола — вежливое поддакивание, не обещание; polish cycle 3)
    re.compile(
        r"(?=.*\b(?:обязательно|не забуду|я обещаю|беру на себя)\b)"
        r"(?=.*\b(?:сдела|приш[лн]|скин|отправ|подготов|провер|напиш|позвон|"
        r"созвон|постав|собер|организ|оформ|переда|уточн|запиш)\w*)",
        re.IGNORECASE,
    ),
    # 1pl strong perfective — rare, unconditionally commissive
    re.compile(
        r"\b(созвонимся|синхронизируемся|встретимся|договоримся|скинем|"
        r"пришл[её]м|вышлем)\b",
        re.IGNORECASE,
    ),
    # 1pl weak/instructional — candidate only with a time anchor in the line
    # («мы будем называть субагентов» — инструктаж, не обещание; «будем делать
    # в пятницу» — обещание). Reviewer-verified: candidates 125 -> ~50.
    re.compile(
        r"(?=.*\b(?:будем|сделаем|обсудим|собер[её]м|запустим|подготовим|"
        r"напишем|проверим|запишем)\b)"
        r"(?=.*\b(?:понедельник|вторник|сред[ау]|четверг|пятниц\w*|суббот\w*|"
        r"воскресень\w*|завтра|послезавтра|сегодня|вечером|утром|"
        r"на следующей неделе|после (?:звонка|встречи|созвона|обеда)|"
        r"через (?:час|день|неделю)))",
        re.IGNORECASE,
    ),
]

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_commitment": {"type": "boolean"},
        "confidence": {"type": "string"},
        "committer": {"type": "string"},
        "recipient": {"type": "string"},
        "text": {"type": "string"},
        "deadline": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["is_commitment", "committer", "text", "quote"],
    "additionalProperties": False,
}

CLASSIFY_PROMPT = """Ты — лингвист-эксперт по речевым актам обязательства \
(commissive speech acts). Твоя ЕДИНСТВЕННАЯ задача — решить, содержит ли \
ВЫДЕЛЕННАЯ строка обещание, и если да — извлечь его точно.

ОПРЕДЕЛЕНИЕ: обещание — говорящий связывает СЕБЯ обязательством совершить \
будущее действие (включая мягкие формы: «давайте синхронимся», «сейчас скину»). \
Условное или сценарное обещание — «пока ты делаешь X, я сделаю Y», «мы будем \
делать это в пятницу, наверное» — это ТОЖЕ обещание: хеджирование («наверное», \
«например») снижает confidence, но не отменяет обязательства, если говорящий \
называет СВОЁ будущее действие. НЕ обещание: вопрос («скинешь?»), просьба или \
поручение собеседнику («можешь скинуть?», «скинь ему», «посмотри»), пересказ \
чужого действия («он сказал, что пришлёт»), факт о будущем без обязательства \
(«встреча в пятницу»).

КОНТЕКСТ:
{context}

КАНДИДАТ: "{line}"

Выведи ТОЛЬКО JSON. committer — метка спикера или имя СТРОГО из контекста. \
quote — ДОСЛОВНАЯ подстрока контекста, символ в символ, не пересказ. Если \
обещания нет — is_commitment=false и пустые строки."""


TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

TITLE_PROMPT = """Сожми обещание в короткий заголовок вида «глагол — предмет — \
срок».

Правила:
- используй ТОЛЬКО слова из ЦИТАТЫ и СРОКА, в той же форме
- новые слова, имена и факты запрещены
- выбрось слова-паразиты, вводные и повторы; глагол поставь первым
- 2-7 слов

Примеры:
ЦИТАТА: "А, давайте я лучше в Telegram скину." → {{"title": "скину в Telegram"}}
ЦИТАТА: "я пришлю договор, наверное, уже в пятницу" СРОК: "в пятницу" → \
{{"title": "пришлю договор в пятницу"}}
ЦИТАТА: "Давай дам. Я тебе скину тогда все сейчас после звонка." → \
{{"title": "скину все после звонка"}}

Пустую строку title верни ТОЛЬКО если в цитате совсем нет глагола будущего \
действия.

ЦИТАТА: "{quote}"
СРОК: "{deadline}"

Выведи ТОЛЬКО JSON."""


def _title_grounded(title: str, source: str) -> bool:
    """Every content word of the title must occur in the source (5-char stems,
    same convention as evaluation): compression may drop words, never add."""
    src = {w[:5] for w in re.findall(r"\w+", source.lower()) if len(w) > 2}
    for w in re.findall(r"\w+", title.lower()):
        if len(w) <= 2 or w.isdigit():
            continue
        if w[:5] not in src:
            return False
    return True


def normalize_title(quote: str, deadline: str = "", llm=None) -> str | None:
    """Compress a commitment into a scannable title without touching the quote.

    The quote stays verbatim evidence; a title that fails grounding is
    discarded — raw ASR text is better than a pretty invention."""
    if not (quote or "").strip():
        return None
    llm = llm or _call_llm
    out = llm(
        TITLE_PROMPT.format(quote=quote, deadline=deadline or "не указан"),
        temperature=0.0,
        schema=TITLE_SCHEMA,
    )
    if not isinstance(out, dict):
        return None
    title = (out.get("title") or "").strip()
    if not title or len(title) > 90:
        return None
    if not _title_grounded(title, f"{quote} {deadline or ''}"):
        return None
    return title


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[«»\"'`]", "", text)
    text = re.sub(r"[—–-]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (text or "").lower()) if len(t) > 2}


def find_candidates(transcript: str) -> list[dict]:
    """Stage 1: candidate lines with a ±1-line context window."""
    lines = [l for l in (transcript or "").splitlines() if l.strip()]
    candidates = []
    for i, line in enumerate(lines):
        if any(p.search(line) for p in CANDIDATE_PATTERNS):
            window = lines[max(0, i - 1) : i + 2]
            candidates.append({"line": line.strip(), "context": "\n".join(window)})
    return candidates


def verify_quote(quote: str, context: str) -> str:
    """Stage 3: is the quote really in the context? exact | fuzzy | failed."""
    q, c = _normalize(quote), _normalize(context)
    if q and q in c:
        return "exact"
    q_tokens = _tokens(quote)
    if q_tokens and len(q_tokens & _tokens(context)) / len(q_tokens) >= 0.6:
        return "fuzzy"
    if difflib.SequenceMatcher(None, q, c).ratio() >= 0.8:
        return "fuzzy"
    return "failed"


def _call_llm(
    prompt: str, temperature: float = 0.25, schema: dict | None = None
) -> dict | None:
    """Default LLM adapter (Ollama chat, closed schema). Tests inject stubs."""
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,  # narrow classification needs no reasoning budget
            "format": schema or CLASSIFY_SCHEMA,
            "options": {"temperature": temperature, "num_predict": 512},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        CHAT_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return json.loads(result["message"]["content"])
    except Exception as e:
        log.warning(f"commitments2 LLM call failed: {e}")
        return None


def extract_commitments(transcript: str, llm=None, votes: int = 3) -> list[dict]:
    """Full v2 pipeline → list in the DB's Karpathy format.

    Every returned item carries uncertain (consensus < 2 of votes),
    confidence_votes ("2/3") and verified ("exact"|"fuzzy"|"failed").
    Failed-verification items are kept but flagged uncertain — visibility
    over silent drops (board rule).
    """
    llm = llm or _call_llm
    results: list[dict] = []

    for cand in find_candidates(transcript):
        prompt = CLASSIFY_PROMPT.format(context=cand["context"], line=cand["line"])
        yes_votes: list[dict] = []
        for _ in range(votes):
            verdict = llm(prompt, temperature=0.25)
            if isinstance(verdict, dict) and verdict.get("is_commitment"):
                yes_votes.append(verdict)
        if not yes_votes:
            continue

        best = max(yes_votes, key=lambda v: len(v.get("quote") or ""))
        committer = (best.get("committer") or "").strip()
        text = (best.get("text") or "").strip()
        if not committer or not text:
            continue
        if not Summarizer._owner_attested(committer, [], cand["context"]):
            log.info(f"commitments2: unattested committer {committer!r} dropped")
            continue

        verified = verify_quote(best.get("quote") or "", cand["context"])
        cand_ts = Summarizer._parse_ts(cand["line"])
        uncertain = 1 if (len(yes_votes) * 2 < votes or verified == "failed") else 0
        results.append(
            {
                "type": Summarizer._direction(committer),
                "who": committer,
                "to_whom": (best.get("recipient") or "").strip() or None,
                "what": text,
                "deadline": (best.get("deadline") or "").strip() or None,
                "quote": (best.get("quote") or "").strip() or None,
                "uncertain": uncertain,
                "confidence_votes": f"{len(yes_votes)}/{votes}",
                "verified": verified,
                "_ts": cand_ts,
            }
        )

    # Dedup: token overlap OR (близкие таймкоды + слабый overlap) — фрагмент
    # «сейчас скину» и «в Telegram скину» через 10 секунд — одно обещание;
    # выживает более длинная формулировка (reviewer, polish cycle 1).
    deduped: list[dict] = []
    for item in results:
        item_tokens = _tokens(item.get("quote") or item["what"])
        duplicate_of = None
        for kept in deduped:
            if kept["who"] != item["who"]:
                continue
            kept_tokens = _tokens(kept.get("quote") or kept["what"])
            if not (item_tokens and kept_tokens):
                continue
            overlap = len(item_tokens & kept_tokens) / min(
                len(item_tokens), len(kept_tokens)
            )
            near = (
                item.get("_ts") is not None
                and kept.get("_ts") is not None
                and abs(item["_ts"] - kept["_ts"]) <= 45
            )
            if overlap >= 0.6 or (near and overlap >= 0.25):
                duplicate_of = kept
                break
        if duplicate_of is None:
            deduped.append(item)
        elif len(item.get("quote") or item["what"]) > len(
            duplicate_of.get("quote") or duplicate_of["what"]
        ):
            deduped[deduped.index(duplicate_of)] = item
    for item in deduped:
        item.pop("_ts", None)
    return deduped
