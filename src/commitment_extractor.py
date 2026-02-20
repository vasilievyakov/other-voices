"""Call Recorder — commitment extraction from call transcripts."""

import json
import logging
import re
import urllib.request
import urllib.error

from .chunking import chunk_transcript
from .config import OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger("call-recorder")

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")

# Chunk size for long transcripts (~30 min of conversation)
CHUNK_MAX_CHARS = 25000
CHUNK_OVERLAP = 2000

# ---------------------------------------------------------------------------
# Extraction prompts
# ---------------------------------------------------------------------------

PROMPT_KARPATHY = """\
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
4. Names: use SPEAKER MAP names only if confidence >= 0.6, otherwise use speaker label.
5. Same promise stated multiple times → extract once.
6. Genuinely unsure? → include it with uncertain: true.

OUTPUT — valid JSON only, start with {:
{
  "commitments": [
    {
      "id": 1,
      "type": "outgoing" | "incoming",
      "who": "SPEAKER_ME" | "SPEAKER_OTHER_1" | "...",
      "who_name": "<from speaker_map if conf>=0.6>" | null,
      "to_whom": "SPEAKER_OTHER_1" | "SPEAKER_ME" | "...",
      "to_whom_name": "<from speaker_map if conf>=0.6>" | null,
      "what": "Send the revised proposal",
      "deadline": "<exact words from transcript>" | null,
      "quote": "<exact phrase that contains the commitment>",
      "timestamp": "00:03:42",
      "uncertain": false
    }
  ]
}"""

PROMPT_MURATI = """\
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
- "Постараюсь", "попробую" → weak commitment, confidence 0.3-0.4
- "Мы должны", "нам нужно" → NOT a commitment (no specific assignee)

DIRECTION LOGIC:
- direction="outgoing" if SPEAKER_ME made the commitment
- direction="incoming" if someone else committed to SPEAKER_ME
- direction="third_party" if neither side is SPEAKER_ME

OUTPUT — valid JSON only, start with {:
{
  "commitments": [
    {
      "id": 1,
      "direction": "outgoing" | "incoming" | "third_party",
      "committer_label": "...",
      "committer_name": "<from speaker_map if conf>=0.6>" | null,
      "recipient_label": "...",
      "recipient_name": "<from transcript>" | null,
      "commitment_text": "...",
      "verbatim_quote": "...",
      "timestamp": "...",
      "deadline_raw": "..." | null,
      "deadline_type": "explicit_date" | "relative_day" | "relative_week" | "relative_month" | "implied_urgent" | "none",
      "commitment_confidence": 0.0,
      "conditional": false,
      "condition_text": null
    }
  ],
  "extraction_notes": "any ambiguities encountered"
}"""

# Prompt registry keyed by internal name
_PROMPTS = {
    "karpathy": PROMPT_KARPATHY,
    "murati": PROMPT_MURATI,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_full_prompt(
    prompt_text: str,
    transcript_text: str,
    speaker_map: dict,
    call_date: str | None,
) -> str:
    """Assemble the final prompt with context appended."""
    return (
        f"{prompt_text}\n\n"
        f"SPEAKER MAP (pre-resolved):\n"
        f"{json.dumps(speaker_map, ensure_ascii=False, indent=2)}\n\n"
        f"CALL DATE: {call_date or 'unknown'}\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
    )


def _call_ollama(prompt: str) -> str | None:
    """Send a prompt to Ollama /api/chat and return the content string.

    Returns None if Ollama is unreachable or the response is malformed.
    """
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 16384,
                "num_ctx": 32768,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning(f"Ollama unavailable: {e}")
        return None

    message = result.get("message", {})
    response_text = message.get("content", "").strip()

    # Log thinking if present
    thinking = message.get("thinking", "")
    if thinking:
        log.info(f"Model thinking: {len(thinking)} chars")

    return response_text


def _parse_json(raw: str) -> dict | None:
    """Extract and parse JSON from model output.

    Handles think-block leakage and markdown code fences.
    """
    text = raw

    # Strip <think> blocks if leaked into content
    if "<think>" in text:
        think_match = re.search(r"<think>.*?</think>\s*", text, re.DOTALL)
        if think_match:
            text = text[think_match.end() :].strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))

    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    # Validate structure
    if isinstance(parsed, dict) and isinstance(parsed.get("commitments"), list):
        return parsed

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _extract_single(
    transcript_text: str,
    speaker_map: dict,
    call_date: str | None,
) -> dict:
    """Extract commitments from a single chunk of transcript.

    Uses Karpathy prompt by default, falls back to Murati if JSON parsing fails.
    """
    attempts = [
        ("karpathy", PROMPT_KARPATHY),
        ("murati", PROMPT_MURATI),
    ]

    for prompt_name, prompt_text in attempts:
        full_prompt = _build_full_prompt(
            prompt_text,
            transcript_text,
            speaker_map,
            call_date,
        )

        log.info(
            f"Extracting commitments via Ollama ({OLLAMA_MODEL}), "
            f"prompt={prompt_name}..."
        )

        raw = _call_ollama(full_prompt)
        if raw is None:
            return {
                "commitments": [],
                "extraction_notes": "Ollama unavailable",
            }

        parsed = _parse_json(raw)
        if parsed is not None:
            commitments = parsed["commitments"]
            outgoing = sum(
                1
                for c in commitments
                if c.get("type") == "outgoing" or c.get("direction") == "outgoing"
            )
            incoming = sum(
                1
                for c in commitments
                if c.get("type") == "incoming" or c.get("direction") == "incoming"
            )
            log.info(
                f"Extracted {len(commitments)} commitments "
                f"(outgoing={outgoing}, incoming={incoming}) "
                f"using prompt={prompt_name}"
            )
            return parsed

        log.warning(
            f"JSON parse failed for prompt={prompt_name}, response preview: {raw[:200]}"
        )

    log.warning("Commitment extraction failed after 2 attempts")
    return {
        "commitments": [],
        "extraction_notes": "extraction failed after 2 attempts",
    }


