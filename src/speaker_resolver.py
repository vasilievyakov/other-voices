"""Call Recorder — speaker resolution from transcript context."""

import json
import logging
import re
import urllib.request
import urllib.error

from .config import OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger("call-recorder")

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")

SPEAKER_RESOLUTION_PROMPT = """\
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
    "SPEAKER_ME": {"confirmed": true, "source": "mic_channel"},
    "SPEAKER_OTHER_1": {
      "name": "<first name or full name from transcript>",
      "confidence": 0.0-1.0,
      "source": "self_introduction" | "direct_address_confirmed" | "direct_address" | "third_person_intro" | "contextual" | null,
      "evidence": "<exact quote from transcript that identified this speaker>"
    }
  },
  "resolution_notes": "<any ambiguities or edge cases>"
}"""

_FALLBACK_MAP = {"SPEAKER_ME": {"confirmed": True, "source": "mic_channel"}}


def _format_segments_for_prompt(segments: list[dict]) -> str:
    """Format unified segments as timestamped transcript text for the LLM prompt.

    Each segment becomes:
        [M:SS] SPEAKER_LABEL: text
    """
    lines = []
    for seg in segments:
        start = seg.get("start", 0.0)
        minutes = int(start) // 60
        seconds = int(start) % 60
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{minutes}:{seconds:02d}] {speaker}: {text}")
    return "\n".join(lines)


def _strip_think_block(text: str) -> str:
    """Remove <think>...</think> blocks that may leak into model content."""
    if "<think>" in text:
        match = re.search(r"<think>.*?</think>\s*", text, re.DOTALL)
        if match:
            text = text[match.end() :].strip()
    return text


def _parse_speaker_map(response_text: str) -> dict | None:
    """Parse speaker map JSON from model response.

    Handles markdown wrapping and extracts the speaker_map key if present.
    Returns the speaker map dict or None on failure.
    """
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    # If response has speaker_map key, extract it
    if "speaker_map" in parsed:
        return parsed["speaker_map"]

    # Otherwise treat the whole response as the map
    return parsed


def resolve_speakers(unified_segments: list[dict]) -> dict:
    """Resolve speaker identities from transcript context.

    Args:
        unified_segments: list of {"start", "end", "text", "speaker"}
                         where speaker is "SPEAKER_ME" or "SPEAKER_OTHER" etc.

    Returns:
        Speaker map dict, e.g.:
        {
            "SPEAKER_ME": {"confirmed": true, "source": "mic_channel"},
            "SPEAKER_OTHER": {"name": "Elena", "confidence": 0.85,
                              "source": "direct_address_confirmed"}
        }

        Returns minimal map with just SPEAKER_ME confirmed if Ollama fails.
    """
    if not unified_segments:
        log.info("No segments provided for speaker resolution")
        return dict(_FALLBACK_MAP)

    transcript_text = _format_segments_for_prompt(unified_segments)
    if not transcript_text:
        log.info("Empty transcript text for speaker resolution")
        return dict(_FALLBACK_MAP)

    prompt = f"{SPEAKER_RESOLUTION_PROMPT}\n\nTRANSCRIPT:\n{transcript_text}"

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2048,
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
        log.info(f"Resolving speakers via Ollama ({OLLAMA_MODEL})...")
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning(f"Ollama unavailable for speaker resolution: {e}")
        return dict(_FALLBACK_MAP)

    message = result.get("message", {})
    response_text = message.get("content", "").strip()

    # Log thinking if present
    thinking = message.get("thinking", "")
    if thinking:
        log.info(f"Speaker resolution thinking: {len(thinking)} chars")

    # Strip thinking block if it leaked into content
    response_text = _strip_think_block(response_text)

    if not response_text:
        log.warning("Empty response from Ollama for speaker resolution")
        return dict(_FALLBACK_MAP)

    speaker_map = _parse_speaker_map(response_text)
    if speaker_map is None:
        log.warning(f"Failed to parse speaker resolution JSON: {response_text[:200]}")
        return dict(_FALLBACK_MAP)

    # Always ensure SPEAKER_ME is in the map with confirmed=true
    if "SPEAKER_ME" not in speaker_map:
        speaker_map["SPEAKER_ME"] = {"confirmed": True, "source": "mic_channel"}
    else:
        speaker_map["SPEAKER_ME"]["confirmed"] = True
        speaker_map["SPEAKER_ME"]["source"] = "mic_channel"

    log.info(f"Speaker resolution complete: {len(speaker_map)} speakers identified")
    return speaker_map


def format_transcript_for_prompt(segments: list[dict], speaker_map: dict) -> str:
    """Format segments with resolved names for downstream prompts.

    Output format:
        [00:01:23] SPEAKER_ME: Хорошо, я пришлю тебе предложение до пятницы.
        [00:01:31] SPEAKER_OTHER (Елена, conf=0.85): Отлично, буду ждать.

    Args:
        segments: list of {"start", "end", "text", "speaker"} dicts.
        speaker_map: resolved speaker map from resolve_speakers().

    Returns:
        Formatted transcript string.
    """
    lines = []
    for seg in segments:
        start = seg.get("start", 0.0)
        hours = int(start) // 3600
        minutes = (int(start) % 3600) // 60
        seconds = int(start) % 60
        timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"

        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "").strip()
        if not text:
            continue

        info = speaker_map.get(speaker)
        if info and info.get("name"):
            conf = info.get("confidence", 0.0)
            label = f"{speaker} ({info['name']}, conf={conf:.2f})"
        else:
            label = speaker

        lines.append(f"{timestamp} {label}: {text}")

    return "\n".join(lines)
