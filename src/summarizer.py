"""Call Recorder — Ollama-based summarization."""

import json
import logging
import urllib.request
import urllib.error

from .config import OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger("call-recorder")

SUMMARY_PROMPT = """\
Ты анализируешь транскрипт звонка. Извлеки структурированную информацию.

Ответь строго в JSON формате (без markdown):
{
  "summary": "краткое описание звонка в 2-3 предложения",
  "key_points": ["ключевой момент 1", "ключевой момент 2"],
  "decisions": ["решение 1", "решение 2"],
  "action_items": ["задача 1 (@кто, дедлайн если есть)", "задача 2"],
  "participants": ["имя1", "имя2"]
}

Если какое-то поле не определяется из транскрипта, используй пустой список [].
Отвечай на том же языке, что и транскрипт.

ТРАНСКРИПТ:
"""


class Summarizer:
    """Summarizes call transcripts using Ollama."""

    def summarize(self, transcript: str) -> dict | None:
        """Generate summary from transcript. Returns dict or None if Ollama unavailable."""
        if not transcript or len(transcript.strip()) < 50:
            log.info("Transcript too short for summarization")
            return None

        # Truncate very long transcripts to fit model context
        max_chars = 12000
        text = transcript[:max_chars] if len(transcript) > max_chars else transcript

        prompt = SUMMARY_PROMPT + text

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
            log.info(f"Calling Ollama ({OLLAMA_MODEL})...")
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            log.warning(f"Ollama unavailable: {e}")
            return None

        response_text = result.get("response", "").strip()

        # Try to parse JSON from response
        try:
            # Handle potential markdown wrapping
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(l for l in lines if not l.startswith("```"))
            summary = json.loads(response_text)
            log.info("Summary generated successfully")
            return summary
        except json.JSONDecodeError:
            log.warning(
                f"Failed to parse Ollama response as JSON: {response_text[:200]}"
            )
            # Return raw text as fallback
            return {
                "summary": response_text,
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
