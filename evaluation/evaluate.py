#!/usr/bin/env python3
"""Commitment extraction evaluation framework.

Compares ground truth annotations against system predictions.
Computes precision, recall, F1 for commitment detection and
per-field accuracy for direction, who, to_whom, deadline.

Usage:
    python evaluate.py ground_truth.json predictions.json
    python evaluate.py ground_truth.json predictions.json --verbose
    python evaluate.py ground_truth.json predictions.json --output results.json
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum similarity ratio for quote-based matching
QUOTE_SIMILARITY_THRESHOLD = 0.40

# Minimum similarity for text-based matching (action descriptions)
TEXT_SIMILARITY_THRESHOLD = 0.35

# Quality thresholds from Murati
THRESHOLDS = {
    "precision": 0.70,
    "recall": 0.70,
    "f1": 0.70,
    "direction_accuracy": 0.85,
    "who_accuracy": 0.80,
    "deadline_accuracy": 0.75,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Commitment:
    """A single commitment extracted from a call."""

    who: str
    to_whom: str
    text: str
    direction: str
    deadline: str | None = None
    quote: str = ""
    uncertain: bool = False
    conditional: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Commitment":
        """Create from a ground truth or prediction dict.

        Handles both Karpathy-style (type/what/quote) and Murati-style
        (direction/commitment_text/verbatim_quote) field names.
        """
        # Direction: "type" (Karpathy) or "direction" (Murati/ground truth)
        direction = d.get("direction") or d.get("type", "")

        # Who: "who" or "committer_label" or "who_label" or "agent_label"
        who = (
            d.get("who")
            or d.get("committer_label")
            or d.get("who_label")
            or d.get("agent_label")
            or ""
        )
        # Use name if available and label is generic
        who_name = d.get("who_name") or d.get("committer_name") or d.get("agent_name")
        if who_name and who.startswith("SPEAKER_"):
            who = who_name

        # To whom: "to_whom" or "recipient_label" or "to_label" or "beneficiary_label"
        to_whom = (
            d.get("to_whom")
            or d.get("recipient_label")
            or d.get("to_label")
            or d.get("beneficiary_label")
            or ""
        )
        to_whom_name = (
            d.get("to_whom_name")
            or d.get("recipient_name")
            or d.get("to_name")
            or d.get("beneficiary_name")
        )
        if to_whom_name and to_whom.startswith("SPEAKER_"):
            to_whom = to_whom_name

        # Text: "text" or "what" or "commitment_text"
        text = d.get("text") or d.get("what") or d.get("commitment_text") or ""

        # Quote: "quote" or "verbatim_quote" or "verbatim"
        quote = d.get("quote") or d.get("verbatim_quote") or d.get("verbatim") or ""

        # Deadline: "deadline" or "deadline_raw"
        deadline = d.get("deadline") or d.get("deadline_raw")

        # Uncertain
        uncertain = bool(d.get("uncertain", False))
        # Murati: low confidence = uncertain
        confidence = d.get("commitment_confidence")
        if confidence is not None and isinstance(confidence, (int, float)):
            if confidence < 0.5:
                uncertain = True

        conditional = bool(d.get("conditional", False))

        return cls(
            who=who,
            to_whom=to_whom,
            text=text,
            direction=direction,
            deadline=deadline,
            quote=quote,
            uncertain=uncertain,
            conditional=conditional,
        )


@dataclass
class MatchResult:
    """Result of matching one ground truth commitment to predictions."""

    gt_index: int
    pred_index: int | None  # None = miss (FN)
    similarity: float = 0.0
    direction_match: bool = False
    who_match: bool = False
    to_whom_match: bool = False
    deadline_match: bool = False


@dataclass
class SessionResult:
    """Evaluation results for a single call session."""

    session_id: str
    gt_count: int = 0
    pred_count: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    matches: list[MatchResult] = field(default_factory=list)
    unmatched_preds: list[int] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class EvalReport:
    """Aggregate evaluation report across all sessions."""

    sessions: list[SessionResult] = field(default_factory=list)
    total_gt: int = 0
    total_pred: int = 0
    total_tp: int = 0
    total_fp: int = 0
    total_fn: int = 0
    direction_correct: int = 0
    direction_total: int = 0
    who_correct: int = 0
    who_total: int = 0
    to_whom_correct: int = 0
    to_whom_total: int = 0
    deadline_correct: int = 0
    deadline_total: int = 0

    @property
    def precision(self) -> float:
        denom = self.total_tp + self.total_fp
        return self.total_tp / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.total_tp + self.total_fn
        return self.total_tp / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def direction_accuracy(self) -> float:
        return (
            self.direction_correct / self.direction_total
            if self.direction_total > 0
            else 0.0
        )

    @property
    def who_accuracy(self) -> float:
        return self.who_correct / self.who_total if self.who_total > 0 else 0.0

    @property
    def to_whom_accuracy(self) -> float:
        return (
            self.to_whom_correct / self.to_whom_total if self.to_whom_total > 0 else 0.0
        )

    @property
    def deadline_accuracy(self) -> float:
        return (
            self.deadline_correct / self.deadline_total
            if self.deadline_total > 0
            else 0.0
        )


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Normalize a string for comparison: lowercase, strip, collapse whitespace."""
    if not s:
        return ""
    return " ".join(s.lower().strip().split())


