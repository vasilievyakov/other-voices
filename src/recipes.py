"""Call Recorder — recipe engine for one-shot insights."""

import json
import logging
import urllib.request
import urllib.error

from .config import OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger("call-recorder")

RECIPES = {
    "action-items": {
        "name": "action-items",
        "display_name": "Action Items",
        "description": "Extract tasks with owners and deadlines",
        "prompt": (
            "Extract all action items, tasks, and commitments from this call.\n"
            "For each item: @Name: what needs to be done [by deadline if mentioned]\n"
            "Rules:\n"
            "- Only include explicit commitments — things someone agreed to do\n"
            "- Do NOT include general suggestions or topics discussed without commitment\n"
            "- If no owner was named, write @TBD\n"
            "- If no deadline mentioned, omit the deadline part\n"
            "- Do not invent tasks not discussed in the call\n"
            "Format as a numbered list. Respond in the transcript's language."
        ),
    },
    "follow-up-email": {
        "name": "follow-up-email",
        "display_name": "Follow-up Email",
        "description": "Generate a follow-up email draft",
        "prompt": (
            "Write a follow-up email based on this call. Requirements:\n"
            "- Subject line: specific topic, NOT 'Following up on our call'\n"
            "- Opening: 1 sentence — the most important outcome or commitment\n"
            "- Body: bullet points for each agreed next step with owner and deadline\n"
            "- Closing: 1 sentence about the next interaction (next call, deadline)\n"
            "- Tone: direct and specific, not corporate-polite\n"
            "- Maximum 150 words total\n"
            "- Mark any uncertain details with [VERIFY]\n"
            "- Only include facts explicitly stated in the call\n"
            "Respond in the transcript's language."
        ),
    },
    "risks": {
        "name": "risks",
        "display_name": "Risks & Blockers",
        "description": "Identify risks, blockers, and concerns",
        "prompt": (
            "Identify risks, blockers, and concerns from this call.\n"
            "For each:\n"
            "- State the risk in one specific sentence (not vague)\n"
            "- Severity: HIGH = threatens main goal; MEDIUM = delays but doesn't block; "
            "LOW = worth noting\n"
            "- Evidence: quote or closely paraphrase the relevant moment\n"
            "- Status: 'raised but unaddressed', 'acknowledged with plan', or 'dismissed'\n"
            "Only include risks explicitly mentioned by participants. "
            "Do NOT invent risks from general knowledge about the topic.\n"
            "Respond in the transcript's language."
        ),
    },
    "key-decisions": {
        "name": "key-decisions",
        "display_name": "Key Decisions",
        "description": "All decisions with context and rationale",
        "prompt": (
            "List all decisions made during this call, in chronological order.\n"
            "For each:\n"
            "- Decision: exactly what was agreed (with amounts, dates, names)\n"
            "- Who: who made or approved it\n"
            "- Rationale: why this option was chosen\n"
            "- Alternatives: what other options were discussed and rejected\n"
            "A DECISION requires a specific choice that closes an open question.\n"
            "NOT a decision: opinions, 'we should probably...', or topics discussed "
            "without resolution.\n"
            "If no decisions were made, say so explicitly.\n"
            "Respond in the transcript's language."
        ),
    },
    "tldr": {
        "name": "tldr",
        "display_name": "TL;DR",
        "description": "Three-sentence summary",
        "prompt": (
            "Write exactly 3 sentences summarizing this call:\n"
            "Sentence 1: Why this call happened and who was involved.\n"
            "Sentence 2: The single most important thing decided or discovered.\n"
            "Sentence 3: The one action that must happen next, and by whom.\n"
            "No bullet points. Plain prose. Under 80 words total.\n"
            "Do not start with 'In this call...' — start with the main point.\n"
            "Respond in the transcript's language."
        ),
    },
}


def get_recipe(name: str) -> dict | None:
    """Get a recipe by name."""
    return RECIPES.get(name)


def list_recipes() -> list[dict]:
    """Return all recipes."""
    return list(RECIPES.values())


def run_recipe(
    name: str,
    transcript: str,
    summary_json: dict | None = None,
) -> str | None:
    """Run a recipe against a transcript. Returns text output or None on failure."""
    recipe = RECIPES.get(name)
    if not recipe:
        log.warning(f"Unknown recipe: {name}")
        return None

    if not transcript or len(transcript.strip()) < 50:
        log.info("Transcript too short for recipe")
        return None

    max_chars = 50000
    text = transcript[:max_chars] if len(transcript) > max_chars else transcript

    context_parts = [recipe["prompt"], "", "TRANSCRIPT:", text]

    if summary_json:
        context_parts.insert(
            1,
            f"\nEXISTING SUMMARY: {json.dumps(summary_json, ensure_ascii=False)[:2000]}\n",
        )

    prompt = "\n".join(context_parts)

    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 1024,
                "num_ctx": 32768,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        log.info(f"Running recipe '{name}' via Ollama ({OLLAMA_MODEL})...")
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning(f"Ollama unavailable: {e}")
        return None

    return result.get("response", "").strip()
