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


# =============================================================================
# Cycle 3: mechanical citation grounding (full transcript, no LLM)
# =============================================================================

from src.evaluation import citation_check

TRANSCRIPT = """[0:30] SPEAKER_ME: обсуждаем бюджет проекта на квартал
[1:00] SPEAKER_1: предлагаю собрать данные с сайта про финансовую отчётность
[1:30] SPEAKER_ME: хорошо, я пришлю договор в пятницу
[34:50] SPEAKER_ME: у субагентов отдельное контекстное окно и выбор модели
[35:20] SPEAKER_1: согласен"""


class TestCitationCheck:
    def test_verbatim_mid_call_claim_grounded(self):
        summary = {
            "key_points": ["[34:50] у субагентов отдельное контекстное окно"],
        }
        r = citation_check(summary, TRANSCRIPT)
        assert r == {"checked": 1, "grounded": 1, "weak": 0, "timestamp_missing": 0}

    def test_paraphrase_with_low_overlap_is_weak(self):
        summary = {"key_points": ["[1:00] решили заняться аналитикой рынка недвижимости"]}
        r = citation_check(summary, TRANSCRIPT)
        assert r["weak"] == 1
        assert r["grounded"] == 0

    def test_nonexistent_timestamp_counted_missing(self):
        summary = {"decisions": ["[150:00] решение из будущего"]}
        r = citation_check(summary, TRANSCRIPT)
        assert r["timestamp_missing"] == 1

    def test_commitment_quote_checked_against_full_transcript(self):
        summary = {
            "commitments": [
                {"who": "SPEAKER_ME", "what": "прислать договор",
                 "quote": "я пришлю договор в пятницу"}
            ]
        }
        r = citation_check(summary, TRANSCRIPT)
        assert r["checked"] == 1
        assert r["grounded"] == 1

    def test_untimestamped_items_not_counted(self):
        summary = {"key_points": ["пункт без метки"]}
        r = citation_check(summary, TRANSCRIPT)
        assert r["checked"] == 0


class TestLabeledRecall:
    from src.evaluation import labeled_recall  # noqa: PLC0415

    def test_promise_found_by_timestamp_proximity(self):
        from src.evaluation import labeled_recall

        summary = {
            "commitments": [
                {"who": "SPEAKER_ME", "what": "прислать ссылку на документ", "quote": "сейчас я пришлю ссылку"}
            ],
            "action_items": ["[29:20] @SPEAKER_ME: скинуть материалы в Telegram"],
        }
        labels = [
            {"ts": "29:17", "text": "скинуть материалы в Telegram"},
            {"ts": "37:23", "text": "прислать ссылку"},
        ]
        r = labeled_recall(summary, labels)
        assert r == {"total": 2, "found": 2}

    def test_missed_promise_counted(self):
        from src.evaluation import labeled_recall

        summary = {"commitments": [], "action_items": []}
        r = labeled_recall(summary, [{"ts": "1:00", "text": "прислать смету"}])
        assert r == {"total": 1, "found": 0}
