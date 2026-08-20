"""Tests for scripts.mcp_server — read-only MCP access to the call ledger.

The server exposes reading only: search, call details, briefs, digest and
open commitments. No write tools by design — statuses change only by the
owner's hand in the app or CLI.
"""

import asyncio

from scripts.mcp_server import (
    TRANSCRIPT_CAP,
    get_call,
    make_server,
    morning_digest,
    open_commitments,
    person_brief,
    search_calls,
)
from tests.conftest import SID1


def _insert_commitment(db):
    db.insert_commitments(
        SID1,
        [
            {
                "direction": "outgoing",
                "committer_label": "SPEAKER_ME",
                "commitment_text": "отправлю договор",
                "verbatim_quote": "я пришлю договор в пятницу",
                "timestamp": "1:30",
            }
        ],
    )


class TestTools:
    def test_search_calls_finds_by_content(self, populated_db):
        rows = search_calls(populated_db, "Альфа")
        assert rows
        assert any(r["session_id"] == SID1 for r in rows)
        assert all("app_name" in r and "started_at" in r for r in rows)

    def test_search_calls_respects_limit(self, populated_db):
        rows = search_calls(populated_db, "обсудили", limit=1)
        assert len(rows) <= 1

    def test_get_call_returns_summary_and_transcript(self, populated_db):
        call = get_call(populated_db, SID1)
        assert call is not None
        assert call["session_id"] == SID1
        assert call["transcript"]
        assert isinstance(call.get("summary"), dict)

    def test_get_call_unknown_id(self, populated_db):
        assert get_call(populated_db, "нет-такого") is None

    def test_open_commitments_shape(self, populated_db):
        _insert_commitment(populated_db)
        rows = open_commitments(populated_db)
        assert rows
        row = rows[0]
        assert row["direction"] == "outgoing"
        assert row["verbatim_quote"]

    def test_open_commitments_direction_filter(self, populated_db):
        _insert_commitment(populated_db)
        assert open_commitments(populated_db, direction="incoming") == []

    def test_person_brief_renders(self, populated_db):
        _insert_commitment(populated_db)
        text = person_brief(populated_db, "SPEAKER_ME")
        assert isinstance(text, str) and text

    def test_morning_digest_renders(self, populated_db):
        text = morning_digest(populated_db)
        assert isinstance(text, str) and text


