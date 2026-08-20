"""Tests for scripts.audit_commitments — blind precision audit kit.

Export must be blind (no direction / uncertain / session_id in the visible
part), deterministically shuffled (seed 42), and round-trippable: the scorer
reads verdicts back by row id hidden in HTML comments.
"""

import re

from scripts.audit_commitments import (
    build_audit_md,
    fetch_commitments,
    parse_verdicts,
    score_verdicts,
)


def _visible(md: str) -> str:
    return re.sub(r"<!--.*?-->", "", md, flags=re.S)


def _populate(db):
    """Two calls, 6 commitments: ids 1-4 open, id 5 dismissed, id 6 done."""
    for sid, started in (
        ("sess_one", "2026-08-10T10:00:00"),
        ("sess_two", "2026-08-11T09:00:00"),
    ):
        db.insert_call(
            session_id=sid,
            app_name="Zoom",
            started_at=started,
            ended_at=started,
            duration_seconds=600.0,
            system_wav_path=None,
            mic_wav_path=None,
            transcript="т",
            summary=None,
        )
    db.insert_commitments(
        "sess_one",
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Пришлю смету до пятницы",
                "quote": "я пришлю смету до пятницы",
            },
            {
                "type": "incoming",
                "who": "SPEAKER_1",
                "what": "Петя подготовит договор",
                "quote": "я подготовлю договор",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Возможно, созвонимся в четверг",
                "quote": "возможно, созвонимся",
                "uncertain": True,
            },
        ],
    )
    db.insert_commitments(
        "sess_two",
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Отправлю запись звонка",
                "quote": "отправлю запись",
            },
            {
                "type": "incoming",
                "who": "SPEAKER_1",
                "what": "Пришлет доступы к серверу",
                "quote": "пришлю доступы",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Соберу оценку по срокам",
                "quote": "соберу оценку",
            },
        ],
    )
    db.update_commitment_status(5, "dismissed")
    db.update_commitment_status(6, "done", "2026-08-12T00:00:00")
    return db


class TestFetchCommitments:
    def test_returns_only_open_rows_by_default(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path)
        assert sorted(r["id"] for r in rows) == [1, 2, 3, 4]

    def test_all_adds_dismissed_but_never_done(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path, include_dismissed=True)
        by_id = {r["id"]: r for r in rows}
        assert sorted(by_id) == [1, 2, 3, 4, 5]
        assert by_id[5]["status"] == "dismissed"
        assert by_id[1]["status"] == "open"

    def test_rows_carry_scoring_fields(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path)
        by_id = {r["id"]: r for r in rows}
        assert by_id[1]["session_id"] == "sess_one"
        assert by_id[1]["started_at"] == "2026-08-10T10:00:00"
        assert by_id[1]["verbatim_quote"] == "я пришлю смету до пятницы"
        assert by_id[3]["uncertain"] == 1
        assert by_id[4]["uncertain"] == 0


class TestBuildAuditMd:
    def test_numbering_is_sequential(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        assert re.findall(r"^## (\d+)", md, flags=re.M) == ["1", "2", "3", "4"]

    def test_shuffle_is_deterministic_and_not_id_order(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path)
        md = build_audit_md(rows)
        ids = [int(i) for i in re.findall(r"<!-- id:(\d+)", md)]
        assert sorted(ids) == [1, 2, 3, 4]
        assert ids != sorted(ids)
        assert build_audit_md(rows) == md

    def test_visible_part_is_blind(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        visible = _visible(md)
        for leak in ("outgoing", "incoming", "uncertain", "sess_one", "sess_two"):
            assert leak not in visible

    def test_comments_carry_id_session_and_status(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        assert re.search(r"<!-- id:1 session:sess_one status:open -->", md)
        assert re.search(r"<!-- id:4 session:sess_two status:open -->", md)

    def test_all_export_hides_status_from_visible_part(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path, include_dismissed=True)
        md = build_audit_md(rows)
        assert re.search(r"<!-- id:5 session:sess_two status:dismissed -->", md)
        assert "dismissed" not in _visible(md)
        assert md.count("Вердикт: _") == 5

    def test_block_format(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        assert "Цитата: «я пришлю смету до пятницы»" in md
        assert "Текст: Пришлю смету до пятницы" in md
        assert "Дата звонка: 2026-08-10" in md
        assert md.count("Вердикт: _") == 4

    def test_footer_instructions(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        assert "+ реальное обязательство" in md
        assert "- мусор" in md


class TestParseVerdicts:
    MD = (
        "## 1 <!-- id:10 session:s -->\n"
        "Цитата: «а»\nТекст: а\nДата звонка: 2026-01-01\nВердикт: +\n\n"
        "## 2 <!-- id:11 session:s -->\n"
        "Цитата: «б»\nТекст: б\nДата звонка: 2026-01-01\nВердикт: -\n\n"
        "## 3 <!-- id:12 session:s -->\n"
        "Цитата: «в»\nТекст: в\nДата звонка: 2026-01-01\nВердикт: _\n\n"
        "## 4 <!-- id:13 session:s -->\n"
        "Цитата: «г»\nТекст: г\nДата звонка: 2026-01-01\nВердикт: - дубль\n"
    )

    def test_parses_marks_and_leaves_unmarked_empty(self):
        assert parse_verdicts(self.MD) == {10: "+", 11: "-", 12: "", 13: "-"}

    def test_fresh_export_is_fully_unmarked(self, tmp_db):
        md = build_audit_md(fetch_commitments(_populate(tmp_db).db_path))
        verdicts = parse_verdicts(md)
        assert sorted(verdicts) == [1, 2, 3, 4]
        assert all(v == "" for v in verdicts.values())


class TestScoreVerdicts:
    def test_precision_split_and_unmarked(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path)
        result = score_verdicts({1: "+", 2: "-", 3: "+", 4: ""}, rows)
        assert result["marked"] == 3
        assert result["unmarked"] == 1
        assert result["precision"] == round(2 / 3, 3)
        assert result["confident_marked"] == 2
        assert result["confident_precision"] == 0.5
        assert result["uncertain_marked"] == 1
        assert result["uncertain_precision"] == 1.0

    def test_open_subset_reported_alongside_full_precision(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path, include_dismissed=True)
        result = score_verdicts({1: "+", 2: "-", 3: "+", 4: "", 5: "-"}, rows)
        assert result["marked"] == 4
        assert result["unmarked"] == 1
        assert result["precision"] == 0.5
        assert result["open_marked"] == 3
        assert result["open_precision"] == round(2 / 3, 3)

    def test_no_marks_yields_none_precision(self, tmp_db):
        rows = fetch_commitments(_populate(tmp_db).db_path)
        result = score_verdicts({1: "", 2: "", 3: "", 4: ""}, rows)
        assert result["marked"] == 0
        assert result["unmarked"] == 4
        assert result["precision"] is None
        assert result["uncertain_precision"] is None
