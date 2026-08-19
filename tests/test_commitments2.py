"""Tests for src.commitments2 — narrow two-stage commitment extraction."""

from src.commitments2 import (
    extract_commitments,
    find_candidates,
    verify_quote,
)

TRANSCRIPT = """[0:30] SPEAKER_ME: обсуждаем план на квартал
[1:30] SPEAKER_ME: хорошо, я пришлю договор в пятницу
[2:10] SPEAKER_1: отлично, жду
[5:00] SPEAKER_1: давайте на следующей неделе синхронимся по бюджету
[7:20] SPEAKER_ME: сейчас скину ссылку в телеграм
[9:00] SPEAKER_1: погода сегодня хорошая"""


class TestCandidates:
    def test_hard_commissive_found(self):
        cands = find_candidates(TRANSCRIPT)
        lines = [c["line"] for c in cands]
        assert any("пришлю договор" in l for l in lines)

    def test_soft_cohortative_found(self):
        cands = find_candidates(TRANSCRIPT)
        assert any("синхронимся" in c["line"] for c in cands)

    def test_immediacy_found(self):
        cands = find_candidates(TRANSCRIPT)
        assert any("сейчас скину" in c["line"] for c in cands)

    def test_plain_line_ignored(self):
        cands = find_candidates(TRANSCRIPT)
        assert not any("погода" in c["line"] for c in cands)

    def test_context_window_includes_neighbors(self):
        cands = find_candidates(TRANSCRIPT)
        c = next(c for c in cands if "пришлю договор" in c["line"])
        assert "обсуждаем план" in c["context"]
        assert "жду" in c["context"]


class TestVerifyQuote:
    CONTEXT = "[1:30] SPEAKER_ME: хорошо, я пришлю договор в пятницу"

    def test_exact_after_normalization(self):
        assert verify_quote("я пришлю договор в пятницу", self.CONTEXT) == "exact"

    def test_fuzzy_tolerates_small_drift(self):
        assert verify_quote("пришлю договор в эту пятницу", self.CONTEXT) == "fuzzy"

    def test_fabricated_quote_fails(self):
        assert verify_quote("подпишу контракт завтра утром", self.CONTEXT) == "failed"


def _llm_always(payloads):
    """LLM stub returning queued responses in order (cycled)."""
    state = {"i": 0}

    def call(prompt, temperature=0.25):
        r = payloads[state["i"] % len(payloads)]
        state["i"] += 1
        return r

    return call


_YES = {
    "is_commitment": True,
    "confidence": "явное",
    "committer": "SPEAKER_ME",
    "recipient": "",
    "text": "прислать договор",
    "deadline": "пятница",
    "quote": "я пришлю договор в пятницу",
}
_NO = {
    "is_commitment": False,
    "confidence": "",
    "committer": "",
    "recipient": "",
    "text": "",
    "deadline": "",
    "quote": "",
}


class TestExtraction:
    def test_consensus_two_of_three_accepted(self):
        llm = _llm_always([_YES, _YES, _NO])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        target = [c for c in out if c["what"] == "прислать договор"]
        assert len(target) == 1
        assert target[0]["type"] == "outgoing"
        assert target[0]["uncertain"] == 0
        assert target[0]["confidence_votes"] == "2/3"
        assert target[0]["verified"] == "exact"

    def test_one_of_three_kept_as_uncertain(self):
        llm = _llm_always([_YES, _NO, _NO])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        target = [c for c in out if c["what"] == "прислать договор"]
        assert len(target) == 1
        assert target[0]["uncertain"] == 1

    def test_zero_votes_dropped(self):
        llm = _llm_always([_NO])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        assert out == []

    def test_unattested_committer_dropped(self):
        ghost = dict(_YES, committer="Призрак")
        llm = _llm_always([ghost])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        assert all(c["who"] != "Призрак" for c in out)

    def test_incoming_direction_for_other_speaker(self):
        other = dict(
            _YES,
            committer="SPEAKER_1",
            text="синхронизироваться по бюджету",
            quote="давайте на следующей неделе синхронимся по бюджету",
            deadline="следующая неделя",
        )
        llm = _llm_always([other])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        target = [c for c in out if "синхрон" in c["what"]]
        assert target and target[0]["type"] == "incoming"

    def test_near_duplicate_quotes_deduped(self):
        v1 = dict(_YES)
        v2 = dict(_YES, quote="пришлю договор в пятницу", text="пришлю договор")
        llm = _llm_always([v1, v2, v1])
        out = extract_commitments(TRANSCRIPT, llm, votes=3)
        assert len([c for c in out if "договор" in c["what"]]) == 1
