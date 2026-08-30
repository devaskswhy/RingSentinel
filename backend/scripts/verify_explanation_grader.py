"""Prove the case-file grader actually catches what it claims to catch.

    docker compose exec backend python -m scripts.verify_explanation_grader

BLINDSPOTS.md reports a pass rate over real case files. That number is only
worth reading if the grader is capable of failing something - a checker that
silently matches nothing reports a perfect score and means nothing by it.

This feeds it one honest case file and four deliberately broken ones, and
requires the honest one to pass and all four to be caught. It exercises the
grader alone: no database, no model call, no network.

That is not hypothetical. The tokeniser shipped with its word boundaries
replaced by literal backspace bytes, so it matched no digits at all and a case
file claiming 9,471 transactions passed the grounding check cleanly. Nothing in
the pass rate revealed it. This script did.
"""

from __future__ import annotations

import sys

from detection.config import DetectorConfig
from evaluation.explanation_quality import grade_case_file

OK = "[ok]"
KNOWN_REF = "inst_robust_abc123def456ab"

#: What the cluster actually is. Every number a case file may legitimately cite
#: has to trace back to here.
EVIDENCE = {
    "size": 4,
    "shared_attributes": [
        {
            "type": "instrument",
            "external_ref": KNOWN_REF,
            "customer_count": 4,
            "observations": 27,
        }
    ],
    "timing": {"median_gap_seconds": 1204, "coefficient_of_variation": 0.91},
}


def row(
    summary: str,
    *,
    score: float = 0.62,
    action: str = "likely_ring",
    confidence_note: str = "The pattern is consistent across all four accounts.",
) -> dict:
    return {
        "cluster_id": "00000000-0000-0000-0000-000000000000",
        "summary": summary,
        "confidence_note": confidence_note,
        "suggested_action": action,
        "key_signals": [],
        "caveats": [],
        "score": score,
        "evidence_json": EVIDENCE,
    }


#: (label, row, must_be_caught, which criterion should fail)
CHECKS = [
    (
        "honest baseline",
        row(
            f"Four accounts share one payment instrument ({KNOWN_REF}), which "
            f"carried 27 orders between them."
        ),
        False,
        None,
    ),
    (
        "fabricated entity ref",
        row(
            "Four accounts share one payment instrument "
            "(inst_robust_000000000000ff), which carried 27 orders."
        ),
        True,
        "grounded",
    ),
    (
        "fabricated count",
        row(
            f"The shared card ({KNOWN_REF}) was used across 9471 separate "
            f"transactions by these accounts."
        ),
        True,
        "grounded",
    ),
    (
        "overclaims on an ambiguous cluster",
        row(
            f"Four accounts share one instrument ({KNOWN_REF}). This "
            f"conclusively proves coordinated abuse.",
            score=0.35,
        ),
        True,
        "calibrated",
    ),
    (
        "action contradicts the score",
        row(
            f"Four accounts share one instrument ({KNOWN_REF}) across 27 orders.",
            action="likely_false_positive",
        ),
        True,
        "action_fits",
    ),
]


def main() -> int:
    config = DetectorConfig()
    failures: list[str] = []

    print("Grader self-test - one honest case file, four broken ones.")
    print("=" * 70)
    for label, case, must_be_caught, criterion in CHECKS:
        scored = grade_case_file(case, config, context={})
        caught = not scored.passed

        if caught != must_be_caught:
            failures.append(
                f"{label}: expected {'a catch' if must_be_caught else 'a pass'}, "
                f"got {'a catch' if caught else 'a pass'}"
            )
        elif criterion and getattr(scored, criterion):
            # Caught, but by the wrong criterion - the check that was supposed
            # to fire did not, and something else covered for it.
            failures.append(
                f"{label}: caught, but {criterion!r} passed - the wrong check fired"
            )

        mark = "CAUGHT" if caught else "PASS  "
        detail = f" - {scored.findings[0]}" if scored.findings else ""
        print(f"  {mark}  {label}{detail}")

    print("=" * 70)
    if failures:
        print("\nThe grader is not trustworthy:")
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print(
            "\nA pass rate produced by this grader would not mean anything. "
            "Fix the grader before reporting one."
        )
        return 1

    print(f"\n{OK} the honest case file passes and all four defects are caught,")
    print(f"{OK} each by the criterion meant to catch it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
