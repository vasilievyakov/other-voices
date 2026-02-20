"""Call Recorder — Ollama-based summarization with chunked processing."""

import json
import logging
import re
import urllib.request
import urllib.error

from .chunking import chunk_transcript
from .config import OLLAMA_MODEL, OLLAMA_URL
from .templates import build_prompt

log = logging.getLogger("call-recorder")

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")

# Chunk size for long transcripts (~30 min of conversation)
CHUNK_MAX_CHARS = 25000
CHUNK_OVERLAP = 2000

# Merge prompt for combining chunk summaries into a final summary
_MERGE_PROMPT_RU = """\
Ты — движок объединения результатов. Ниже приведены {n} промежуточных JSON-резюме, \
полученных из последовательных частей одного длинного звонка.

Твоя задача — объединить их в ОДИН итоговый JSON со следующими правилами:
1. summary — общее резюме всего звонка (2-4 предложения), а не перечисление резюме чанков.
2. title — один заголовок, отражающий ВЕСЬ звонок.
3. Все списочные поля (key_points, decisions, action_items, participants и др.) — объедини, \
убери полные дубликаты. Сохраняй порядок: от начала звонка к концу.
4. participants — объедини из всех чанков, убери дубликаты.
5. entities — объедини из всех чанков, убери дубликаты.
6. Используй ТОЛЬКО поля из входных данных. НЕ добавляй новые.
7. Выводи ТОЛЬКО JSON. Начни с {{

ПРОМЕЖУТОЧНЫЕ РЕЗЮМЕ:
{summaries}"""

_MERGE_PROMPT_EN = """\
You are a result merging engine. Below are {n} intermediate JSON summaries \
from consecutive parts of the same long call.

Your task: merge them into ONE final JSON following these rules:
1. summary — overall summary of the entire call (2-4 sentences), not a list of chunk summaries.
2. title — one title reflecting the WHOLE call.
3. All list fields (key_points, decisions, action_items, participants, etc.) — merge and \
deduplicate. Preserve chronological order: start to end.
4. participants — merge from all chunks, deduplicate.
5. entities — merge from all chunks, deduplicate.
6. Use ONLY fields present in the inputs. Do NOT add new fields.
7. Output ONLY JSON. Start with {{

INTERMEDIATE SUMMARIES:
{summaries}"""


