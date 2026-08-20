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
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "древнее из воркшопа",
                    "quote": "сейчас открою",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "recent_burn",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "настоящий недавний долг",
                    "quote": "пришлю",
                    "uncertain": 0,
                }
            ],
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
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "горящий долг",
                    "quote": "сделаю",
                    "uncertain": 0,
                }
            ],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        header = md.splitlines()[0]
        assert "1 горит" in header
        assert "1 ты должен" in header  # горящий outgoing — всё ещё твой долг


class TestTitleLines:
    def test_followup_uses_title_over_text_and_keeps_quote(self, tmp_db):
        _call_with_summary(tmp_db, "s1")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "ну я это, смету пришлю, наверное",
                    "quote": "ну я это, смету пришлю",
                    "title": "прислать смету",
                    "uncertain": 0,
                }
            ],
        )
        _, md = build_followup(tmp_db, "s1")
        assert "- прислать смету" in md
        assert "ну я это, смету пришлю, наверное" not in md
        assert "> ну я это, смету пришлю" in md

    def test_followup_falls_back_to_text_without_title(self, tmp_db):
        _call_with_summary(tmp_db, "s1")
        tmp_db.insert_commitments(
            "s1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "прислать смету",
                    "quote": "пришлю смету",
                    "uncertain": 0,
                }
            ],
        )
        _, md = build_followup(tmp_db, "s1")
        assert "- прислать смету" in md

    def test_digest_uses_title_in_all_buckets(self, tmp_db):
        _call_with_summary(tmp_db, "burn", started="2026-08-10T10:00:00")
        _call_with_summary(tmp_db, "fresh", started="2026-08-19T10:00:00")
        tmp_db.insert_commitments(
            "burn",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "сырой текст горящего",
                    "quote": "сделаю",
                    "title": "заголовок горящего",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "fresh",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "сырой текст свежего",
                    "quote": "пришлю",
                    "title": "заголовок свежего",
                    "uncertain": 0,
                }
            ],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        assert "заголовок горящего" in md
        assert "сырой текст горящего" not in md
        assert "заголовок свежего" in md
        assert "сырой текст свежего" not in md


class TestBurningSort:
    def test_dated_first_earliest_on_top_then_by_age(self, tmp_db):
        # Four burning items (8-30 days old): two dated, two dateless.
        for sid, started in (
            ("b1", "2026-08-10T10:00:00"),
            ("b2", "2026-08-08T10:00:00"),
            ("b3", "2026-08-05T10:00:00"),
            ("b4", "2026-08-11T10:00:00"),
        ):
            _call_with_summary(tmp_db, sid, started=started)
        tmp_db.insert_commitments(
            "b1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "поздний срок",
                    "quote": "сделаю",
                    "deadline_date": "2026-08-25",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "b2",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "ранний срок",
                    "quote": "сделаю",
                    "deadline_date": "2026-08-21",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "b3",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "старое без срока",
                    "quote": "сделаю",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.insert_commitments(
            "b4",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "молодое без срока",
                    "quote": "сделаю",
                    "uncertain": 0,
                }
            ],
        )
        md = build_morning_digest(tmp_db, now=NOW)
        burning = md.split("## Горит")[1]
        order = [
            burning.index("ранний срок"),
            burning.index("поздний срок"),
            burning.index("старое без срока"),
            burning.index("молодое без срока"),
        ]
        assert order == sorted(order)


