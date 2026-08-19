"""Call Recorder — pipeline quality metrics for eval runs.

Pure functions over (summary, transcript) pairs. The eval runner
(scripts/run_eval.py) applies them to fresh pipeline output; results feed the
board-review cycles. Nothing here writes to the database.
"""

import re

from .summarizer import Summarizer

# A name counts as present when its stem appears with a real Russian case
# ending («Максиму», «Андреем»). Arbitrary tails are not accepted — «максимум»
# must not attest «Максим».
_CASE_ENDINGS = r"(?:ами|ями|ах|ях|ам|ям|ой|ей|ем|ём|ом|а|я|у|ю|е|ё|и|ы|о|й|ь)?"


def _name_present(name: str, transcript: str) -> bool:
    name_l = name.lower()
    # й/ь-stem names inflect by swapping the final letter («Андрей» →
    # «Андреем») — match the stem plus a real case ending only.
    stem = name_l[:-1] if name_l[-1:] in ("й", "ь") and len(name_l) > 3 else name_l
    pattern = rf"(?<!\w){re.escape(stem)}{_CASE_ENDINGS}(?!\w)"
    return bool(re.search(pattern, transcript or "", re.IGNORECASE))


def owner_attestation(summary: dict, transcript: str) -> dict:
    """How many @owner action items survive the attestation the pipeline uses."""
    items = summary.get("action_items") or []
    participants = summary.get("participants") or []
    with_owner = 0
    attested = 0
    for item in items:
        if not isinstance(item, str):
            continue
        m = re.search(r"@([^\s:,;)\]]+)", item)
        if not m:
            continue
        owner = m.group(1).strip(".,;:()[]").strip()
        if not owner:
            continue
        with_owner += 1
        if Summarizer._owner_attested(owner, participants, transcript):
            attested += 1
    return {"with_owner": with_owner, "attested": attested}


def hallucinated_participants(summary: dict, transcript: str) -> list[str]:
    """Participants the model listed that never appear in the transcript."""
    flagged = []
    for name in summary.get("participants") or []:
        if not isinstance(name, str) or not name.strip():
            continue
        if re.fullmatch(r"speaker[_ ]?\w+", name.strip().lower()):
            continue
        # Multi-word names count as present if any single token is present.
        tokens = name.strip().split()
        if not any(_name_present(t, transcript) for t in tokens):
            flagged.append(name)
    return flagged


def coverage_correct(summary: dict, transcript: str) -> bool:
    """Does the stored coverage match what the transcript actually contains?"""
    return summary.get("coverage") == Summarizer._detect_coverage(transcript)


def summary_shape(summary: dict | None) -> dict:
    """Structural stats of one summary; failed=True when the pipeline gave None."""
    if not isinstance(summary, dict):
        return {"failed": True}
    return {
        "failed": False,
        "summary_chars": len(summary.get("summary") or ""),
        "key_points": len(summary.get("key_points") or []),
        "decisions": len(summary.get("decisions") or []),
        "action_items": len(summary.get("action_items") or []),
        "participants": len(summary.get("participants") or []),
        "repaired": bool(summary.get("_repaired")),
    }