def _similarity(a: str, b: str) -> float:
    """Compute string similarity ratio between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _speaker_match(a: str, b: str) -> bool:
    """Check if two speaker identifiers refer to the same person.

    Handles: exact match, name vs label (e.g. "Елена" matches "SPEAKER_OTHER_1"
    if one is a resolved name), case-insensitive.
    """
    if not a or not b:
        return False
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    # Both are "SPEAKER_ME" type labels
    if na.startswith("speaker_me") and nb.startswith("speaker_me"):
        return True
    # One is a label, other is a name -- cannot verify without speaker map,
    # so we check if either contains the other as substring
    if na in nb or nb in na:
        return True
    return False


def _deadline_match(a: str | None, b: str | None) -> bool:
    """Check if two deadline strings match.

    Both null = match. One null other not = no match.
    Otherwise fuzzy string match.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return _similarity(a, b) >= 0.6


def match_commitments(
    ground_truth: list[Commitment],
    predictions: list[Commitment],
) -> tuple[list[MatchResult], list[int]]:
    """Match ground truth commitments to predictions using greedy best-match.

    Returns:
        Tuple of (matches for GT items, indices of unmatched predictions).
        A match with pred_index=None means the GT item was missed (FN).
    """
    if not ground_truth:
        return [], list(range(len(predictions)))

    if not predictions:
        return [
            MatchResult(gt_index=i, pred_index=None) for i in range(len(ground_truth))
        ], []

    # Build similarity matrix
    n_gt = len(ground_truth)
    n_pred = len(predictions)
    scores: list[list[float]] = []

    for i in range(n_gt):
        row = []
        for j in range(n_pred):
            gt_c = ground_truth[i]
            pred_c = predictions[j]

            # Multi-signal matching score
            quote_sim = _similarity(gt_c.quote, pred_c.quote)
            text_sim = _similarity(gt_c.text, pred_c.text)
            who_sim = 1.0 if _speaker_match(gt_c.who, pred_c.who) else 0.0

            # Weighted combination: quote is strongest signal, then text, then who
            if quote_sim >= QUOTE_SIMILARITY_THRESHOLD:
                score = 0.5 * quote_sim + 0.3 * text_sim + 0.2 * who_sim
            elif text_sim >= TEXT_SIMILARITY_THRESHOLD:
                score = 0.3 * quote_sim + 0.5 * text_sim + 0.2 * who_sim
            else:
                score = 0.33 * quote_sim + 0.34 * text_sim + 0.33 * who_sim

            row.append(score)
        scores.append(row)

    # Greedy matching: pick best score, remove both, repeat
    used_gt: set[int] = set()
    used_pred: set[int] = set()
    matches: list[MatchResult] = []

    # Flatten and sort all (gt_i, pred_j, score) by score descending
    all_pairs = [(i, j, scores[i][j]) for i in range(n_gt) for j in range(n_pred)]
    all_pairs.sort(key=lambda x: x[2], reverse=True)

    # Threshold for considering a match valid
    match_threshold = 0.25

    for gt_i, pred_j, score in all_pairs:
        if gt_i in used_gt or pred_j in used_pred:
            continue
        if score < match_threshold:
            break

        gt_c = ground_truth[gt_i]
        pred_c = predictions[pred_j]

        match = MatchResult(
            gt_index=gt_i,
            pred_index=pred_j,
            similarity=score,
            direction_match=_normalize(gt_c.direction) == _normalize(pred_c.direction),
            who_match=_speaker_match(gt_c.who, pred_c.who),
            to_whom_match=_speaker_match(gt_c.to_whom, pred_c.to_whom),
            deadline_match=_deadline_match(gt_c.deadline, pred_c.deadline),
        )
        matches.append(match)
        used_gt.add(gt_i)
        used_pred.add(pred_j)

    # Add misses (unmatched GT items)
    for i in range(n_gt):
        if i not in used_gt:
            matches.append(MatchResult(gt_index=i, pred_index=None))

    # Unmatched predictions (false positives)
    unmatched_preds = sorted(set(range(n_pred)) - used_pred)

    return matches, unmatched_preds


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_session(
    session_id: str,
    gt_commitments: list[dict],
    pred_commitments: list[dict],
) -> SessionResult:
    """Evaluate commitment extraction for a single call session."""
    gt_list = [Commitment.from_dict(c) for c in gt_commitments]
    pred_list = [Commitment.from_dict(c) for c in pred_commitments]

    matches, unmatched_preds = match_commitments(gt_list, pred_list)

    tp = sum(1 for m in matches if m.pred_index is not None)
    fn = sum(1 for m in matches if m.pred_index is None)
    fp = len(unmatched_preds)

    return SessionResult(
        session_id=session_id,
        gt_count=len(gt_list),
        pred_count=len(pred_list),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        matches=matches,
        unmatched_preds=unmatched_preds,
    )


