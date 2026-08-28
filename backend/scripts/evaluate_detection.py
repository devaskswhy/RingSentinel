"""Measure detector performance against ground truth. EVALUATION ONLY.

    docker compose exec backend python -m scripts.evaluate_detection

Defaults to the TUNING split. This script reads `is_synthetic_ring_id`, which is
exactly why it lives outside `detection/` - the detector itself never sees a
label. See `evaluation/splits.py` for the full argument.

Running this against the held-out split before Phase 6 defeats the purpose of
having one, so it warns loudly when asked to.
"""

from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from detection.config import DetectorConfig
from detection.pipeline import run_detection
from evaluation.report import MIN_ACCOUNT_RECALL, evaluate
from evaluation.splits import (
    SPLIT_ALL,
    SPLIT_HOLDOUT,
    SPLIT_TUNING,
    load_ring_truth,
    normal_customer_ids,
    transactions_to_exclude,
)

OK = "[ok]"
MISS = "[MISS]"
WARN = "[warn]"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the detector.")
    parser.add_argument(
        "--split", choices=(SPLIT_TUNING, SPLIT_HOLDOUT, SPLIT_ALL), default=SPLIT_TUNING
    )
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="try a range of thresholds and show the recall/false-flag trade-off",
    )
    args = parser.parse_args()

    if args.split == SPLIT_HOLDOUT:
        print(f"{WARN} EVALUATING THE HELD-OUT SPLIT.")
        print("       Only do this once, in Phase 6. Tuning against these")
        print("       rings destroys the only unbiased estimate available.\n")

    overrides = {}
    if args.threshold is not None:
        overrides["score_threshold"] = args.threshold
    config = DetectorConfig(**overrides)

    db = SessionLocal()
    try:
        excluded = transactions_to_exclude(db, args.split)
        rings = load_ring_truth(db, args.split if args.split != SPLIT_ALL else None)
        normals = normal_customer_ids(db)

        run = run_detection(
            db, config=config, exclude_transaction_ids=excluded, persist=False
        )
        db.rollback()

        report = evaluate(run.flagged, rings, normals)

        print(f"Detector evaluation - split={args.split}, "
              f"threshold={config.score_threshold}, version={config.version}\n")

        # ---- per-ring recall ---------------------------------------------
        print("Seeded rings:")
        print(f"  {'ring':<9}{'pattern':<15}{'cadence':<9}{'accts':>6}{'found':>7}"
              f"{'score':>8}  {'detected cadence':<16}result")
        print("  " + "-" * 78)
        for outcome in report.rings:
            marker = OK if outcome.detected else MISS
            score = f"{outcome.score:.3f}" if outcome.detected else "-"
            print(
                f"  {outcome.truth.ring:<9}{outcome.truth.pattern:<15}"
                f"{outcome.truth.cadence:<9}{outcome.accounts_total:>6}"
                f"{outcome.accounts_found:>7}{score:>8}  "
                f"{outcome.cadence:<16}{marker}"
            )

        # ---- cadence accuracy --------------------------------------------
        detected = [r for r in report.rings if r.detected]
        cadence_right = sum(
            1 for r in detected if r.cadence.startswith(r.truth.cadence)
        )

        # ---- flagged cluster purity --------------------------------------
        print("\nFlagged clusters:")
        print(f"  {'#':<3}{'size':>5}{'score':>8}{'ring accts':>12}{'purity':>8}  "
              f"{'matched':<12}verdict")
        print("  " + "-" * 78)
        for cluster in report.clusters:
            verdict = "FALSE FLAG" if cluster.is_false_flag else "true positive"
            matched = ",".join(c.replace("ring_", "") for c in cluster.matched_rings) or "-"
            print(
                f"  {cluster.index + 1:<3}{cluster.size:>5}{cluster.score:>8.3f}"
                f"{cluster.ring_accounts:>12}{cluster.purity:>8.0%}  "
                f"{matched:<12}{verdict}"
            )

        # ---- headline numbers --------------------------------------------
        print("\n" + "=" * 62)
        print("RESULTS")
        print("=" * 62)
        print(f"  rings detected        : {report.detected}/{len(report.rings)} "
              f"({report.ring_recall:.0%} recall, >= {MIN_ACCOUNT_RECALL:.0%} of "
              f"a ring's accounts required)")
        print(f"  cadence correct       : {cadence_right}/{len(detected)} of detected rings")
        print(f"  clusters flagged      : {len(report.clusters)}")
        print(f"  false flags           : {report.false_flags} "
              f"(precision {report.precision:.0%})")
        print(f"  normal accounts       : {report.normal_accounts_flagged} of "
              f"{report.normal_accounts_total} swept into a flagged cluster "
              f"({report.normal_flag_rate:.1%})")

        # ---- threshold sweep ---------------------------------------------
        if args.sweep:
            print("\nThreshold sweep:")
            print(f"  {'thresh':>7}{'flagged':>9}{'rings':>7}{'recall':>8}"
                  f"{'false':>7}{'precision':>11}")
            print("  " + "-" * 49)
            for step in range(20, 75, 5):
                t = step / 100
                cfg = DetectorConfig(score_threshold=t)
                flagged = [c for c in run.scored if c.score >= t]
                rep = evaluate(flagged, rings, normals)
                print(
                    f"  {t:>7.2f}{len(flagged):>9}{rep.detected:>7}"
                    f"{rep.ring_recall:>8.0%}{rep.false_flags:>7}"
                    f"{rep.precision:>11.0%}"
                )

        missed = [r for r in report.rings if not r.detected]
        if missed:
            print(f"\n{MISS} missed rings:")
            for outcome in missed:
                print(f"   - {outcome.truth.ring} ({outcome.truth.pattern}, "
                      f"{outcome.truth.cadence}, {outcome.accounts_total} accounts): "
                      f"best cluster held {outcome.accounts_found} of them")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
