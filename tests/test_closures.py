"""Tests for src.closures — closure-proposal detection (promise -> evidence).

Promise on call T1, evidence («я отправил») on a strictly later call T2 —
the pair is PROPOSED; status changes only by the owner's hand. The module
must never write to the database.
"""

import sqlite3

import src.closures as closures
from src.closures import build_closure_proposals, find_evidence

T0 = "2026-07-20T10:00:00"
T1 = "2026-08-01T10:00:00"
T2 = "2026-08-05T10:00:00"

PROMISE_QUOTE = "отправлю смету по проекту в пятницу"
EVIDENCE_QUOTE = "я отправил смету по проекту вчера"
EVIDENCE_LINE = f"[0:05] SPEAKER_ME: {EVIDENCE_QUOTE}"


def _call(db, sid, started, transcript):
    db.insert_call(
        session_id=sid,
        app_name="Zoom",
        started_at=started,
        ended_at=started,
        duration_seconds=600.0,
        system_wav_path=None,
        mic_wav_path=None,
        transcript=transcript,
        summary=None,
    )


def _promise(db, sid="t1", started=T1, quote=PROMISE_QUOTE):
    _call(db, sid, started, f"[0:10] SPEAKER_ME: {quote}")
    db.insert_commitments(
        sid,
        [
            {
                "type": "outgoing",
                "who": "SPEAKER_ME",
                "to_whom": "Максим",
                "what": "отправить смету по проекту",
                "quote": quote,
                "uncertain": 0,
            }
        ],
    )


class TestStage1Evidence:
    """Regex evidence candidates: real endings, not \\w-tails."""

    def test_first_person_perfective_past(self):
        cands = find_evidence("[0:05] SPEAKER_ME: я отправил смету")
        assert len(cands) == 1
        assert cands[0]["speaker"] == "SPEAKER_ME"
        assert "отправил смету" in cands[0]["quote"]

    def test_feminine_form(self):
        assert find_evidence("[0:05] SPEAKER_1: скинула презентацию утром")

    def test_reflexive_forms(self):
        assert find_evidence("[0:05] SPEAKER_ME: договорился с подрядчиком")
        assert find_evidence("[0:05] SPEAKER_1: созвонилась с ними вчера")

    def test_ya_uzhe_form(self):
        assert find_evidence("[0:05] SPEAKER_ME: я уже залил файлы на диск")

    def test_otpravleno_and_vse_gotovo(self):
        assert find_evidence("[0:05] SPEAKER_ME: отправлено")
        assert find_evidence("[0:05] SPEAKER_ME: все, по смете готово")

    def test_plural_and_third_person_are_not_evidence(self):
        assert find_evidence("[0:05] SPEAKER_ME: мы отправили отчет") == []
        assert find_evidence("[0:05] SPEAKER_ME: он отправил договор") == []
        assert find_evidence("[0:05] SPEAKER_ME: она сделала рассылку") == []

    def test_negated_past_is_not_evidence(self):
        """Live-base false positive: «Ничего он не сделал» proposed a closure."""
        assert find_evidence("[0:05] SPEAKER_ME: ничего он не сделал") == []
        assert find_evidence("[0:05] SPEAKER_ME: я не отправил еще") == []
        assert find_evidence("[0:05] SPEAKER_ME: я уже не успел никому") == []

    def test_future_is_not_evidence(self):
        assert find_evidence("[0:05] SPEAKER_ME: отправлю смету завтра") == []
        assert find_evidence("[0:05] SPEAKER_ME: скину презентацию") == []

    def test_unlabeled_line_keeps_none_speaker(self):
        cands = find_evidence("я отправил смету")
        assert len(cands) == 1
        assert cands[0]["speaker"] is None


