"""Call Recorder — closure detection: promise on call T1, evidence on call T2.

Karpathy plan item (docs/plans/2026-08-20-market-parity-plan.md, item 4):
«я отправил» on a later call is a CANDIDATE for closing an earlier open
commitment. Three code-only stages, mirroring the extractor in commitments2
(no LLM in this version):

  stage 1 (code): regex candidates of fulfilment evidence — 1st person
                  perfective past («отправил(а)», «скинул(а)», …),
                  «я уже …», «все, … готово», «отправлено». Morphology uses
                  real endings (the evaluation._name_present convention),
                  never \\w-tails;
  stage 2 (code): match evidence against earlier OPEN commitments of the SAME
                  owner-direction: 5-char-prefix stem overlap (the
                  commitments2._title_grounded convention) >= 0.5 over the
                  smaller set; the evidence call is strictly LATER than the
                  promise call;
  stage 3 (code): both quotes hold — the promise quote must already sit in the
                  DB (verbatim_quote), the evidence quote is checked with
                  commitments2.verify_quote against the evidence transcript;
                  failed pairs are dropped.

Nothing here writes to the database: status changes only by the owner's hand.
This module PROPOSES; the morning digest shows the pair, the decision stays
human.
"""

import re

from .commitments2 import verify_quote

# --- Stage 1: evidence candidate patterns -----------------------------------

# «он отправил» is a retelling of someone else's deed, not the speaker's own,
# and «не сделал» is the opposite of evidence (live-base false positive).
# re lookbehinds must be fixed-width, so one guard per token.
_NOT_FIRST_PERSON = r"(?<!\bон )(?<!\bона )(?<!\bони )(?<!\bты )(?<!\bвы )(?<!\bне )"

EVIDENCE_PATTERNS = [
    # 1st person perfective past, masculine/feminine. Real endings only:
    # «отправил(а)» matches, «отправили» (plural) and «отправлю» (future)
    # do not — the _name_present convention, no \w-tails.
    re.compile(
        _NOT_FIRST_PERSON
        + r"\b(?:отправил|скинул|сделал|прислал|написал|выложил|загрузил|"
        r"поставил)(?:а)?\b",
        re.IGNORECASE,
    ),
    # reflexive perfective past: «договорился/договорилась», «созвонился/…»
    re.compile(
        _NOT_FIRST_PERSON + r"\b(?:договорил|созвонил)(?:ся|ась)\b",
        re.IGNORECASE,
    ),
    # «я уже …» + a past-tense verb (constrained tail: -л/-ла/-лся/-лась)
    re.compile(
        r"\bя уже\b[^.?!\n]{0,40}?(?<!\bне )\b[а-яё]{3,}л(?:а|ся|ась)?\b",
        re.IGNORECASE,
    ),
    # statements of completion
    re.compile(r"\bвс[её]\b[^.?!\n]{0,30}?\bготово\b", re.IGNORECASE),
    re.compile(r"\bотправлено\b", re.IGNORECASE),
]

# Transcript line: optional "[m:ss]" timestamp, optional "SPEAKER_X:" label.
_LINE_RE = re.compile(r"^\s*(?:\[[\d:]+\]\s*)?(?:(SPEAKER_[A-Z0-9]+)\s*:\s*)?(.*)$")

OVERLAP_THRESHOLD = 0.5


def find_evidence(transcript: str) -> list[dict]:
    """Stage 1: lines where the speaker reports a completed deed.

    Returns [{"speaker": "SPEAKER_X" | None, "quote": line_text}].
    Lines without a speaker label keep speaker=None — the matching stage
    drops them: unattributable evidence cannot establish an owner.
    """
    out = []
    for raw in (transcript or "").splitlines():
        if not raw.strip():
            continue
        m = _LINE_RE.match(raw)
        speaker, content = m.group(1), (m.group(2) or "").strip()
        if not content:
            continue
        if any(p.search(content) for p in EVIDENCE_PATTERNS):
            out.append({"speaker": speaker, "quote": content})
    return out


# --- Stage 2: owner and overlap ---------------------------------------------


