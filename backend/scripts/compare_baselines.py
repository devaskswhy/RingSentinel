"""Measure the four-signal scorer against rules that cost nothing.

    docker compose exec backend python -m scripts.compare_baselines
    docker compose exec backend python -m scripts.compare_baselines --split holdout

Reads ground truth, so it lives on the evaluation side of the boundary and is
never imported by `detection/`.
"""

from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from detection.config import DetectorConfig
from detection.pipeline import run_detection
from evaluation.baselines import render, run_baselines
from evaluation.splits import (
    load_ring_truth,
    normal_customer_ids,
    transactions_to_exclude,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare the scorer against naive baselines on the same clusters."
    )
    parser.add_argument(
        "--split", choices=["tuning", "holdout", "all"], default="all",
        help="Which rings are in scope (default: all).",
    )
    args = parser.parse_args()

    config = DetectorConfig()
    db = SessionLocal()
    try:
        exclude = (
            transactions_to_exclude(db, args.split) if args.split != "all" else set()
        )
        run = run_detection(
            db, config=config, exclude_transaction_ids=exclude,
            persist=False, scope_label=args.split,
        )
        rings = load_ring_truth(db, None if args.split == "all" else args.split)
        normals = normal_customer_ids(db)

        results = run_baselines(run.scored, rings, normals, config)
        print()
        print(render(results, candidates=len(run.scored)))
        print(f"\n  split: {args.split} · {len(rings)} seeded rings in scope")
        print("  Nothing was persisted; this is a measurement, not a detection run.")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
