"""Call Recorder — Ollama-based summarization."""

import json
import logging
import urllib.request
import urllib.error

from .config import OLLAMA_MODEL, OLLAMA_URL
from .templates import build_prompt

log = logging.getLogger("call-recorder")


class Summarizer:
    """Summarizes call transcripts using Ollama."""

    def summarize(
        self,
        transcript: str,
        template_name: str = "default",
        notes: str | None = None,
        segments: list[dict] | None = None,
    ) -> dict | None:
        """Generate summary from transcript using a template.

        Args:
            transcript: Call transcript text.
            template_name: Template to use for structuring the output.
            notes: Optional user notes to steer the summary.
            segments: Optional transcript segments with timestamps for citations.

        Returns:
            Parsed summary dict, or None if Ollama unavailable / input too short.
        """
        if not transcript or len(transcript.strip()) < 50:
            log.info("Transcript too short for summarization")
            return None

        # Truncate very long transcripts to fit model context
        max_chars = 12000
        text = transcript[:max_chars] if len(transcript) > max_chars else transcript

        prompt = build_prompt(template_name, text, notes, segments=segments)

        # More sections → more tokens needed
        num_predict = 2048 if template_name != "default" else 1024

        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": num_predict,
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            log.info(f"Calling Ollama ({OLLAMA_MODEL}), template={template_name}...")
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