def _stems(text: str) -> set[str]:
    # Same convention as commitments2._title_grounded: content words only
    # (len > 2), 5-char prefixes as poor-man's stemming.
    return {w[:5] for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 2}


def stem_overlap(evidence_text: str, commitment_text: str) -> float:
    """Overlap of 5-char stems, measured against the smaller set."""
    a, b = _stems(evidence_text), _stems(commitment_text)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _commitment_owner(c: dict) -> str | None:
    """Identity key of the promise owner: "ME" or a lowercase name."""
    if (c.get("direction") or "") == "outgoing":
        return "ME"
    name = (c.get("who_name") or "").strip()
    if not name:
        label = (c.get("who_label") or "").strip()
        # A bare SPEAKER_N label is not a cross-call identity.
        if label and not label.upper().startswith("SPEAKER_"):
            name = label
    return name.lower() or None


def _evidence_owner(speaker: str | None, speaker_names: dict) -> str | None:
    """Identity key of the evidence speaker in its own call."""
    if speaker is None:
        return None
    if speaker == "SPEAKER_ME":
        return "ME"
    # SPEAKER_N labels are per-call; only the owner-set rename links them
    # to a person that can also own a commitment from another call.
    name = (speaker_names.get(speaker) or "").strip()
    return name.lower() or None


# --- Pipeline ----------------------------------------------------------------


def build_closure_proposals(db) -> list[dict]:
    """Read-only scan: pairs (open commitment, later fulfilment evidence).

    One proposal per commitment: the earliest qualifying evidence call wins,
    inside it — the highest stem overlap. Returns dicts with commitment_id,
    commitment_text, commitment_quote, evidence_session_id, evidence_quote,
    evidence_date. Never writes: closing is the owner's hand.
    """
    open_items = [
        c
        for c in db.get_open_commitments()
        if (c.get("verbatim_quote") or "").strip()  # stage 3: quote in the DB
    ]
    if not open_items:
        return []

    calls = db.list_recent(limit=1_000_000)
    calls.sort(key=lambda c: c.get("started_at") or "")  # oldest first
    evidence_cache: dict[str, tuple[str, list[dict]]] = {}
    names_cache: dict[str, dict] = {}

    proposals: list[dict] = []
    for c in sorted(open_items, key=lambda x: x["id"]):
        owner = _commitment_owner(c)
        if owner is None:
            continue
        promise_started = c.get("started_at") or ""
        if not promise_started:
            continue
        source = f"{c.get('text') or ''} {c.get('verbatim_quote') or ''}"

        best: tuple[float, dict, dict] | None = None
        for call in calls:
            sid = call["session_id"]
            started = call.get("started_at") or ""
            # strictly later call only — same call never closes its own promise
            if sid == c.get("session_id") or started <= promise_started:
                continue
            if sid not in evidence_cache:
                transcript = (db.get_call(sid) or {}).get("transcript") or ""
                evidence_cache[sid] = (transcript, find_evidence(transcript))
            transcript, candidates = evidence_cache[sid]
            if not candidates:
                continue
            if sid not in names_cache:
                names_cache[sid] = db.get_speaker_names(sid)
            for ev in candidates:
                if _evidence_owner(ev["speaker"], names_cache[sid]) != owner:
                    continue
                overlap = stem_overlap(ev["quote"], source)
                if overlap < OVERLAP_THRESHOLD:
                    continue
                # stage 3: the evidence quote must hold against its transcript
                if verify_quote(ev["quote"], transcript) == "failed":
                    continue
                if best is None or overlap > best[0]:
                    best = (overlap, ev, call)
            if best is not None:
                break  # earliest evidence call wins

        if best is not None:
            _, ev, call = best
            proposals.append(
                {
                    "commitment_id": c["id"],
                    "commitment_text": c.get("text") or "",
                    "commitment_quote": c.get("verbatim_quote") or "",
                    "evidence_session_id": call["session_id"],
                    "evidence_quote": ev["quote"],
                    "evidence_date": (call.get("started_at") or "")[:10],
                }
            )
    return proposals
