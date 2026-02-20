"""Call Recorder — chat engine for asking questions about calls."""

import json
import logging
import urllib.request
import urllib.error

from .config import OLLAMA_MODEL, OLLAMA_URL
from .database import Database

log = logging.getLogger("call-recorder")

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")


class ChatEngine:
    """Ask questions about a specific call or across all calls."""

    def __init__(self, db: Database | None = None):
        self.db = db or Database()

    def _build_context(self, session_id: str | None = None, query: str = "") -> str:
        """Build context string from call data."""
        if session_id:
            call = self.db.get_call(session_id)
            if not call:
                return "No call found with this session ID."
            parts = [f"App: {call['app_name']}", f"Date: {call['started_at']}"]
            if call.get("transcript"):
                parts.append(f"Transcript:\n{call['transcript'][:8000]}")
            if call.get("summary_json"):
                parts.append(f"Summary:\n{call['summary_json']}")
            if call.get("notes"):
                parts.append(f"User notes:\n{call['notes']}")
            return "\n\n".join(parts)
        else:
            # Global: search for relevant calls
            # Sanitize query for FTS5 (remove special chars)
            safe_query = "".join(c for c in query if c.isalnum() or c.isspace())
            results = (
                self.db.search(safe_query.strip(), limit=5)
                if safe_query.strip()
                else []
            )
            if not results:
                return "No relevant calls found."
            parts = []
            for r in results:
                part = f"[{r['session_id']}] {r['app_name']} — {r['started_at']}"
                if r.get("transcript"):
                    part += f"\nTranscript: {r['transcript'][:2000]}"
                if r.get("summary_json"):
                    part += f"\nSummary: {r['summary_json'][:1000]}"
                parts.append(part)
            return "\n\n---\n\n".join(parts)

    def _get_history(
        self, session_id: str | None, scope: str, limit: int = 10
    ) -> list[dict]:
        """Load recent chat history."""
        messages = self.db.get_chat_messages(session_id, scope, limit)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def ask(
        self,
        question: str,
        session_id: str | None = None,
    ) -> str | None:
        """Ask a question about a call (or globally).

        Returns the assistant's response text, or None on failure.
        """
        scope = "call" if session_id else "global"
        context = self._build_context(session_id, question)
        history = self._get_history(session_id, scope)

        is_global = session_id is None
        system_msg = (
            "You are a call recording analyst. Rules:\n"
            "1. Answer ONLY from the provided call data. Never use outside knowledge.\n"
            "2. If the answer is not in the transcript or summary, say: "
            "'This was not discussed in the call.' Do NOT guess or infer.\n"
            "3. Cite specific timestamps [M:SS] when referencing transcript moments.\n"
            "4. Be direct. No preamble. Start your answer immediately.\n"
            "5. Respond in the same language as the question."
        )
        if is_global:
            system_msg += (
                "\n6. When answering about multiple calls, name which call "
                "each fact comes from (use the date and app as identifier)."
            )

        messages = [
            {"role": "system", "content": f"{system_msg}\n\nCall data:\n{context}"}
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": question})

        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024, "num_ctx": 32768},
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
            log.warning(f"Ollama chat unavailable: {e}")
            return None

        answer = result.get("message", {}).get("content", "").strip()
        if not answer:
            return None

        # Save both messages to history
        self.db.insert_chat_message(session_id, "user", question, scope)
        self.db.insert_chat_message(session_id, "assistant", answer, scope)

        return answer