def evaluate(
    ground_truth: dict,
    predictions: dict,
) -> EvalReport:
    """Evaluate commitment extraction across all sessions.

    Args:
        ground_truth: Dict of session_id -> {"commitments": [...]}
        predictions:  Dict of session_id -> {"commitments": [...]}

    Returns:
        EvalReport with aggregate metrics.
    """
    report = EvalReport()

    for session_id, gt_data in ground_truth.items():
        # Skip metadata keys
        if session_id.startswith("_"):
            continue

        gt_commitments = gt_data.get("commitments", [])
        pred_data = predictions.get(session_id, {})
        pred_commitments = pred_data.get("commitments", [])

        session_result = evaluate_session(session_id, gt_commitments, pred_commitments)
        report.sessions.append(session_result)

        report.total_gt += session_result.gt_count
        report.total_pred += session_result.pred_count
        report.total_tp += session_result.true_positives
        report.total_fp += session_result.false_positives
        report.total_fn += session_result.false_negatives

        # Field accuracy on matched commitments
        gt_list = [Commitment.from_dict(c) for c in gt_commitments]
        pred_list = [Commitment.from_dict(c) for c in pred_commitments]

        for match in session_result.matches:
            if match.pred_index is None:
                continue  # FN -- no prediction to compare fields

            report.direction_total += 1
            if match.direction_match:
                report.direction_correct += 1

            report.who_total += 1
            if match.who_match:
                report.who_correct += 1

            report.to_whom_total += 1
            if match.to_whom_match:
                report.to_whom_correct += 1

            report.deadline_total += 1
            if match.deadline_match:
                report.deadline_correct += 1

    return report


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _bar(value: float, width: int = 20) -> str:
    """Create a simple ASCII bar chart segment."""
    filled = int(value * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _status(value: float, threshold: float) -> str:
    """Return PASS/FAIL marker based on threshold."""
    return "PASS" if value >= threshold else "FAIL"


def format_report(
    report: EvalReport,
    ground_truth: dict,
    predictions: dict,
    verbose: bool = False,
) -> str:
    """Format evaluation report as a human-readable string."""
    lines: list[str] = []

    lines.append("=" * 72)
    lines.append("  COMMITMENT EXTRACTION EVALUATION REPORT")
    lines.append("=" * 72)
    lines.append("")

    # --- Overall metrics ---
    lines.append("DETECTION METRICS")
    lines.append("-" * 40)
    lines.append(f"  Ground truth commitments:  {report.total_gt}")
    lines.append(f"  Predicted commitments:     {report.total_pred}")
    lines.append(f"  True positives (matched):  {report.total_tp}")
    lines.append(f"  False positives (extra):   {report.total_fp}")
    lines.append(f"  False negatives (missed):  {report.total_fn}")
    lines.append("")

    p = report.precision
    r = report.recall
    f = report.f1
    lines.append(
        f"  Precision:  {p:.3f}  {_bar(p)}  {_status(p, THRESHOLDS['precision'])}"
    )
    lines.append(
        f"  Recall:     {r:.3f}  {_bar(r)}  {_status(r, THRESHOLDS['recall'])}"
    )
    lines.append(f"  F1:         {f:.3f}  {_bar(f)}  {_status(f, THRESHOLDS['f1'])}")
    lines.append("")

    # --- Field accuracy ---
    lines.append("FIELD ACCURACY (on matched commitments)")
    lines.append("-" * 40)

    if report.direction_total > 0:
        da = report.direction_accuracy
        lines.append(
            f"  Direction:  {da:.3f}  ({report.direction_correct}/{report.direction_total})  {_status(da, THRESHOLDS['direction_accuracy'])}"
        )
    else:
        lines.append("  Direction:  N/A (no matches)")

    if report.who_total > 0:
        wa = report.who_accuracy
        lines.append(
            f"  Who:        {wa:.3f}  ({report.who_correct}/{report.who_total})  {_status(wa, THRESHOLDS['who_accuracy'])}"
        )
    else:
        lines.append("  Who:        N/A (no matches)")

    if report.to_whom_total > 0:
        ta = report.to_whom_accuracy
        lines.append(
            f"  To whom:    {ta:.3f}  ({report.to_whom_correct}/{report.to_whom_total})"
        )
    else:
        lines.append("  To whom:    N/A (no matches)")

    if report.deadline_total > 0:
        dla = report.deadline_accuracy
        lines.append(
            f"  Deadline:   {dla:.3f}  ({report.deadline_correct}/{report.deadline_total})  {_status(dla, THRESHOLDS['deadline_accuracy'])}"
        )
    else:
        lines.append("  Deadline:   N/A (no matches)")
    lines.append("")

    # --- Per-session breakdown ---
    lines.append("PER-SESSION BREAKDOWN")
    lines.append("-" * 72)
    lines.append(
        f"  {'Session':<24} {'GT':>4} {'Pred':>4} {'TP':>4} {'FP':>4} {'FN':>4}  {'P':>5} {'R':>5} {'F1':>5}"
    )
    lines.append("  " + "-" * 68)

    for sr in report.sessions:
        lines.append(
            f"  {sr.session_id:<24} {sr.gt_count:>4} {sr.pred_count:>4} "
            f"{sr.true_positives:>4} {sr.false_positives:>4} {sr.false_negatives:>4}  "
            f"{sr.precision:>5.2f} {sr.recall:>5.2f} {sr.f1:>5.2f}"
        )
    lines.append("")

    # --- Verbose: show individual matches and errors ---
    if verbose:
        lines.append("DETAILED MATCHES")
        lines.append("=" * 72)

        for sr in report.sessions:
            gt_data = ground_truth.get(sr.session_id, {})
            pred_data = predictions.get(sr.session_id, {})
            gt_commitments = gt_data.get("commitments", [])
            pred_commitments = pred_data.get("commitments", [])

            gt_list = [Commitment.from_dict(c) for c in gt_commitments]
            pred_list = [Commitment.from_dict(c) for c in pred_commitments]

            lines.append(f"\n--- {sr.session_id} ---")

            # Matched pairs
            for match in sr.matches:
                if match.pred_index is not None:
                    gt_c = gt_list[match.gt_index]
                    pred_c = pred_list[match.pred_index]
                    lines.append(f"\n  MATCH (sim={match.similarity:.2f}):")
                    lines.append(
                        f"    GT:   [{gt_c.direction}] {gt_c.who} -> {gt_c.to_whom}: {gt_c.text}"
                    )
                    lines.append(
                        f"    Pred: [{pred_c.direction}] {pred_c.who} -> {pred_c.to_whom}: {pred_c.text}"
                    )

                    field_status = []
                    if not match.direction_match:
                        field_status.append(
                            f"direction: GT={gt_c.direction} vs Pred={pred_c.direction}"
                        )
                    if not match.who_match:
                        field_status.append(f"who: GT={gt_c.who} vs Pred={pred_c.who}")
                    if not match.to_whom_match:
                        field_status.append(
                            f"to_whom: GT={gt_c.to_whom} vs Pred={pred_c.to_whom}"
                        )
                    if not match.deadline_match:
                        field_status.append(
                            f"deadline: GT={gt_c.deadline} vs Pred={pred_c.deadline}"
                        )

                    if field_status:
                        lines.append(f"    FIELD ERRORS: {'; '.join(field_status)}")
                else:
                    gt_c = gt_list[match.gt_index]
                    lines.append(f"\n  MISS (FN):")
                    lines.append(
                        f"    GT: [{gt_c.direction}] {gt_c.who} -> {gt_c.to_whom}: {gt_c.text}"
                    )
                    if gt_c.quote:
                        lines.append(f'    Quote: "{gt_c.quote[:100]}"')

            # False positives
            for pred_idx in sr.unmatched_preds:
                pred_c = pred_list[pred_idx]
                lines.append(f"\n  FALSE POSITIVE:")
                lines.append(
                    f"    Pred: [{pred_c.direction}] {pred_c.who} -> {pred_c.to_whom}: {pred_c.text}"
                )
                if pred_c.quote:
                    lines.append(f'    Quote: "{pred_c.quote[:100]}"')

        lines.append("")

    # --- Overall verdict ---
    lines.append("=" * 72)
    all_pass = (
        p >= THRESHOLDS["precision"]
        and r >= THRESHOLDS["recall"]
        and f >= THRESHOLDS["f1"]
    )
    if report.total_gt == 0:
        lines.append(
            "  VERDICT: NO GROUND TRUTH DATA -- annotate ground_truth.json first"
        )
    elif all_pass:
        lines.append(
            "  VERDICT: PASS -- commitment extraction meets quality thresholds"
        )
    else:
        lines.append("  VERDICT: FAIL -- commitment extraction needs improvement")
        if p < THRESHOLDS["precision"]:
            lines.append(
                f"    - Precision {p:.3f} < {THRESHOLDS['precision']} (too many false positives)"
            )
        if r < THRESHOLDS["recall"]:
            lines.append(
                f"    - Recall {r:.3f} < {THRESHOLDS['recall']} (too many missed commitments)"
            )
    lines.append("=" * 72)

    return "\n".join(lines)


def report_to_dict(report: EvalReport) -> dict:
    """Convert EvalReport to a JSON-serializable dict."""
    return {
        "detection": {
            "ground_truth_count": report.total_gt,
            "prediction_count": report.total_pred,
            "true_positives": report.total_tp,
            "false_positives": report.total_fp,
            "false_negatives": report.total_fn,
            "precision": round(report.precision, 4),
            "recall": round(report.recall, 4),
            "f1": round(report.f1, 4),
        },
        "field_accuracy": {
            "direction": round(report.direction_accuracy, 4)
            if report.direction_total > 0
            else None,
            "who": round(report.who_accuracy, 4) if report.who_total > 0 else None,
            "to_whom": round(report.to_whom_accuracy, 4)
            if report.to_whom_total > 0
            else None,
            "deadline": round(report.deadline_accuracy, 4)
            if report.deadline_total > 0
            else None,
        },
        "thresholds": THRESHOLDS,
        "sessions": [
            {
                "session_id": sr.session_id,
                "gt_count": sr.gt_count,
                "pred_count": sr.pred_count,
                "tp": sr.true_positives,
                "fp": sr.false_positives,
                "fn": sr.false_negatives,
                "precision": round(sr.precision, 4),
                "recall": round(sr.recall, 4),
                "f1": round(sr.f1, 4),
            }
            for sr in report.sessions
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_json(path: str) -> dict:
    """Load and validate a JSON file."""
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(p) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        print(f"Error: expected JSON object in {path}", file=sys.stderr)
        sys.exit(1)
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate commitment extraction quality"
    )
    parser.add_argument(
        "ground_truth",
        help="Path to ground truth JSON file",
    )
    parser.add_argument(
        "predictions",
        help="Path to predictions JSON file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed per-commitment matching",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Save results as JSON to this file",
    )
    args = parser.parse_args()

    ground_truth = load_json(args.ground_truth)
    predictions = load_json(args.predictions)

    report = evaluate(ground_truth, predictions)

    # Print formatted report
    print(format_report(report, ground_truth, predictions, verbose=args.verbose))

    # Save JSON output if requested
    if args.output:
        result_dict = report_to_dict(report)
        with open(args.output, "w") as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
