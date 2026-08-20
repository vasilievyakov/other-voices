"""Tests for scripts/stage1_sweep.py — stage-1 candidate sweep over calls.db."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.stage1_sweep import sweep, main  # noqa: E402
from src.database import Database  # noqa: E402


# A line that matches stage-1 CANDIDATE_PATTERNS (future commitment marker).
HIT = "[SPEAKER_ME 0:01] Я отправлю тебе документ завтра."
# A line with no commitment markers.
MISS = "[SPEAKER_00 0:02] Погода сегодня отличная."


def _make_db(tmp_path):
    return Database(db_path=tmp_path / "calls.db")


def _insert(db, session_id, transcript, duration=600.0, app_name="Zoom"):
    db.insert_call(
        session_id=session_id,
        app_name=app_name,
        started_at="2026-08-20T10:00:00",
        ended_at="2026-08-20T10:10:00",
        duration_seconds=duration,
        system_wav_path=None,
        mic_wav_path=None,
        transcript=transcript,
        summary=None,
    )


class TestSweep:
    def test_skips_calls_without_transcript(self, tmp_path):
        db = _make_db(tmp_path)
        _insert(db, "s-none", None)
        _insert(db, "s-empty", "   \n  ")
        _insert(db, "s-ok", HIT)
        report = sweep(db.db_path)
        ids = [s["session_id"] for s in report["sessions"]]
        assert ids == ["s-ok"]
        assert report["summary"]["total_sessions"] == 1

    def test_per_session_fields(self, tmp_path):
        db = _make_db(tmp_path)
        _insert(db, "s-1", f"{HIT}\n{MISS}", duration=120.0, app_name="Telegram")
        report = sweep(db.db_path)
        (s,) = report["sessions"]
        assert s["session_id"] == "s-1"
        assert s["app_name"] == "Telegram"
        assert s["duration_seconds"] == 120.0
        assert s["transcript_lines"] == 2
        assert s["candidates"] == 1
        assert s["candidates_per_minute"] == 0.5
        assert s["degenerate"] is False

    def test_degenerate_transcript_flagged(self, tmp_path):
        db = _make_db(tmp_path)
        loop = "\n".join("[0:%02d] Продолжение следует..." % i for i in range(20))
        _insert(db, "s-degen", loop)
        _insert(db, "s-live", HIT)
        report = sweep(db.db_path)
        by_id = {s["session_id"]: s for s in report["sessions"]}
        assert by_id["s-degen"]["degenerate"] is True
        assert by_id["s-live"]["degenerate"] is False
        assert report["summary"]["degenerate_sessions"] == 1

    def test_zero_candidate_sessions_listed_with_duration(self, tmp_path):
        db = _make_db(tmp_path)
        _insert(db, "s-zero", MISS, duration=333.0)
        _insert(db, "s-hit", HIT, duration=60.0)
        report = sweep(db.db_path)
        zeros = report["summary"]["zero_candidate_sessions"]
        assert len(zeros) == 1
        z = zeros[0]
        assert z["session_id"] == "s-zero"
        assert z["duration_seconds"] == 333.0
        assert z["degenerate"] is False

    def test_distribution_keys_and_values(self, tmp_path):
        db = _make_db(tmp_path)
        # 4 sessions, 1 candidate each, durations 60s..240s → cpm 1.0, 0.5, ...
        for i, dur in enumerate([60.0, 120.0, 180.0, 240.0]):
            _insert(db, f"s-{i}", HIT, duration=dur)
        dist = sweep(db.db_path)["summary"]["candidates_per_minute"]
        for key in ("min", "p10", "p25", "median", "p75", "p90", "max"):
            assert key in dist
        assert dist["min"] == 0.25
        assert dist["max"] == 1.0
        assert (
            dist["min"] <= dist["p25"] <= dist["median"] <= dist["p75"] <= dist["max"]
        )

    def test_zero_duration_does_not_crash(self, tmp_path):
        db = _make_db(tmp_path)
        _insert(db, "s-zerodur", HIT, duration=0.0)
        (s,) = sweep(db.db_path)["sessions"]
        assert s["candidates_per_minute"] == 0.0


class TestMain:
    def test_main_writes_json(self, tmp_path):
        db = _make_db(tmp_path)
        _insert(db, "s-1", HIT)
        out = tmp_path / "stage1-sweep.json"
        main(["--db", str(db.db_path), "--out", str(out)])
        data = json.loads(out.read_text())
        assert data["summary"]["total_sessions"] == 1
        assert data["sessions"][0]["session_id"] == "s-1"


class TestCanaryThreshold:
    def test_threshold_matches_sweep_calibration(self):
        """Pin the stage-1 canary threshold to the value derived from the
        2026-08-20 sweep of the full call history (eval/stage1-sweep.json).

        If you change EXTRACTION_CANARY_MIN_SECONDS, re-run
        scripts/stage1_sweep.py and re-derive the number from the
        zero-candidate non-degenerate sessions — do not tune it by hand.
        """
        import src.daemon as daemon_mod

        assert daemon_mod.EXTRACTION_CANARY_MIN_SECONDS == 2400, (
            "EXTRACTION_CANARY_MIN_SECONDS drifted from the data-derived "
            "calibration; see eval/stage1-sweep.json (sweep of 2026-08-20) "
            "before changing it"
        )
