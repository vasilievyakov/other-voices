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


# Same window the pipeline uses for chunk-overlap dedup — one shared meaning.
TIMESTAMP_WINDOW_SECONDS = 30

_OVERLAP_THRESHOLD = 0.35


def _transcript_moments(transcript: str) -> list[tuple[int, str]]:
    """Per-line (seconds, text) pairs from a [MM:SS]-annotated transcript."""
    moments = []
    for line in (transcript or "").splitlines():
        ts = Summarizer._parse_ts(line.strip())
        if ts is None:
            continue
        text = re.sub(r"^\[[\d:]+\]\s*", "", line.strip())
        text = re.sub(r"^SPEAKER[_ ]?\w+\s*:\s*", "", text)
        moments.append((ts, text))
    return moments


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (text or "").lower()) if len(t) > 2}


def citation_check(summary: dict, transcript: str) -> dict:
    """Mechanically verify timestamped claims against the FULL transcript.

    The LLM judge is blind outside its context slice and intolerant to
    paraphrase (two false «1» scores in cycle 2); this check sees 100% of the
    transcript by construction. Token overlap is recall of the claim's tokens
    in the ±window text: grounded ≥ threshold, else weak (human review, never
    auto-drop). A timestamp with no transcript line nearby is counted apart.
    """
    moments = _transcript_moments(transcript)
    result = {"checked": 0, "grounded": 0, "weak": 0, "timestamp_missing": 0}

    for field in ("key_points", "decisions", "action_items"):
        for item in summary.get(field) or []:
            if not isinstance(item, str):
                continue
            ts = Summarizer._parse_ts(item.strip())
            if ts is None:
                continue
            result["checked"] += 1
            window = [
                text
                for t, text in moments
                if abs(t - ts) <= TIMESTAMP_WINDOW_SECONDS
            ]
            if not window:
                result["timestamp_missing"] += 1
                continue
            claim = re.sub(r"^\[[\d:]+\]\s*", "", item.strip())
            claim = re.sub(r"^@?SPEAKER[_ ]?\w+\s*:\s*", "", claim)
            claim_tokens = _tokens(claim)
            window_tokens = _tokens(" ".join(window))
            if not claim_tokens:
                result["weak"] += 1
                continue
            overlap = len(claim_tokens & window_tokens) / len(claim_tokens)
            if overlap >= _OVERLAP_THRESHOLD:
                result["grounded"] += 1
            else:
                result["weak"] += 1

    transcript_tokens = _tokens(transcript)
    for c in summary.get("commitments") or []:
        quote = (c or {}).get("quote") if isinstance(c, dict) else None
        if not quote:
            continue
        result["checked"] += 1
        q_tokens = _tokens(quote)
        if q_tokens and len(q_tokens & transcript_tokens) / len(q_tokens) >= 0.6:
            result["grounded"] += 1
        else:
            result["weak"] += 1

    return result


def _stems(text: str) -> set[str]:
    """Crude Russian stemming for recall matching: 5-char prefixes bridge
    «скинуть»↔«скину», «собрать»↔«соберу» stays apart (accepted cost)."""
    return {t[:5] for t in re.findall(r"\w+", (text or "").lower()) if len(t) > 2}


def labeled_recall(summary: dict, labels: list[dict]) -> dict:
    """First recall measure: did hand-labeled promises reach the summary?

    A labeled promise counts as found when any commitment (what+quote) or
    action item overlaps its tokens (≥0.3) or carries a timestamp within 90s.
    """
    candidates: list[tuple[set, int | None]] = []
    for c in summary.get("commitments") or []:
        if isinstance(c, dict):
            text = f"{c.get('what') or ''} {c.get('quote') or ''}"
            candidates.append((_stems(text), None))
    for item in summary.get("action_items") or []:
        if isinstance(item, str):
            candidates.append((_stems(item), Summarizer._parse_ts(item.strip())))

    found = 0
    for label in labels:
        label_tokens = _stems(label.get("text") or "")
        label_ts = Summarizer._parse_ts(f"[{label.get('ts')}]")
        hit = False
        for tokens, ts in candidates:
            if label_tokens and len(label_tokens & tokens) / len(label_tokens) >= 0.3:
                hit = True
                break
            if label_ts is not None and ts is not None and abs(ts - label_ts) <= 90:
                hit = True
                break
        if hit:
            found += 1
    return {"total": len(labels), "found": found}
