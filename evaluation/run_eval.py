#!/usr/bin/env python3
"""Run commitment extraction pipeline on ground truth sessions and evaluate.

Reads session_ids from ground_truth.json, runs the extraction pipeline on
each call's transcript, saves predictions, and runs evaluation.

Usage:
    python run_eval.py                          # default files
    python run_eval.py --ground-truth gt.json   # custom ground truth
    python run_eval.py --verbose                # detailed output
    python run_eval.py --skip-extract           # use existing predictions.json
    python run_eval.py --prompt karpathy        # force specific prompt

Requirements:
    - Ollama running locally with the configured model
    - data/calls.db with transcripts for the sessions in ground truth
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.commitment_extractor import extract_commitments  # noqa: E402
from src.config import DB_PATH, OLLAMA_MODEL  # noqa: E402
from evaluate import evaluate, format_report, report_to_dict  # noqa: E402


EVAL_DIR = Path(__file__).resolve().parent


def get_transcript(db_path: Path, session_id: str) -> str | None:
    """Fetch transcript for a session from the database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT transcript FROM calls WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["transcript"]


def get_call_date(db_path: Path, session_id: str) -> str | None:
    """Fetch call date for a session from the database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT started_at FROM calls WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["started_at"]


def get_speaker_map(db_path: Path, session_id: str) -> dict:
    """Build a minimal speaker map for evaluation.

    In a real pipeline, this comes from speaker_resolver.py.
    For evaluation, we use a basic map since we are testing
    commitment extraction, not speaker resolution.
    """
    return {
        "SPEAKER_ME": {"confirmed": True, "source": "mic_channel"},
        "SPEAKER_OTHER": {"name": None, "confidence": 0.0, "source": None},
    }


def run_extraction(
    ground_truth: dict,
    db_path: Path,
    verbose: bool = False,
) -> dict:
    """Run commitment extraction on all sessions in ground truth.

    Returns predictions dict with same structure as ground truth.
    """
    predictions: dict = {}
    session_ids = [k for k in ground_truth.keys() if not k.startswith("_")]

    print(f"Extracting commitments from {len(session_ids)} sessions...")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Database: {db_path}")
    print()

    for i, session_id in enumerate(session_ids, 1):
        print(f"[{i}/{len(session_ids)}] {session_id}...", end=" ", flush=True)

        transcript = get_transcript(db_path, session_id)
        if transcript is None:
            print("SKIP (no transcript)")
            predictions[session_id] = {
                "commitments": [],
                "error": "no transcript in database",
            }
            continue

        call_date = get_call_date(db_path, session_id)
        speaker_map = get_speaker_map(db_path, session_id)

        start_time = time.time()
        try:
            result = extract_commitments(
                transcript_text=transcript,
                speaker_map=speaker_map,
                call_date=call_date,
            )
        except Exception as e:
            print(f"ERROR ({e})")
            predictions[session_id] = {
                "commitments": [],
                "error": str(e),
            }
            continue

        elapsed = time.time() - start_time
        n_commitments = len(result.get("commitments", []))
        n_chunks = result.get("_chunks", 1)
        print(
            f"{n_commitments} commitments ({n_chunks} chunk{'s' if n_chunks > 1 else ''}, {elapsed:.1f}s)"
        )

        if verbose and n_commitments > 0:
            for c in result["commitments"]:
                direction = c.get("type") or c.get("direction", "?")
                who = c.get("who") or c.get("committer_label", "?")
                what = c.get("what") or c.get("commitment_text", "?")
                print(f"    [{direction}] {who}: {what}")

        predictions[session_id] = {
            "commitments": result.get("commitments", []),
            "extraction_notes": result.get("extraction_notes"),
            "chunks": n_chunks,
            "elapsed_seconds": round(elapsed, 1),
        }

    return predictions


def main():
    parser = argparse.ArgumentParser(
        description="Run commitment extraction evaluation pipeline"
    )
    parser.add_argument(
        "--ground-truth",
        "-g",
        default=str(EVAL_DIR / "ground_truth.json"),
        help="Path to ground truth JSON (default: evaluation/ground_truth.json)",
    )
    parser.add_argument(
        "--predictions",
        "-p",
        default=str(EVAL_DIR / "predictions.json"),
        help="Path to save/load predictions JSON",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(EVAL_DIR / "results.json"),
        help="Path to save evaluation results JSON",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help=f"Path to calls.db (default: {DB_PATH})",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extraction, use existing predictions.json",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output during extraction and evaluation",
    )
    args = parser.parse_args()

    # Load ground truth
    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"Error: ground truth file not found: {gt_path}", file=sys.stderr)
        print(
            f"Hint: copy ground_truth_template.json to ground_truth.json and annotate it",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(gt_path) as f:
        ground_truth = json.load(f)

    # Check if ground truth has any annotations
    total_gt = sum(
        len(v.get("commitments", []))
        for k, v in ground_truth.items()
        if not k.startswith("_") and isinstance(v, dict)
    )

    pred_path = Path(args.predictions)
    db_path = Path(args.db)

    if args.skip_extract:
        # Load existing predictions
        if not pred_path.exists():
            print(f"Error: predictions file not found: {pred_path}", file=sys.stderr)
            sys.exit(1)
        with open(pred_path) as f:
            predictions = json.load(f)
        print(f"Loaded existing predictions from {pred_path}")
    else:
        # Check database exists
        if not db_path.exists():
            print(f"Error: database not found: {db_path}", file=sys.stderr)
            sys.exit(1)

        # Run extraction
        predictions = run_extraction(
            ground_truth=ground_truth,
            db_path=db_path,
            verbose=args.verbose,
        )

        # Save predictions
        with open(pred_path, "w") as f:
            json.dump(predictions, f, indent=2, ensure_ascii=False)
        print(f"\nPredictions saved to {pred_path}")

    # Run evaluation
    print()
    report = evaluate(ground_truth, predictions)
    print(format_report(report, ground_truth, predictions, verbose=args.verbose))

    # Save results
    result_dict = report_to_dict(report)
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_path}")

    # Warn if no ground truth annotations
    if total_gt == 0:
        print()
        print("WARNING: Ground truth has 0 annotated commitments.")
        print("The evaluation above only measures false positives from predictions.")
        print()
        print("Next steps:")
        print("  1. Copy ground_truth_template.json to ground_truth.json")
        print("  2. Read transcripts for each session_id")
        print("  3. Annotate commitments following DEFINITION.md")
        print("  4. Re-run: python run_eval.py")

    # Return exit code based on quality
    if total_gt > 0 and report.f1 < 0.70:
        sys.exit(1)  # Quality below threshold
    sys.exit(0)


if __name__ == "__main__":
    main()
