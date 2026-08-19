"""Tests for src.brief — per-person briefing (the combine's first artifact)."""

from datetime import datetime

from src.brief import build_brief, render_brief


def _call(db, sid, started, transcript="Максим обсуждал смету"):
    db.insert_call(
        session_id=sid,
        app_name="Zoom",
        started_at=started,
        ended_at=started,
        duration_seconds=600.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript=transcript,
        summary={
            "summary": "Обсудили смету и сроки.",
            "decisions": ["[1:00] решили делать пилот"],
        },
    )
    db.insert_entities(sid, [{"name": "Максим", "type": "person"}])


NOW = datetime(2026, 8, 19, 12, 0, 0)


class TestBuildBrief:
    def test_unknown_person_returns_none(self, tmp_db):
        assert build_brief(tmp_db, "Никто", now=NOW) is None

    def test_debt_first_structure(self, tmp_db):
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "Максим",
                    "what": "прислать смету",
                    "deadline": "пятница",
                    "quote": "пришлю смету в пятницу",
                },
                {
                    "type": "incoming",
                    "who": "Максим",
                    "to_whom": None,
                    "what": "прислать бриф",
                    "deadline": None,
                    "quote": "скину бриф",
                },
            ],
        )
        brief = build_brief(tmp_db, "Максим", now=NOW)
        assert brief["name"] == "Максим"
        assert brief["days_since_contact"] == 3
        assert len(brief["outgoing"]) == 1
        assert brief["outgoing"][0]["what"] == "прислать смету"
        assert brief["outgoing"][0]["deadline"] == "пятница"
        assert len(brief["incoming"]) == 1
        assert brief["recent"][0]["summary"] == "Обсудили смету и сроки."

    def test_incoming_requires_committer_match(self, tmp_db):
        """A stranger's incoming commitment must not be attributed to Максим."""
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "incoming",
                    "who": "Вася",
                    "to_whom": None,
                    "what": "чужое обещание",
                    "quote": "сделаю",
                }
            ],
        )
        brief = build_brief(tmp_db, "Максим", now=NOW)
        assert brief["incoming"] == []

    def test_person_without_commitments_empty_lists(self, tmp_db):
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        brief = build_brief(tmp_db, "Максим", now=NOW)
        assert brief["outgoing"] == []
        assert brief["incoming"] == []


class TestRenderBrief:
    def test_header_is_debt_first_and_human(self, tmp_db):
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "Максим",
                    "what": "прислать смету",
                    "deadline": "пятница",
                    "quote": "пришлю смету в пятницу",
                }
            ],
        )
        md = render_brief(build_brief(tmp_db, "Максим", now=NOW))
        first_line = md.splitlines()[0]
        assert "должен: 1" in first_line
        assert "3 дня назад" in first_line or "3 дн" in first_line
        # human language, no raw field names or timestamps
        assert "outgoing" not in md
        assert "direction" not in md
        assert "[1:00]" not in md


class TestBriefHonesty:
    def test_uncertain_never_in_debt_counter(self, tmp_db):
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        tmp_db.insert_commitments(
            "s1",
            [
                {"type": "outgoing", "who": "SPEAKER_ME", "to_whom": "Максим",
                 "what": "уверенное", "quote": "сделаю", "uncertain": 0},
                {"type": "outgoing", "who": "SPEAKER_ME", "to_whom": "Максим",
                 "what": "сомнительное", "quote": "может сделаю", "uncertain": 1},
            ],
        )
        brief = build_brief(tmp_db, "Максим", now=NOW)
        assert len(brief["outgoing"]) == 1
        assert len(brief["unconfirmed"]) == 1
        md = render_brief(brief)
        assert "должен: 1" in md.splitlines()[0]
        assert "нужно подтвердить: 1" in md

    def test_empty_is_honest_not_confident(self, tmp_db):
        _call(tmp_db, "s1", "2026-08-16T10:00:00")
        md = render_brief(build_brief(tmp_db, "Максим", now=NOW))
        assert "не значит" in md  # «не найдено — не значит, что не было»
