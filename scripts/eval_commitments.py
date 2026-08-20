"""Focused eval for commitment extraction v2: recall, stability, precision.

Usage: .venv/bin/python scripts/eval_commitments.py <cycle-name> [--k 3]

Runs ONLY the v2 extractor (no full summarization) K times per session over
the golden set, so a polish cycle takes minutes, not an hour. Writes
eval/<cycle-name>/commitments-report.json.
"""

import argparse
import functools
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.commitments2 as commitments2  # noqa: E402
from scripts.audit_commitments import (  # noqa: E402
    AUDIT_PATH,
    fetch_commitments,
    parse_verdicts,
    score_verdicts,
)
from src.commitments2 import (  # noqa: E402
    CLASSIFY_PROMPT,
    _tokens,
    extract_commitments,
    find_candidates,
)
from src.config import DB_PATH  # noqa: E402
from src.evaluation import _stems, labeled_recall  # noqa: E402

print = functools.partial(print, flush=True)

REGRESSION_SET_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "regression-set.json"
)

_labels_path = Path(__file__).resolve().parent.parent / "eval" / "golden-labels.json"
LABELS: dict = (
    json.loads(_labels_path.read_text())["sessions"] if _labels_path.exists() else {}
)


def _key(item: dict) -> frozenset:
    return frozenset(_tokens(item.get("quote") or item.get("what") or ""))


def self_consistency(runs: list[list[dict]]) -> float | None:
    """Mean share of runs confirming each unique commitment (union key =
    committer + quote-token overlap >= 0.6)."""
    unique: list[tuple[str, frozenset, int]] = []  # (who, tokens, hits)
    for run in runs:
        for item in run:
            tokens = _key(item)
            matched = False
            for i, (who, kept, hits) in enumerate(unique):
                if who != item["who"] or not tokens or not kept:
                    continue
                if len(tokens & kept) / min(len(tokens), len(kept)) >= 0.6:
                    unique[i] = (who, kept, hits + 1)
                    matched = True
                    break
            if not matched:
                unique.append((item["who"], tokens, 1))
    if not unique:
        return None
    return round(sum(h for _, _, h in unique) / (len(unique) * len(runs)), 3)


# Same threshold labeled_recall uses end-to-end: a label matches a text when
# >= 0.3 of its stems occur in it. The funnel repeats one matching rule at
# every stage so a stage transition, not a rule change, explains each loss.
_MATCH_THRESHOLD = 0.3


def _label_matches(label_stems: set, text: str) -> bool:
    if not label_stems:
        return False
    return len(label_stems & _stems(text)) / len(label_stems) >= _MATCH_THRESHOLD


