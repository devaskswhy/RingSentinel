"""Run the fraud-ring detector and print the flagged clusters.

    docker compose exec backend python -m scripts.detect --help

Defaults to the TUNING split (seeded rings 1-8). The held-out rings 9-12 stay
excluded unless explicitly asked for, and asking for them prints a warning -
they are reserved for Phase 6 and looking at them while tuning invalidates the
evaluation.

No LLM calls happen here. This is deterministic graph and statistics work.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal
from detection.config import DetectorConfig
from detection.pipeline import run_detection
from evaluation.splits import SPLIT_ALL, SPLIT_HOLDOUT, SPLIT_TUNING, transactions_to_exclude

OK = "[ok]"
WARN = "[warn]"

CADENCE_DISPLAY = {
    "agent_like": "agent-like",
    "human_like": "human-like",
    "inconclusive": "inconclusive",
}


def _bar(score: float, width: int = 12) -> str:
    filled = int(round(score * width))
    return "#" * filled + "-" * (width - filled)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect coordinated fraud rings in the entity graph."
    )
    parser.add_argument(
        "--split",
        choices=(SPLIT_TUNING, SPLIT_HOLDOUT, SPLIT_ALL),
        default=SPLIT_TUNING,
        help="which evaluation split to run against (default: tuning)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="override the score threshold for flagging",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=None,
        help="override the minimum number of accounts per cluster",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="score and print but write nothing to the database",
    )
    parser.add_argument(
        "--show-below",
        action="store_true",
        help="also list candidate clusters that scored below the threshold",
    )
    parser.add_argument(
        "--explain",
        type=int,
        default=None,
        metavar="N",
        help="print the full evidence JSON for the Nth flagged cluster (1-based)",
    )
    args = parser.parse_args()

    overrides = {}
    if args.threshold is not None:
        overrides["score_threshold"] = args.threshold
    if args.min_size is not None:
        overrides["min_cluster_customers"] = args.min_size
    config = DetectorConfig(**overrides)

    if args.split == SPLIT_HOLDOUT:
        print(f"{WARN} Running against the HELD-OUT split (rings 9-12).")
        print("       These are reserved for Phase 6 evaluation. Tuning any")
        print("       threshold against them invalidates the held-out result.\n")

    db = SessionLocal()
    try:
        excluded = transactions_to_exclude(db, args.split)

        print("RingSentinel detector")
        print(f"  version        : {config.version}")
        print(f"  split          : {args.split}")
        print(f"  threshold      : {config.score_threshold}")
        print(f"  min accounts   : {config.min_cluster_customers}")
        if excluded:
            print(f"  excluded txns  : {len(excluded)} (out-of-split, opaque to detector)")
        print()

        run = run_detection(
            db,
            config=config,
            exclude_transaction_ids=excluded,
            persist=not args.no_persist,
        )

        if not args.no_persist:
            db.commit()
        else:
            db.rollback()

        # ---- graph summary ------------------------------------------------
        b = run.bundle
        print("Graph:")
        print(f"  nodes {b.graph.number_of_nodes()}  edges {b.graph.number_of_edges()}"
              f"  accounts {b.total_customers}  transactions in scope {b.total_transactions}")
        if b.dropped_hubs:
            print(f"  {len(b.dropped_hubs)} hub attribute(s) dropped as infrastructure:")
            for hub in b.dropped_hubs[:5]:
                print(f"    - {hub['type']} {hub['external_ref'][:20]}... : {hub['reason']}")
        print(f"  baseline rhythm: median gap {run.baseline.median_gap_seconds:.1f}s, "
              f"CV {run.baseline.median_coefficient_of_variation:.2f} "
              f"across {run.baseline.customers_measured} accounts")
        print()

        # ---- the table ----------------------------------------------------
        print(f"Flagged clusters ({len(run.flagged)} of {run.candidates} candidates):\n")
        if not run.flagged:
            print("  none above threshold")
        else:
            header = (
                f"  {'#':<3}{'cluster id':<14}{'size':>5}  {'score':<20}"
                f"{'cadence':<14}top shared attributes"
            )
            print(header)
            print("  " + "-" * (len(header) + 20))
            for index, item in enumerate(run.flagged, start=1):
                cid = run.persisted_ids.get(index - 1)
                cid_display = str(cid)[:12] if cid else "(not saved)"
                attrs = ", ".join(
                    f"{a.attribute_type}x{a.customer_count}" for a in item.top_attributes(3)
                )
                print(
                    f"  {index:<3}{cid_display:<14}{item.size:>5}  "
                    f"{item.score:.3f} {_bar(item.score)}  "
                    f"{CADENCE_DISPLAY[item.cadence.classification]:<14}{attrs}"
                )

            print("\n  What drove each flag:")
            for index, item in enumerate(run.flagged, start=1):
                print(f"    {index}. {item.headline()}")
                print(
                    f"       reuse {item.attribute_reuse:.2f} | "
                    f"timing {item.timing_regularity:.2f} | "
                    f"concentration {item.concentration:.2f} | "
                    f"shallow {item.account_shallowness:.2f}"
                    f" ({item.shallow_account_count}/{item.size} accts)"
                    f"  ->  {item.score:.3f}"
                )
                print(f"       cadence: {item.cadence.reason}")

        # ---- optional extras ----------------------------------------------
        if args.show_below:
            below = run.below_threshold()
            print(f"\nBelow threshold ({len(below)}):")
            for item in below[:20]:
                attrs = ", ".join(
                    f"{a.attribute_type}x{a.customer_count}" for a in item.top_attributes(2)
                ) or "no shared attributes"
                print(f"  {item.score:.3f}  size {item.size:<3}  {attrs}")

        if args.explain:
            idx = args.explain - 1
            if 0 <= idx < len(run.flagged):
                print(f"\nFull evidence for flagged cluster #{args.explain}:")
                print(json.dumps(run.flagged[idx].to_evidence(config), indent=2))
            else:
                print(f"\n{WARN} no flagged cluster #{args.explain}")

        # ---- persistence summary -------------------------------------------
        print()
        if args.no_persist:
            print(f"{OK} dry run - nothing written.")
        else:
            print(f"{OK} wrote {len(run.flagged)} cluster(s), status='pending'.")
            print(f"     replaced {run.deleted_pending} previously-pending cluster(s); "
                  f"preserved {run.preserved_reviewed} already reviewed by a human.")
        print(f"     {run.elapsed_seconds:.2f}s")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