class TestSpeakerRename:
    """Owner-set speaker names must flow into delivery artifacts."""

    def _call_no_entities(self, db, sid="r1", started="2026-08-19T10:00:00"):
        db.insert_call(
            session_id=sid,
            app_name="Zoom",
            started_at=started,
            ended_at=started,
            duration_seconds=600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="разговор",
            summary={"summary": "Обсудили запуск пилота.", "decisions": []},
        )

    def test_followup_addresses_sobesednik_before_rename(self, tmp_db):
        self._call_no_entities(tmp_db)
        tmp_db.insert_commitments(
            "r1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "SPEAKER_1",
                    "what": "прислать смету",
                    "quote": "пришлю смету",
                    "uncertain": 0,
                }
            ],
        )
        slug, md = build_followup(tmp_db, "r1")
        assert slug == "собеседник"
        assert md.startswith("# Собеседник")

    def test_followup_addresses_renamed_speaker(self, tmp_db):
        self._call_no_entities(tmp_db)
        tmp_db.insert_commitments(
            "r1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "SPEAKER_1",
                    "what": "прислать смету",
                    "quote": "пришлю смету",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.set_speaker_name("r1", "SPEAKER_1", "Игорь")
        slug, md = build_followup(tmp_db, "r1")
        assert slug == "игорь"
        assert md.startswith("# Игорь")

    def test_followup_rename_beats_extracted_entity(self, tmp_db):
        """The owner's explicit rename outranks entity extraction."""
        self._call_no_entities(tmp_db)
        tmp_db.insert_entities("r1", [{"name": "Максим", "type": "person"}])
        tmp_db.insert_commitments(
            "r1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "SPEAKER_1",
                    "what": "прислать смету",
                    "quote": "пришлю смету",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.set_speaker_name("r1", "SPEAKER_1", "Игорь")
        slug, md = build_followup(tmp_db, "r1")
        assert slug == "игорь"
        assert md.startswith("# Игорь")

    def test_followup_ignores_speaker_me_mapping(self, tmp_db):
        """Naming yourself must not make the follow-up address you."""
        self._call_no_entities(tmp_db)
        tmp_db.insert_commitments(
            "r1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": "SPEAKER_1",
                    "what": "прислать смету",
                    "quote": "пришлю смету",
                    "uncertain": 0,
                }
            ],
        )
        tmp_db.set_speaker_name("r1", "SPEAKER_ME", "Яков")
        slug, md = build_followup(tmp_db, "r1")
        assert slug == "собеседник"
        assert md.startswith("# Собеседник")

    def test_morning_digest_shows_renamed_speaker(self, tmp_db):
        self._call_no_entities(tmp_db, started="2026-08-19T10:00:00")
        tmp_db.insert_commitments(
            "r1",
            [
                {
                    "type": "incoming",
                    "who": "SPEAKER_1",
                    "to_whom": "SPEAKER_ME",
                    "what": "прислать бриф",
                    "quote": "скину бриф",
                    "uncertain": 0,
                }
            ],
        )
        before = build_morning_digest(tmp_db, now=NOW)
        assert "SPEAKER_1" in before
        tmp_db.set_speaker_name("r1", "SPEAKER_1", "Игорь")
        after = build_morning_digest(tmp_db, now=NOW)
        assert "Игорь" in after
        assert "SPEAKER_1" not in after


class TestClosureProposalSection:
    """«Предлагаю закрыть (реши сам)» — the pair is shown, status untouched."""

    PROMISE = "отправлю смету по проекту в пятницу"
    EVIDENCE = "я отправил смету по проекту вчера"

    def _pair(self, db):
        db.insert_call(
            session_id="p1",
            app_name="Zoom",
            started_at="2026-08-15T10:00:00",
            ended_at="2026-08-15T10:30:00",
            duration_seconds=600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript=f"[0:10] SPEAKER_ME: {self.PROMISE}",
            summary=None,
        )
        db.insert_commitments(
            "p1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "отправить смету по проекту",
                    "quote": self.PROMISE,
                    "uncertain": 0,
                }
            ],
        )
        db.insert_call(
            session_id="p2",
            app_name="Zoom",
            started_at="2026-08-19T10:00:00",
            ended_at="2026-08-19T10:30:00",
            duration_seconds=600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript=f"[0:05] SPEAKER_ME: {self.EVIDENCE}",
            summary=None,
        )

    def test_section_lists_pair_with_both_quotes(self, tmp_db):
        self._pair(tmp_db)
        md = build_morning_digest(tmp_db, now=NOW)
        assert "## Предлагаю закрыть (реши сам)" in md
        section = md.split("## Предлагаю закрыть (реши сам)")[1]
        assert self.PROMISE in section
        assert self.EVIDENCE in section

    def test_digest_does_not_change_status(self, tmp_db):
        self._pair(tmp_db)
        build_morning_digest(tmp_db, now=NOW)
        assert [c["status"] for c in tmp_db.get_commitments("p1")] == ["open"]

    def test_no_pairs_no_section(self, tmp_db):
        _call_with_summary(tmp_db, "s1")
        md = build_morning_digest(tmp_db, now=NOW)
        assert "Предлагаю закрыть" not in md
