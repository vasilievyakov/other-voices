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

from src.commitments2 import _tokens, extract_commitments, find_candidates  # noqa: E402
from src.config import DB_PATH  # noqa: E402
from src.evaluation import labeled_recall  # noqa: E402

print = functools.partial(print, flush=True)

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
        t0 = time.monotonic()
        for k in range(args.k):
            runs.append(extract_commitments(s["transcript"]))
            print(f"  [{sid}] run {k + 1}/{args.k}: {len(runs[-1])} commitment(s)")
        elapsed = round(time.monotonic() - t0, 1)

        union_last = runs[-1]
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
        }
        if sid in LABELS:
            entry["recall"] = labeled_recall(
                {"commitments": union_last, "action_items": []}, LABELS[sid]
            )
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
    report = {"aggregate": aggregate, "sessions": results}
    (out_dir / "commitments-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    main()
