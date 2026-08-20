"""Lifecycle stamps: closing a commitment must record when it was closed."""

from tests.conftest import SID1


def _insert_one(db):
    db.insert_commitments(
        SID1,
        [
            {
                "direction": "outgoing",
                "committer_label": "я",
                "commitment_text": "отправлю документ",
                "verbatim_quote": "я отправлю документ завтра",
                "timestamp": "12:01",
            }
        ],
    )
    return db.get_commitments(SID1)[0]["id"]


class TestResolvedAtStamping:
    def test_dismiss_without_explicit_time_stamps_resolved_at(self, populated_db):
        cid = _insert_one(populated_db)
        populated_db.update_commitment_status(cid, "dismissed")
        row = populated_db.get_commitments(SID1)[0]
        assert row["status"] == "dismissed"
        assert row["resolved_at"], "closing must stamp resolved_at"

    def test_done_without_explicit_time_stamps_resolved_at(self, populated_db):
        cid = _insert_one(populated_db)
        populated_db.update_commitment_status(cid, "done")
        row = populated_db.get_commitments(SID1)[0]
        assert row["resolved_at"]

    def test_explicit_time_wins(self, populated_db):
        cid = _insert_one(populated_db)
        populated_db.update_commitment_status(cid, "done", "2026-08-12T00:00:00")
        row = populated_db.get_commitments(SID1)[0]
        assert row["resolved_at"] == "2026-08-12T00:00:00"

    def test_reopen_clears_resolved_at(self, populated_db):
        cid = _insert_one(populated_db)
        populated_db.update_commitment_status(cid, "dismissed")
        populated_db.update_commitment_status(cid, "open")
        row = populated_db.get_commitments(SID1)[0]
        assert row["status"] == "open"
        assert not row["resolved_at"]
