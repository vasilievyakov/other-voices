"""Tests for src.evaluation — pipeline quality metrics (pure functions)."""

from src.evaluation import (
    coverage_correct,
    hallucinated_participants,
    owner_attestation,
    summary_shape,
)


class TestOwnerAttestation:
    def test_counts_attested_and_total(self):
        summary = {
            "action_items": [
                "@Максим: отчёт",  # participant → attested
                "@Ghost: призрак",  # nowhere → not attested
                "без владельца",  # no owner → not counted
            ],
            "participants": ["Максим"],
        }
        result = owner_attestation(summary, "обсуждение")
        assert result == {"with_owner": 2, "attested": 1}

    def test_empty_items(self):
        assert owner_attestation({"action_items": []}, "t") == {
            "with_owner": 0,
            "attested": 0,
        }


class TestHallucinatedParticipants:
    def test_participant_absent_from_transcript_flagged(self):
        summary = {"participants": ["Анна", "Призрак"]}
        transcript = "Анна сказала, что перезвонит"
        assert hallucinated_participants(summary, transcript) == ["Призрак"]

    def test_inflected_name_not_flagged(self):
        """«Максиму» — case-inflected forms of a name count as present."""
        summary = {"participants": ["Максим"]}
        transcript = "передайте Максиму документы"
        assert hallucinated_participants(summary, transcript) == []

    def test_speaker_labels_ignored(self):
        summary = {"participants": ["SPEAKER_1", "SPEAKER_ME"]}
        assert hallucinated_participants(summary, "разговор без имён") == []


class TestCoverageCorrect:
    def test_matching_coverage(self):
        transcript = "[SPEAKER_ME]: привет\n[SPEAKER_1]: привет"
        summary = {"coverage": "full"}
        assert coverage_correct(summary, transcript) is True

    def test_mismatched_coverage(self):
        transcript = "[SPEAKER_ME]: говорю сам с собой"
        summary = {"coverage": "full"}
        assert coverage_correct(summary, transcript) is False


class TestSummaryShape:
    def test_shape_counts(self):
        summary = {
            "summary": "текст",
            "key_points": ["a", "b"],
            "decisions": [],
            "action_items": ["x"],
            "_repaired": True,
        }
        shape = summary_shape(summary)
        assert shape["summary_chars"] == 5
        assert shape["key_points"] == 2
        assert shape["decisions"] == 0
        assert shape["action_items"] == 1
        assert shape["repaired"] is True

    def test_none_summary(self):
        shape = summary_shape(None)
        assert shape["failed"] is True