def _deduplicate_commitments(commitments: list[dict]) -> list[dict]:
    """Remove duplicate commitments across chunks using quote similarity."""
    seen: set[str] = set()
    unique: list[dict] = []

    for c in commitments:
        # Build a dedup key from the commitment's core content
        key_parts = [
            c.get("what") or c.get("commitment_text") or "",
            c.get("who") or c.get("committer_label") or "",
            c.get("to_whom") or c.get("recipient_label") or "",
        ]
        key = "|".join(p.strip().lower() for p in key_parts)
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
        elif not key:
            # No key — keep it to avoid dropping data
            unique.append(c)

    return unique


def extract_commitments(
    transcript_text: str,
    speaker_map: dict,
    call_date: str | None = None,
) -> dict:
    """Extract commitments from a call transcript.

    For long transcripts (>25K chars), splits into chunks, extracts from
    each independently, then merges and deduplicates results.

    Args:
        transcript_text: Formatted transcript with speaker labels and timestamps.
        speaker_map: Resolved speaker identities.
        call_date: ISO date of the call for deadline context.

    Returns:
        dict with "commitments" list. Empty list if extraction fails.
    """
    if not transcript_text or len(transcript_text.strip()) < 50:
        return {"commitments": [], "extraction_notes": "transcript too short"}

    chunks = chunk_transcript(transcript_text, CHUNK_MAX_CHARS, CHUNK_OVERLAP)

    if len(chunks) == 1:
        return _extract_single(transcript_text, speaker_map, call_date)

    # Long transcript — extract from each chunk, then merge
    log.info(
        f"Long transcript ({len(transcript_text)} chars), "
        f"splitting into {len(chunks)} chunks for commitment extraction"
    )

    all_commitments: list[dict] = []
    notes_parts: list[str] = []

    for i, chunk in enumerate(chunks):
        log.info(f"Extracting commitments from chunk {i + 1}/{len(chunks)}...")
        result = _extract_single(chunk, speaker_map, call_date)
        chunk_commitments = result.get("commitments", [])

        # Re-number IDs to avoid collisions
        base_id = len(all_commitments)
        for j, c in enumerate(chunk_commitments):
            c["id"] = base_id + j + 1

        all_commitments.extend(chunk_commitments)

        if result.get("extraction_notes"):
            notes_parts.append(f"chunk {i + 1}: {result['extraction_notes']}")

    # Deduplicate commitments from overlapping chunks
    unique = _deduplicate_commitments(all_commitments)

    # Re-number final IDs sequentially
    for i, c in enumerate(unique):
        c["id"] = i + 1

    log.info(
        f"Commitment extraction complete: {len(all_commitments)} raw → "
        f"{len(unique)} unique ({len(chunks)} chunks)"
    )

    result = {"commitments": unique, "_chunks": len(chunks)}
    if notes_parts:
        result["extraction_notes"] = "; ".join(notes_parts)

    return result


def list_prompts() -> list[dict]:
    """Return available extraction prompts for UI selection."""
    return [
        {
            "name": "karpathy",
            "display_name": "Simple & Reliable",
            "description": "Default. Clear rules, minimal complexity.",
        },
        {
            "name": "murati",
            "display_name": "Strict & Detailed",
            "description": "Fallback. More fields, stricter classification.",
        },
    ]