class Summarizer:
    """Summarizes call transcripts using Ollama with chunked processing."""

    @staticmethod
    def _try_repair_json(text: str) -> dict | None:
        """Attempt to repair truncated JSON from model output."""
        text = text.strip()
        if not text.startswith("{"):
            return None
        last_brace = text.rfind("}")
        if last_brace <= 0:
            return None
        candidate = text[: last_brace + 1]
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        candidate += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                result["_repaired"] = True
                return result
        except json.JSONDecodeError:
            pass
        return None

    def _call_ollama(self, prompt: str) -> str | None:
        """Send prompt to Ollama /api/chat and return content string."""
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
            with urllib.request.urlopen(req, timeout=600) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            log.warning(f"Ollama unavailable: {e}")
            return None

        message = result.get("message", {})
        response_text = message.get("content", "").strip()

        thinking = message.get("thinking", "")
        if thinking:
            log.info(f"Model thinking: {len(thinking)} chars")

        return response_text

    def _parse_response(self, response_text: str | None) -> dict | None:
        """Parse JSON from Ollama response, handling think blocks and markdown."""
        if not response_text:
            return None

        text = response_text

        # Strip thinking block if it leaked into content
        if "<think>" in text:
            think_match = re.search(r"<think>.*?</think>\s*", text, re.DOTALL)
            if think_match:
                text = text[think_match.end() :].strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```"))

        try:
            summary = json.loads(text)
        except json.JSONDecodeError:
            summary = self._try_repair_json(text)

        if isinstance(summary, dict):
            return summary
        return None

    def _summarize_single(
        self,
        text: str,
        template_name: str,
        notes: str | None,
        segments: list[dict] | None,
    ) -> dict | None:
        """Summarize a single chunk of transcript."""
        prompt = build_prompt(template_name, text, notes, segments=segments)
        log.info(
            f"Calling Ollama ({OLLAMA_MODEL}), template={template_name}, "
            f"chars={len(text)}..."
        )
        raw = self._call_ollama(prompt)
        result = self._parse_response(raw)

        if result is None and raw:
            log.warning(f"Failed to parse Ollama response as JSON: {raw[:200]}")
            return {
                "summary": raw,
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "participants": [],
            }
        return result

    def _merge_summaries(self, chunk_summaries: list[dict], lang: str) -> dict | None:
        """Merge multiple chunk summaries into one final summary (reduce step)."""
        summaries_text = "\n\n".join(
            f"--- Chunk {i + 1} of {len(chunk_summaries)} ---\n"
            + json.dumps(s, ensure_ascii=False, indent=2)
            for i, s in enumerate(chunk_summaries)
        )

        if lang == "ru":
            prompt = _MERGE_PROMPT_RU.format(
                n=len(chunk_summaries), summaries=summaries_text
            )
        else:
            prompt = _MERGE_PROMPT_EN.format(
                n=len(chunk_summaries), summaries=summaries_text
            )

        log.info(f"Merging {len(chunk_summaries)} chunk summaries via Ollama...")
        raw = self._call_ollama(prompt)
        result = self._parse_response(raw)

        if result is None:
            # Fallback: mechanical merge without LLM
            log.warning("LLM merge failed, falling back to mechanical merge")
            return self._mechanical_merge(chunk_summaries)

        return result

    @staticmethod
    def _mechanical_merge(chunk_summaries: list[dict]) -> dict:
        """Merge summaries without LLM as a last resort."""
        merged: dict = {}
        seen_lists: dict[str, set] = {}

        for cs in chunk_summaries:
            for key, value in cs.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, str):
                    if key not in merged or not merged[key]:
                        merged[key] = value
                    elif key == "summary":
                        merged[key] += " " + value
                elif isinstance(value, list):
                    if key not in merged:
                        merged[key] = []
                        seen_lists[key] = set()
                    for item in value:
                        item_key = (
                            json.dumps(item, ensure_ascii=False, sort_keys=True)
                            if isinstance(item, dict)
                            else str(item)
                        )
                        if item_key not in seen_lists[key]:
                            seen_lists[key].add(item_key)
                            merged[key].append(item)

        return merged

    def summarize(
        self,
        transcript: str,
        template_name: str = "default",
        notes: str | None = None,
        segments: list[dict] | None = None,
    ) -> dict | None:
        """Generate summary from transcript using a template.

        For long transcripts (>25K chars), splits into chunks, summarizes
        each independently, then merges results via a reduce pass.

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

        chunks = chunk_transcript(transcript, CHUNK_MAX_CHARS, CHUNK_OVERLAP)

        if len(chunks) == 1:
            # Short call — single pass (most common case)
            summary = self._summarize_single(transcript, template_name, notes, segments)
            if summary is not None:
                log.info("Summary generated successfully")
            return summary

        # Long call — chunked map-reduce
        log.info(
            f"Long transcript ({len(transcript)} chars), "
            f"splitting into {len(chunks)} chunks"
        )

        # Detect language from first chunk for merge prompt
        lang = (
            "ru" if any("\u0400" <= c <= "\u04ff" for c in transcript[:200]) else "en"
        )

        # Map: summarize each chunk
        chunk_summaries: list[dict] = []
        for i, chunk in enumerate(chunks):
            log.info(f"Summarizing chunk {i + 1}/{len(chunks)}...")
            # Only pass notes to the first chunk
            chunk_notes = notes if i == 0 else None
            result = self._summarize_single(
                chunk, template_name, chunk_notes, segments=None
            )
            if result is not None:
                chunk_summaries.append(result)
            else:
                log.warning(f"Chunk {i + 1} summarization returned None")

        if not chunk_summaries:
            log.warning("All chunk summarizations failed")
            return None

        if len(chunk_summaries) == 1:
            # Only one chunk succeeded — use it as-is
            log.info("Only one chunk succeeded, using it directly")
            return chunk_summaries[0]

        # Reduce: merge chunk summaries into one
        merged = self._merge_summaries(chunk_summaries, lang)
        if merged is not None:
            merged["_chunks"] = len(chunks)
            log.info(f"Summary generated successfully ({len(chunks)} chunks merged)")
        return merged
