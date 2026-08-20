"""Tests for scripts.freeze_regression_set — owner-curated snapshot.

The snapshot freezes ALL commitment rows (open, dismissed, done) with the
owner's verdicts, in id order, with exactly the fields the regression check
needs. The database is opened read-only; output goes to a JSON file.
"""

import json

from scripts.freeze_regression_set import FIELDS, fetch_rows, freeze


def _populate(db):
    """Two calls, 4 commitments: ids 1-2 open, id 3 dismissed, id 4 done."""
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
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Возможно, созвонимся",
                "quote": "возможно, созвонимся",
                "uncertain": True,
            },
        ],
    )
    db.insert_commitments(
        "sess_two",
        [
            {
                "type": "incoming",
                "who": "SPEAKER_1",
                "what": "Пришлет доступы",
                "quote": "пришлю доступы",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "Отправлю запись",
                "quote": "отправлю запись",
            },
        ],
    )
    db.update_commitment_status(3, "dismissed", "2026-08-15T12:00:00")
    db.update_commitment_status(4, "done", "2026-08-16T09:00:00")
    return db


class TestFetchRows:
    def test_all_statuses_in_id_order(self, tmp_db):
        rows = fetch_rows(_populate(tmp_db).db_path)
        assert [r["id"] for r in rows] == [1, 2, 3, 4]
        assert [r["status"] for r in rows] == ["open", "open", "dismissed", "done"]

    def test_rows_carry_exactly_the_frozen_fields(self, tmp_db):
        rows = fetch_rows(_populate(tmp_db).db_path)
        for row in rows:
            assert set(row) == set(FIELDS)

    def test_field_values_survive_verbatim(self, tmp_db):
        rows = fetch_rows(_populate(tmp_db).db_path)
        by_id = {r["id"]: r for r in rows}
        assert by_id[1]["session_id"] == "sess_one"
        assert by_id[1]["verbatim_quote"] == "я пришлю смету до пятницы"
        assert by_id[1]["direction"] == "outgoing"
        assert by_id[1]["resolved_at"] is None
        assert by_id[2]["uncertain"] == 1
        assert by_id[3]["direction"] == "incoming"
        assert by_id[3]["resolved_at"] == "2026-08-15T12:00:00"


class TestFreeze:
    def test_writes_snapshot_json(self, tmp_db, tmp_path):
        db = _populate(tmp_db)
        out = tmp_path / "eval" / "regression-set.json"
        payload = freeze(db.db_path, out)
        assert out.exists()
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk == payload
        assert on_disk["count"] == 4
        assert len(on_disk["rows"]) == 4
        assert on_disk["frozen_at"]

    def test_database_content_is_untouched(self, tmp_db, tmp_path):
        db = _populate(tmp_db)
        before = fetch_rows(db.db_path)
        freeze(db.db_path, tmp_path / "regression-set.json")
        assert fetch_rows(db.db_path) == before
