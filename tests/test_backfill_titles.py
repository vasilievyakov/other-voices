"""Tests for scripts.backfill_titles — title/deadline_date backfill for open rows.

The LLM is always injected as a stub here; the live Ollama path is exercised
only by running the script manually against the real database.
"""

from scripts.backfill_titles import (
    apply_updates,
    compute_deadline_date,
    main,
    plan_updates,
)


def _populate(db):
    """One call (Wed 2026-08-19), three commitments: 2 open, 1 done."""
    db.insert_call(
        session_id="s1",
        app_name="Zoom",
        started_at="2026-08-19T10:00:00",
        ended_at="2026-08-19T10:30:00",
        duration_seconds=1800.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript="т",
        summary=None,
    )
    db.insert_commitments(
        "s1",
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "прислать смету",
                "quote": "пришлю смету завтра",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "сделать отчет",
                "quote": "сделаю как получится",
            },
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "what": "закрытое",
                "quote": "сделаю в пятницу",
            },
        ],
    )
    db.update_commitment_status(3, "done")
    return db


class TestComputeDeadlineDate:
    def test_from_quote_when_raw_null(self, tmp_db):
        rows = _populate(tmp_db).get_open_commitments()
        row = next(r for r in rows if r["id"] == 1)
        assert compute_deadline_date(row) == "2026-08-20"

    def test_deadline_raw_wins_over_quote(self):
        row = {
            "started_at": "2026-08-19T10:00:00",
            "deadline_raw": "в пятницу",
            "verbatim_quote": "пришлю смету завтра",
            "text": "прислать смету",
        }
        assert compute_deadline_date(row) == "2026-08-21"

    def test_text_is_last_resort(self):
        row = {
            "started_at": "2026-08-19T10:00:00",
            "deadline_raw": None,
            "verbatim_quote": "ну я сделаю",
            "text": "сделать отчет к пятнице",
        }
        assert compute_deadline_date(row) == "2026-08-21"

    def test_none_when_no_computable_date(self, tmp_db):
        rows = _populate(tmp_db).get_open_commitments()
        row = next(r for r in rows if r["id"] == 2)
        assert compute_deadline_date(row) is None

    def test_none_when_started_at_broken(self):
        row = {"started_at": "", "verbatim_quote": "завтра", "text": ""}
        assert compute_deadline_date(row) is None


class TestPlanUpdates:
    def test_titles_come_from_title_fn_with_quote_and_deadline(self, tmp_db):
        rows = _populate(tmp_db).get_open_commitments()
        calls = []

        def stub(quote, deadline):
            calls.append((quote, deadline))
            return "заголовок"

        updates = {u["id"]: u for u in plan_updates(rows, title_fn=stub)}
        assert updates[1]["title"] == "заголовок"
        assert ("пришлю смету завтра", "") in calls

    def test_existing_title_kept_and_not_recomputed(self, tmp_db):
        db = _populate(tmp_db)
        with db._conn() as conn:
            conn.execute("UPDATE commitments SET title = 'готовый' WHERE id = 1")
        rows = db.get_open_commitments()
        calls = []

        def stub(quote, deadline):
            calls.append(quote)
            return "новый"

        updates = {u["id"]: u for u in plan_updates(rows, title_fn=stub)}
        assert updates[1]["title"] == "готовый"
        assert "пришлю смету завтра" not in calls

    def test_existing_deadline_date_kept(self, tmp_db):
        db = _populate(tmp_db)
        with db._conn() as conn:
            conn.execute(
                "UPDATE commitments SET deadline_date = '2026-09-01' WHERE id = 1"
            )
        rows = db.get_open_commitments()
        updates = {u["id"]: u for u in plan_updates(rows, title_fn=lambda q, d: None)}
        assert updates[1]["deadline_date"] == "2026-09-01"

    def test_deadline_date_computed_for_open_rows(self, tmp_db):
        rows = _populate(tmp_db).get_open_commitments()
        updates = {u["id"]: u for u in plan_updates(rows, title_fn=lambda q, d: None)}
        assert updates[1]["deadline_date"] == "2026-08-20"
        assert updates[2]["deadline_date"] is None


class TestApplyAndCli:
    def test_apply_writes_rows(self, tmp_db):
        db = _populate(tmp_db)
        apply_updates(
            db,
            [
                {
                    "id": 1,
                    "title": "прислать смету — завтра",
                    "deadline_date": "2026-08-20",
                }
            ],
        )
        row = db.get_commitments("s1")[0]
        assert row["title"] == "прислать смету — завтра"
        assert row["deadline_date"] == "2026-08-20"

    def test_main_dry_run_writes_nothing(self, tmp_db, capsys):
        db = _populate(tmp_db)
        main(["--db", str(db.db_path), "--dry-run"], title_fn=lambda q, d: "заголовок")
        out = capsys.readouterr().out
        assert "dry-run" in out
        rows = db.get_commitments("s1")
        assert all(r["title"] is None for r in rows)
        assert all(r["deadline_date"] is None for r in rows)

    def test_main_updates_only_open_rows(self, tmp_db):
        db = _populate(tmp_db)
        main(["--db", str(db.db_path)], title_fn=lambda q, d: "заголовок")
        rows = {r["id"]: r for r in db.get_commitments("s1")}
        assert rows[1]["title"] == "заголовок"
        assert rows[1]["deadline_date"] == "2026-08-20"
        assert rows[2]["title"] == "заголовок"
        assert rows[3]["title"] is None  # done row untouched
