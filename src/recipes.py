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
            "Extract all action items, tasks, and commitments from this call. "
            "For each item, include: who is responsible (@name), what needs to be done, "
            "and any mentioned deadline. Format as a numbered list."
        ),
    },
    "follow-up-email": {
        "name": "follow-up-email",
        "display_name": "Follow-up Email",
        "description": "Generate a follow-up email draft",
        "prompt": (
            "Write a professional follow-up email based on this call. "
            "Include: greeting, summary of what was discussed, agreed next steps, "
            "and a closing. Keep it concise and actionable."
        ),
    },
    "risks": {
        "name": "risks",
        "display_name": "Risks & Blockers",
        "description": "Identify risks, blockers, and concerns",
        "prompt": (
            "Identify all risks, blockers, concerns, and potential issues mentioned "
            "or implied in this call. For each, note the severity (high/medium/low) "
            "and any suggested mitigation."
        ),
    },
    "key-decisions": {
        "name": "key-decisions",
        "display_name": "Key Decisions",
        "description": "All decisions with context and rationale",
        "prompt": (
            "List all decisions made during this call. For each decision, include: "
            "what was decided, who made or approved it, the rationale or context, "
            "and any alternatives that were considered."
        ),
    },
    "tldr": {
        "name": "tldr",
        "display_name": "TL;DR",
        "description": "One paragraph summary",
        "prompt": (
            "Write a single concise paragraph (3-5 sentences) summarizing this call. "
            "Focus on the most important outcome, key decision, and immediate next step."
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

    max_chars = 12000
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
