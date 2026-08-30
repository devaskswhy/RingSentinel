"""Run the detector over real IEEE-CIS payment data. Everything rolls back.

    docker compose exec backend python -m scripts.evaluate_ieee --limit 100000

The seeded corpus is separable by construction — its busiest benign attribute
is shared by 3 accounts. This is 590,540 real transactions where a single card
carries 14,112. It is the environment the seeded corpus is not.

Reports LIFT, never precision or recall. The dataset labels transactions as
fraudulent, not accounts as ring members, so there is no ring to recall and any
recall figure would answer a different question than the seeded corpus does.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import text

from app.db import SessionLocal
from detection.config import DetectorConfig
from detection.pipeline import run_detection
from evaluation.ieee import (
    TRANSACTIONS_CSV,
    insert_corpus,
    load_corpus,
    measure_lift,
)

OK = "[ok]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the detector on real IEEE-CIS data. Rolls back."
    )
    parser.add_argument(
        "--limit", type=int, default=100_000,
        help="Transactions to read (0 = all 590,540). Default 100,000.",
    )
    args = parser.parse_args()

    if not TRANSACTIONS_CSV.exists():
        print(f"Not found: {TRANSACTIONS_CSV}")
        print("See backend/data/README.md for what to download.")
        return 2

    config = DetectorConfig()
    db = SessionLocal()
    try:
        # Everything already in the database is out of scope. The detector is
        # never told what a scope is — it just receives ids to exclude.
        existing = {
            r[0] for r in db.execute(text("SELECT id FROM transactions")).all()
        }
        print(f"Excluding {len(existing):,} existing transactions (the seeded corpus).")

        t0 = time.monotonic()
        corpus = load_corpus(args.limit or None)
        print(
            f"Read {len(corpus.rows):,} rows in {time.monotonic() - t0:.1f}s "
            f"({corpus.skipped_no_account:,} skipped: no card1/addr1)"
        )
        print(
            f"  fraud: {corpus.fraud:,}  base rate: {corpus.base_rate:.3%}"
        )

        t0 = time.monotonic()
        insert_corpus(db, corpus)
        print(f"Inserted in {time.monotonic() - t0:.1f}s")

        t0 = time.monotonic()
        run = run_detection(
            db, config=config, exclude_transaction_ids=existing,
            persist=False, scope_label="ieee",
        )
        print(f"Detection: {time.monotonic() - t0:.1f}s · "
              f"{len(run.scored):,} candidates · {len(run.flagged):,} flagged")

        base = corpus.base_rate
        flagged_accounts: set = set()
        for s in run.flagged:
            flagged_accounts |= set(s.candidate.customers)

        result = measure_lift(db, "RingSentinel", flagged_accounts, base)

        # Diagnostics, because "lift 1.0" on its own does not say WHY. If the
        # signals are saturated the number is explained by the scoring, not by
        # an absence of structure in the data.
        sizes = sorted((len(s.candidate.customers) for s in run.scored), reverse=True)
        def mean(f):
            vals = [f(s) for s in run.flagged]
            return sum(vals) / len(vals) if vals else 0.0

        print()
        print("=" * 74)
        print("  REAL DATA — IEEE-CIS Fraud Detection, 590,540 transactions")
        print("  Reporting LIFT. Not precision, not recall: this dataset labels")
        print("  transactions as fraudulent, not accounts as ring members.")
        print("=" * 74)
        print()
        print(f"  population base rate      {base:>10.2%}")
        print(f"  clusters flagged          {len(run.flagged):>10,}")
        print(f"  accounts in them          {result.accounts:>10,}")
        print(f"  their transactions        {result.transactions:>10,}")
        print(f"  of those, fraudulent      {result.fraud_transactions:>10,}")
        print(f"  flagged-cluster fraud rate{result.cluster_fraud_rate:>10.2%}")
        print()
        print(f"  LIFT                      {result.lift:>10.2f}x")
        print()
        print(f"  flagged {len(run.flagged)} of {len(run.scored)} candidates "
              f"({len(run.flagged)/max(1,len(run.scored)):.0%})")
        print(f"  cluster sizes (accounts)  largest {sizes[:5] if sizes else []}")
        print("  mean signal values on flagged clusters:")
        print(f"    attribute reuse         {mean(lambda s: s.attribute_reuse):>10.2f}")
        print(f"    timing regularity       {mean(lambda s: s.timing_regularity):>10.2f}")
        print(f"    concentration           {mean(lambda s: s.concentration):>10.2f}")
        print(f"    account shallowness     {mean(lambda s: s.account_shallowness):>10.2f}")
        print()
        if result.lift >= 2:
            print("  The graph carries signal on data this project did not generate.")
        elif result.lift >= 1.2:
            print("  Modest lift. Real, but far below the seeded-corpus result —")
            print("  which is the honest shape of the difference between the two.")
        else:
            print("  ⚠ No meaningful lift. On real data with dense benign sharing,")
            print("  this approach does not separate fraud from the base rate, and")
            print("  that is the finding. It is reported rather than buried.")
        print("=" * 74)
        print()
        print("  ⚠ The account is a PROXY: card1 + addr1. IEEE-CIS has no customer")
        print("    column, so every account here is constructed, not observed.")
        print(f"{OK} nothing persisted — the seeded corpus is unchanged")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