class _RecordingLLM:
    """Wraps an llm callable keeping (prompt, verdict) pairs, so the funnel
    can attribute yes-votes to candidates without re-implementing the
    extractor's voting loop."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, prompt, temperature=0.25, schema=None):
        verdict = self._inner(prompt, temperature=temperature, schema=schema)
        self.calls.append((prompt, verdict))
        return verdict


def build_funnel(
    labels: list[dict],
    candidates: list[dict],
    yes_votes: list[bool],
    extracted: list[dict],
) -> dict:
    """Attribute every golden label to the funnel stage where it died.

    stage1: some candidate's context window covers the label;
    stage2: a covering candidate got at least one LLM yes-vote;
    stage3: a final item with verified != "failed" matches the label
            (verification, attestation and dedup all live in code stage 3).
    """
    surviving_texts = [
        f"{item.get('what') or ''} {item.get('quote') or ''}"
        for item in extracted
        if item.get("verified") != "failed"
    ]
    covered: list[str] = []
    stage2: list[str] = []
    stage3: list[str] = []
    lost: list[dict] = []
    for label in labels:
        name = label.get("text") or ""
        stems = _stems(name)
        covering = [
            i
            for i, cand in enumerate(candidates)
            if _label_matches(stems, cand["context"])
        ]
        if not covering:
            lost.append({"label": name, "ts": label.get("ts"), "stage": "stage1"})
            continue
        covered.append(name)
        if not any(yes_votes[i] for i in covering):
            lost.append({"label": name, "ts": label.get("ts"), "stage": "stage2"})
            continue
        stage2.append(name)
        if not any(_label_matches(stems, text) for text in surviving_texts):
            lost.append({"label": name, "ts": label.get("ts"), "stage": "stage3"})
            continue
        stage3.append(name)
    return {
        "labels": len(labels),
        "stage1_coverage": {"count": len(covered), "covered": covered},
        "stage2_survival": {"count": len(stage2), "survived": stage2},
        "stage3_survival": {"count": len(stage3), "survived": stage3},
        "lost": lost,
    }


def eval_funnel(
    transcript: str, labels: list[dict], llm=None, votes: int = 3
) -> tuple[list[dict], dict]:
    """One real extraction run plus its per-label funnel.

    The recording wrapper intercepts the extractor's own LLM calls; prompts
    are re-derived per candidate with the extractor's own template, so no
    voting logic is duplicated here."""
    candidates = find_candidates(transcript)
    recorder = _RecordingLLM(llm or commitments2._call_llm)
    extracted = extract_commitments(transcript, llm=recorder, votes=votes)
    yes_votes = []
    for cand in candidates:
        prompt = CLASSIFY_PROMPT.format(context=cand["context"], line=cand["line"])
        yes_votes.append(
            any(
                isinstance(verdict, dict) and verdict.get("is_commitment")
                for recorded_prompt, verdict in recorder.calls
                if recorded_prompt == prompt
            )
        )
    return extracted, build_funnel(labels, candidates, yes_votes, extracted)


def regression_check(rows: list[dict], extracted_by_session: dict) -> dict:
    """Score the current run against the owner-curated regression set.

    An open row the run failed to reproduce is a regression (lost a promise
    the owner kept); a dismissed row it reproduced is a regression too
    (resurrected what the owner rejected). Rows from sessions the run did not
    evaluate are not judged."""
    open_total = open_kept = dismissed_total = dismissed_reproduced = 0
    evaluated = 0
    regressions: list[dict] = []
    for row in rows:
        sid = row.get("session_id")
        if sid not in extracted_by_session:
            continue
        status = row.get("status")
        if status not in ("open", "dismissed"):
            continue
        evaluated += 1
        stems = _stems(f"{row.get('text') or ''} {row.get('verbatim_quote') or ''}")
        reproduced = any(
            _label_matches(stems, f"{item.get('what') or ''} {item.get('quote') or ''}")
            for item in extracted_by_session[sid]
        )
        if status == "open":
            open_total += 1
            if reproduced:
                open_kept += 1
            else:
                regressions.append(
                    {
                        "id": row.get("id"),
                        "session_id": sid,
                        "kind": "open_lost",
                        "text": row.get("text"),
                    }
                )
        else:
            dismissed_total += 1
            if reproduced:
                dismissed_reproduced += 1
                regressions.append(
                    {
                        "id": row.get("id"),
                        "session_id": sid,
                        "kind": "dismissed_reproduced",
                        "text": row.get("text"),
                    }
                )
    return {
        "rows_total": len(rows),
        "rows_evaluated": evaluated,
        "open_total": open_total,
        "open_kept": open_kept,
        "kept_open_rate": round(open_kept / open_total, 3) if open_total else None,
        "dismissed_total": dismissed_total,
        "dismissed_reproduced": dismissed_reproduced,
        "reproduced_dismissed_rate": (
            round(dismissed_reproduced / dismissed_total, 3)
            if dismissed_total
            else None
        ),
        "regressions": regressions,
    }


def precision_block(audit_path=AUDIT_PATH, db_path=DB_PATH) -> dict:
    """Owner-labeled precision for the report; honest null until labeled."""
    audit_path = Path(audit_path)
    if not audit_path.exists():
        return {"precision": None, "note": "awaiting owner labels"}
    rows = fetch_commitments(db_path, include_dismissed=True)
    verdicts = parse_verdicts(audit_path.read_text(encoding="utf-8"))
    result = score_verdicts(verdicts, rows)
    if not result["marked"]:
        return {"precision": None, "note": "awaiting owner labels"}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cycle")
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()

    golden = json.loads(
        (
            Path(__file__).resolve().parent.parent / "eval" / "golden-set.json"
        ).read_text()
    )["session_ids"]

    conn = sqlite3.connect(DB_PATH)
    out_dir = Path(__file__).resolve().parent.parent / "eval" / args.cycle
    out_dir.mkdir(parents=True, exist_ok=True)

    sessions = []
    for sid in golden:
        row = conn.execute(
            "SELECT transcript FROM calls WHERE session_id=?", (sid,)
        ).fetchone()
        if row and row[0]:
            sessions.append({"session_id": sid, "transcript": row[0]})

    results = []
    for s in sessions:
        sid = s["session_id"]
        candidates = len(find_candidates(s["transcript"]))
        runs = []
        funnel = None
        t0 = time.monotonic()
        for k in range(args.k):
            if k == args.k - 1:
                # last run doubles as the funnel run: same pipeline, with
                # per-candidate yes-votes recorded for stage attribution
                extracted, funnel = eval_funnel(s["transcript"], LABELS.get(sid, []))
                runs.append(extracted)
            else:
                runs.append(extract_commitments(s["transcript"]))
            print(f"  [{sid}] run {k + 1}/{args.k}: {len(runs[-1])} commitment(s)")
        elapsed = round(time.monotonic() - t0, 1)

        union_last = runs[-1]
        # extractions saved for diagnosis — polish cycles must not re-run
        # the model just to see what was extracted (reviewer, cycle 1)
        entry = {
            "session_id": sid,
            "candidates": candidates,
            "counts": [len(r) for r in runs],
            "self_consistency": self_consistency(runs),
            "uncertain_rate": round(
                sum(1 for r in runs for c in r if c.get("uncertain"))
                / max(sum(len(r) for r in runs), 1),
                3,
            ),
            "verified_exact_rate": round(
                sum(1 for r in runs for c in r if c.get("verified") == "exact")
                / max(sum(len(r) for r in runs), 1),
                3,
            ),
            "seconds": elapsed,
            "extracted": union_last,
        }
        if sid in LABELS:
            entry["recall"] = labeled_recall(
                {"commitments": union_last, "action_items": []}, LABELS[sid]
            )
            entry["funnel"] = funnel
        results.append(entry)
        print(f"  [{sid}] counts={entry['counts']} sc={entry['self_consistency']}")

    scs = [r["self_consistency"] for r in results if r["self_consistency"] is not None]
    recalls = [r["recall"] for r in results if "recall" in r]
    aggregate = {
        "sessions": len(results),
        "k": args.k,
        "mean_self_consistency": round(sum(scs) / len(scs), 3) if scs else None,
        "recall_total": sum(r["total"] for r in recalls),
        "recall_found": sum(r["found"] for r in recalls),
        "total_seconds": round(sum(r["seconds"] for r in results), 1),
    }
    funnels = [(r["session_id"], r["funnel"]) for r in results if "funnel" in r]
    aggregate["funnel"] = {
        "labels": sum(f["labels"] for _, f in funnels),
        "stage1_covered": sum(f["stage1_coverage"]["count"] for _, f in funnels),
        "stage2_survived": sum(f["stage2_survival"]["count"] for _, f in funnels),
        "stage3_survived": sum(f["stage3_survival"]["count"] for _, f in funnels),
        "lost": [
            dict(item, session_id=sid) for sid, f in funnels for item in f["lost"]
        ],
    }

    if REGRESSION_SET_PATH.exists():
        regression = regression_check(
            json.loads(REGRESSION_SET_PATH.read_text(encoding="utf-8"))["rows"],
            {r["session_id"]: r["extracted"] for r in results},
        )
    else:
        regression = {
            "note": (
                "eval/regression-set.json missing — "
                "run scripts/freeze_regression_set.py"
            )
        }

    report = {
        "aggregate": aggregate,
        "regression": regression,
        "precision": precision_block(),
        "sessions": results,
    }
    (out_dir / "commitments-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    main()