class TestContracts:
    """Evidence must survive the process boundary: every tool row carries its
    quote and flags, counters never absorb uncertain rows, truncation and
    snippet-only search are honest about what they withhold."""

    def _karpathy(
        self,
        db,
        what="прислать смету",
        quote="пришлю смету",
        uncertain=0,
        verified="exact",
        **extra,
    ):
        db.insert_commitments(
            SID1,
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "what": what,
                    "quote": quote,
                    "uncertain": uncertain,
                    "verified": verified,
                    **extra,
                }
            ],
        )

    # --- open_commitments ---

    def test_open_commitments_row_carries_evidence(self, populated_db):
        self._karpathy(
            populated_db,
            quote="пришлю смету в пятницу",
            verified="exact",
            title="прислать смету — пятница",
            deadline="пятница",
            deadline_date="2026-08-21",
        )
        rows = open_commitments(populated_db)
        assert len(rows) == 1
        row = rows[0]
        for key in (
            "verbatim_quote",
            "uncertain",
            "verified",
            "title",
            "deadline_date",
            "direction",
            "status",
        ):
            assert key in row, f"contract key missing: {key}"
        assert row["verbatim_quote"] == "пришлю смету в пятницу"
        assert row["uncertain"] == 0
        assert row["verified"] == "exact"
        assert row["title"] == "прислать смету — пятница"
        assert row["deadline_date"] == "2026-08-21"
        assert row["direction"] == "outgoing"
        assert row["status"] == "open"

    def test_open_commitments_legacy_row_verified_none(self, populated_db):
        """Rows inserted before the verified column exist honestly as NULL —
        re-extraction is forbidden, so None is the truthful value."""
        with populated_db._conn() as conn:
            conn.execute(
                """INSERT INTO commitments (session_id, direction, who_label, text)
                   VALUES (?, 'outgoing', 'SPEAKER_ME', 'легаси-обещание')""",
                (SID1,),
            )
        rows = open_commitments(populated_db)
        assert len(rows) == 1
        assert "verified" in rows[0]
        assert rows[0]["verified"] is None

    # --- person_brief ---

    def test_person_brief_counter_excludes_uncertain(self, populated_db):
        populated_db.insert_entities(SID1, [{"name": "Игорь", "type": "person"}])
        self._karpathy(populated_db, what="прислать смету", quote="пришлю смету")
        self._karpathy(
            populated_db,
            what="может быть прислать бюджет",
            quote="наверное пришлю бюджет",
            uncertain=1,
            verified="failed",
        )
        text = person_brief(populated_db, "Игорь")
        assert "должен: 1" in text  # uncertain row must not move the counter
        assert "нужно подтвердить: 1" in text
        # ...but the uncertain row is visible in its own section, with quote
        assert "Нужно подтвердить" in text
        assert "может быть прислать бюджет" in text
        assert "наверное пришлю бюджет" in text

    # --- morning_digest ---

    def test_morning_digest_counter_excludes_uncertain(self, populated_db):
        self._karpathy(
            populated_db,
            what="может быть прислать бюджет",
            quote="наверное пришлю бюджет",
            uncertain=1,
            verified="failed",
        )
        assert "0 ты должен" in morning_digest(populated_db)
        self._karpathy(populated_db, what="прислать смету", quote="пришлю смету")
        assert "1 ты должен" in morning_digest(populated_db)

    # --- get_call ---

    def test_get_call_truncation_is_honest(self, tmp_db):
        long_transcript = "сл " * (TRANSCRIPT_CAP // 3 + 100)
        assert len(long_transcript) > TRANSCRIPT_CAP
        tmp_db.insert_call(
            session_id="long1",
            app_name="Zoom",
            started_at="2026-08-19T10:00:00",
            ended_at="2026-08-19T11:00:00",
            duration_seconds=3600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript=long_transcript,
            summary=None,
        )
        call = get_call(tmp_db, "long1")
        assert call["transcript_truncated"] is True
        assert len(call["transcript"]) == TRANSCRIPT_CAP

    def test_get_call_short_transcript_not_flagged(self, populated_db):
        call = get_call(populated_db, SID1)
        assert call["transcript_truncated"] is False

    # --- search_calls ---

    def test_search_calls_returns_snippet_not_transcript(self, populated_db):
        rows = search_calls(populated_db, "Альфа")
        assert rows
        for r in rows:
            assert "snippet" in r
            assert "transcript" not in r  # full text never rides along silently
            assert "summary_json" not in r


class TestServer:
    def test_server_exposes_exactly_read_tools(self, populated_db):
        server = make_server(populated_db)
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert names == {
            "search_calls",
            "get_call",
            "person_brief",
            "morning_digest",
            "open_commitments",
        }

    def test_tool_descriptions_promise_no_writes(self, populated_db):
        """Eyes, not hands: no tool description may hint at changing state —
        an LLM consumer plans actions from descriptions alone."""
        forbidden = (
            "измен",
            "обнов",
            "закры",
            "удал",
            "помет",
            "постав",
            "update",
            "write",
            "delete",
            "modify",
            "mark",
            "create",
            "insert",
        )
        server = make_server(populated_db)
        tools = asyncio.run(server.list_tools())
        assert tools
        for t in tools:
            description = (t.description or "").lower()
            assert description.strip(), f"{t.name}: empty description"
            for word in forbidden:
                assert word not in description, (
                    f"{t.name}: description mentions writing ({word!r})"
                )
