"""Tests for src.digests — post-call followup drafts and morning digest."""

import json
from datetime import datetime

from src.digests import build_followup, build_morning_digest


def _call_with_summary(db, sid, started="2026-08-19T10:00:00", summary=None):
    db.insert_call(
        session_id=sid,
        app_name="Zoom",
        started_at=started,
        ended_at=started,
        duration_seconds=600.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript="разговор",
        summary=summary
        or {
            "summary": "Обсудили запуск пилота и сроки.",
            "decisions": ["[5:00] решили запускать пилот в сентябре"],
        },
    )
    db.insert_entities(sid, [{"name": "Максим", "type": "person"}])


NOW = datetime(2026, 8, 20, 8, 0, 0)


class TestFollowup:
    def test_structure_and_tone(self, tmp_db):
        _call_with_summary(tmp_db, "s1")
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
                    "uncertain": 0,
                },
                {
                    "type": "incoming",
                    "who": "Максим",
                    "to_whom": None,
                    "what": "прислать бриф",
                    "quote": "скину бриф",
                    "uncertain": 0,
                },
            ],
        )
        result = build_followup(tmp_db, "s1")
        assert result is not None
        slug, md = result
        assert slug == "максим"
        assert "## Договорились" in md
        assert "решили запускать пилот" in md
        assert "[5:00]" not in md
        assert "## Беру на себя" in md
        assert "прислать смету" in md and "пятниц" in md
        assert "## От тебя жду" in md
        assert "сверь перед отправкой" in md

    def test_uncertain_commitments_not_in_followup(self, tmp_db):
        _call_with_summary(tmp_db, "s1")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "сомнительное",
                    "quote": "мм",
                    "uncertain": 1,
                }
            ],
        )
        result = build_followup(tmp_db, "s1")
        # decisions есть — черновик создаётся, но сомнительное в него не входит
        assert result is not None
        _, md = result
        assert "сомнительное" not in md

    def test_no_content_no_draft(self, tmp_db):
        _call_with_summary(
            tmp_db, "s1", summary={"summary": "Пустой звонок.", "decisions": []}
        )
        assert build_followup(tmp_db, "s1") is None


class TestMorningDigest:
    def test_score_header_and_buckets(self, tmp_db):
        _call_with_summary(tmp_db, "old", started="2026-08-01T10:00:00")
        _call_with_summary(tmp_db, "new", started="2026-08-19T10:00:00")
        tmp_db.insert_commitments(
            "old",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "старый долг",
                    "quote": "сделаю",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "new",
            [
                {
                    "type": "incoming",
                    "who": "Максим",
                    "to_whom": None,
                    "what": "свежее обещание",
                    "quote": "скину",
                    "uncertain": 0,
                }
            ],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        header = md.splitlines()[0]
        assert "1 горит" in header
        assert "## Горит" in md and "старый долг" in md
        assert "## Тебе должны" in md and "свежее обещание" in md

    def test_empty_digest_is_honest(self, tmp_db):
        md = build_morning_digest(tmp_db, now=NOW)
        assert "не значит" in md


class TestArchiveBucket:
    def test_stale_items_collapse_into_archive_count(self, tmp_db):
        _call_with_summary(tmp_db, "ancient", started="2026-06-01T10:00:00")
        _call_with_summary(tmp_db, "recent_burn", started="2026-08-10T10:00:00")
        tmp_db.insert_commitments(
            "ancient",
            [{"type": "outgoing", "who": "SPEAKER_ME", "to_whom": None,
              "what": "древнее из воркшопа", "quote": "сейчас открою", "uncertain": 0}],
        )
        tmp_db.insert_commitments(
            "recent_burn",
            [{"type": "outgoing", "who": "SPEAKER_ME", "to_whom": None,
              "what": "настоящий недавний долг", "quote": "пришлю", "uncertain": 0}],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        assert "1 горит" in md.splitlines()[0]
        assert "настоящий недавний долг" in md
        assert "древнее из воркшопа" not in md
        assert "Архив" in md and "1" in md.split("Архив")[1][:40]


class TestHeaderMatchesBody:
    def test_burning_outgoing_counted_in_debt_total(self, tmp_db):
        _call_with_summary(tmp_db, "old", started="2026-08-10T10:00:00")
        tmp_db.insert_commitments(
            "old",
            [{"type": "outgoing", "who": "SPEAKER_ME", "to_whom": None,
              "what": "горящий долг", "quote": "сделаю", "uncertain": 0}],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        header = md.splitlines()[0]
        assert "1 горит" in header
        assert "1 ты должен" in header  # горящий outgoing — всё ещё твой долг