class TestStage2Matching:
    def test_promise_then_evidence_pair(self, tmp_db):
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, EVIDENCE_LINE)
        pairs = build_closure_proposals(tmp_db)
        assert len(pairs) == 1
        p = pairs[0]
        cid = tmp_db.get_commitments("t1")[0]["id"]
        assert p["commitment_id"] == cid
        assert p["commitment_text"] == "отправить смету по проекту"
        assert p["commitment_quote"] == PROMISE_QUOTE
        assert p["evidence_session_id"] == "t2"
        assert p["evidence_quote"] == EVIDENCE_QUOTE
        assert p["evidence_date"] == "2026-08-05"

    def test_evidence_before_promise_no_pair(self, tmp_db):
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t0", T0, EVIDENCE_LINE)
        assert build_closure_proposals(tmp_db) == []

    def test_evidence_in_same_call_no_pair(self, tmp_db):
        _call(
            tmp_db,
            "t1",
            T1,
            f"[0:10] SPEAKER_ME: {PROMISE_QUOTE}\n{EVIDENCE_LINE}",
        )
        tmp_db.insert_commitments(
            "t1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "отправить смету по проекту",
                    "quote": PROMISE_QUOTE,
                    "uncertain": 0,
                }
            ],
        )
        assert build_closure_proposals(tmp_db) == []

    def test_foreign_evidence_no_pair(self, tmp_db):
        """Someone else's «я отправил» must not close my promise."""
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, f"[0:05] SPEAKER_1: {EVIDENCE_QUOTE}")
        assert build_closure_proposals(tmp_db) == []

    def test_unattributable_evidence_no_pair(self, tmp_db):
        """No speaker label — the owner cannot be established."""
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, EVIDENCE_QUOTE)
        assert build_closure_proposals(tmp_db) == []

    def test_weak_overlap_no_pair(self, tmp_db):
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, "[0:05] SPEAKER_ME: я отправил договор аренды и акт")
        assert build_closure_proposals(tmp_db) == []

    def test_closed_commitment_not_proposed(self, tmp_db):
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, EVIDENCE_LINE)
        cid = tmp_db.get_commitments("t1")[0]["id"]
        tmp_db.update_commitment_status(cid, "done")
        assert build_closure_proposals(tmp_db) == []

    def test_incoming_pair_needs_resolved_speaker_name(self, tmp_db):
        """Cross-call SPEAKER_N labels are not identities — only the
        owner-set rename links the evidence speaker to the promise owner."""
        _call(tmp_db, "t1", T1, "[0:10] SPEAKER_1: пришлю бриф по проекту завтра")
        tmp_db.insert_commitments(
            "t1",
            [
                {
                    "type": "incoming",
                    "who": "Максим",
                    "to_whom": "SPEAKER_ME",
                    "what": "прислать бриф по проекту",
                    "quote": "пришлю бриф по проекту завтра",
                    "uncertain": 0,
                }
            ],
        )
        _call(tmp_db, "t2", T2, "[0:05] SPEAKER_1: я прислал бриф по проекту")
        assert build_closure_proposals(tmp_db) == []
        tmp_db.set_speaker_name("t2", "SPEAKER_1", "Максим")
        pairs = build_closure_proposals(tmp_db)
        assert len(pairs) == 1
        assert pairs[0]["evidence_quote"] == "я прислал бриф по проекту"


class TestStage3Verification:
    def test_failed_evidence_quote_drops_pair(self, tmp_db, monkeypatch):
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, EVIDENCE_LINE)
        monkeypatch.setattr(closures, "verify_quote", lambda q, c: "failed")
        assert build_closure_proposals(tmp_db) == []

    def test_promise_without_quote_in_db_no_pair(self, tmp_db):
        _call(tmp_db, "t1", T1, f"[0:10] SPEAKER_ME: {PROMISE_QUOTE}")
        tmp_db.insert_commitments(
            "t1",
            [
                {
                    "type": "outgoing",
                    "who": "SPEAKER_ME",
                    "to_whom": None,
                    "what": "отправить смету по проекту",
                    "uncertain": 0,
                }
            ],
        )
        _call(tmp_db, "t2", T2, EVIDENCE_LINE)
        assert build_closure_proposals(tmp_db) == []


def _commitments_snapshot(db):
    with sqlite3.connect(str(db.db_path)) as conn:
        return conn.execute("SELECT * FROM commitments ORDER BY id").fetchall()


class TestReadOnly:
    def test_zero_writes_to_commitments(self, tmp_db):
        """The whole run must leave the commitments table byte-identical."""
        _promise(tmp_db, "t1", T1)
        _call(tmp_db, "t2", T2, EVIDENCE_LINE)
        before = _commitments_snapshot(tmp_db)
        pairs = build_closure_proposals(tmp_db)
        assert pairs  # the pair exists — and still nothing was written
        after = _commitments_snapshot(tmp_db)
        assert before == after
        assert [c["status"] for c in tmp_db.get_commitments("t1")] == ["open"]
