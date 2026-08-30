"""Measure what each of the four signals actually contributes.

    docker compose exec backend python -m scripts.ablate_signals
    docker compose exec backend python -m scripts.ablate_signals --split holdout

Reads ground truth, so it sits on the evaluation side of the boundary and is
never imported by `detection/`. Nothing is persisted.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.db import SessionLocal
from detection.baseline import population_baseline
from detection.clustering import find_clusters
from detection.config import DetectorConfig
from detection.graph import load_graph
from evaluation.ablation import render, run_ablation
from evaluation.splits import (
    load_ring_truth,
    normal_customer_ids,
    transactions_to_exclude,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drop each signal in turn and report what it cost."
    )
    parser.add_argument(
        "--split", choices=["tuning", "holdout", "all"], default="all"
    )
    parser.add_argument(
        "--ieee", type=int, default=0, metavar="N",
        help="Also ablate against N rows of real IEEE-CIS data, scored by "
             "top-decile ranking lift. The seeded corpus cannot measure what "
             "the behavioural signals do; this can.",
    )
    args = parser.parse_args()

    config = DetectorConfig()
    db = SessionLocal()
    try:
        exclude = (
            transactions_to_exclude(db, args.split) if args.split != "all" else set()
        )
        # Build the graph and candidates ONCE. Neither depends on the weights,
        # so rescoring the same candidates isolates the weighting exactly.
        bundle = load_graph(db, config, exclude)
        baseline = population_baseline(bundle.customer_timestamps, config)
        candidates = find_clusters(bundle, config)

        rings = load_ring_truth(db, None if args.split == "all" else args.split)
        normals = normal_customer_ids(db)

        rows = run_ablation(candidates, bundle, baseline, rings, normals, config)
        print()
        print(render(rows, args.split, len(candidates)))
        if args.ieee:
            from evaluation.ablation import ablate_lift
            from evaluation.ieee import insert_corpus, load_corpus, measure_lift

            existing = {r[0] for r in db.execute(text("SELECT id FROM transactions")).all()}
            corpus = load_corpus(args.ieee)
            insert_corpus(db, corpus)
            base = corpus.base_rate
            ib = load_graph(db, config, existing)
            ibl = population_baseline(ib.customer_timestamps, config)
            icands = find_clusters(ib, config)

            def top_decile_lift(scored):
                ranked = sorted(scored, key=lambda s: -s.score)
                k = max(1, int(len(ranked) * 0.10))
                accts: set = set()
                for s in ranked[:k]:
                    accts |= set(s.candidate.customers)
                return measure_lift(db, "x", accts, base).lift

            print()
            print("=" * 78)
            print(f"  THE SAME ABLATION ON REAL DATA — {len(corpus.rows):,} IEEE-CIS rows")
            print(f"  Scored by top-decile lift against a {base:.2%} base rate.")
            print("=" * 78)
            print()
            results = ablate_lift(icands, ib, ibl, top_decile_lift, config)
            full_lift = results[0][1]
            for label, value in results:
                delta = "" if label.startswith("all") else f"{value - full_lift:+.2f}"
                print(f"    {label:<30}{value:>6.2f}x{delta:>9}")
            print()
            print("  Read this against the table above before concluding anything")
            print("  about which signals are dead weight.")
            print("=" * 78)

        print()
        print("  Nothing persisted; this is a measurement, not a detection run.")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
