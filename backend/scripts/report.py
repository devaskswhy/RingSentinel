"""Plain-text evaluation summary, suitable for pasting into an architecture doc.

    docker compose exec backend python -m scripts.report            # held-out
    docker compose exec backend python -m scripts.report --store    # and record it

Writes nothing unless `--store` is passed, in which case the snapshot goes into
`evaluation_runs` so /metrics can serve exactly what was reported here rather
than recomputing and possibly disagreeing.

The "where it is weakest" section is written from the measured numbers, not
composed by hand. If the detector performs badly this script says so.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from app.db import SessionLocal
from evaluation.cost import assumptions
from evaluation.metrics import compute_metrics, store_metrics
from evaluation.splits import SPLIT_ALL, SPLIT_HOLDOUT, SPLIT_TUNING

RULE = "=" * 72
THIN = "-" * 72


def wrap(text_body: str, indent: str = "  ") -> str:
    return "\n".join(
        textwrap.fill(line, width=72, initial_indent=indent, subsequent_indent=indent)
        for line in text_body.strip().split("\n")
    )


def weakest_points(m) -> list[str]:
    """Where the detector is weakest, derived from the numbers just measured."""
    points: list[str] = []

    if m.false_negatives:
        missed = [r for r in m.ring_rows if not r["detected"]]
        patterns = ", ".join(sorted({r["pattern"] for r in missed}))
        points.append(
            f"{m.false_negatives} of {m.rings_total} rings were missed entirely "
            f"({patterns}). Those patterns are where the detector is blind, and "
            "no threshold change fixes a ring that never formed a cluster."
        )

    if m.needs_review:
        band_scores = sorted(e.score for e in m.needs_review)
        points.append(
            f"{len(m.needs_review)} of {m.clusters_flagged} flagged clusters fall "
            f"in the ambiguous band [{m.score_threshold}, "
            f"{m.confident_threshold}), scoring "
            f"{band_scores[0]:.3f}-{band_scores[-1]:.3f}. Whether these are found "
            "at all depends on where the threshold sits rather than on the "
            "strength of the evidence, so they are reported as exceptions."
        )

    human_rings = [r for r in m.ring_rows if r["cadence"] == "human" and r["detected"]]
    agent_rings = [r for r in m.ring_rows if r["cadence"] == "agent" and r["detected"]]
    if human_rings and agent_rings:
        human_avg = sum(r["score"] or 0 for r in human_rings) / len(human_rings)
        agent_avg = sum(r["score"] or 0 for r in agent_rings) / len(agent_rings)
        if agent_avg - human_avg > 0.1:
            points.append(
                f"Human-cadence rings score materially lower than agent-cadence "
                f"ones ({human_avg:.3f} vs {agent_avg:.3f} on average). The timing "
                "signal contributes almost nothing when a ring is operated by "
                "people, so those rings rest on attribute reuse alone and sit "
                "closer to the threshold."
            )

    address_only = [
        e for e in m.needs_review if "address" in e.headline and "instrument" not in e.headline
    ]
    if address_only:
        points.append(
            f"{len(address_only)} exception(s) rest primarily on a shared address, "
            "which is weighted at 0.40 precisely because households share "
            "addresses. That weighting is deliberate, but it means address-only "
            "rings are the hardest class for this detector to justify flagging."
        )

    if not points:
        points.append(
            "No systematic weakness is visible in this run, which most likely "
            "reflects the corpus rather than the detector - see the caveat above."
        )
    return points


def render(m, split: str) -> str:
    out: list[str] = []
    a = out.append

    a(RULE)
    a("RingSentinel — detector evaluation")
    a(RULE)
    a(f"  split            : {split}")
    a(f"  detector version : {m.detector_version}")
    a(f"  flag threshold   : {m.score_threshold}")
    a(f"  confident above  : {m.confident_threshold}")
    a(f"  run at           : {m.run_at.isoformat(timespec='seconds')}")
    a("")

    # ---- composition ----------------------------------------------------
    a("HELD-OUT SET COMPOSITION" if split == SPLIT_HOLDOUT else "SET COMPOSITION")
    a(THIN)
    a(f"  {'ring':<10}{'pattern':<16}{'cadence':<9}{'accts':>6}{'found':>7}{'score':>9}")
    for row in m.ring_rows:
        score = f"{row['score']:.3f}" if row["score"] is not None else "—"
        mark = "" if row["detected"] else "   MISSED"
        a(
            f"  {row['ring']:<10}{row['pattern']:<16}{row['cadence']:<9}"
            f"{row['accounts']:>6}{row['accounts_found']:>7}{score:>9}{mark}"
        )
    a("")

    # ---- headline -------------------------------------------------------
    a("HEADLINE NUMBERS")
    a(THIN)
    a(f"  Precision  {m.precision:>7.1%}   {m.true_positives} of "
      f"{m.true_positives + m.false_positives} flagged clusters were real rings")
    a(f"  Recall     {m.recall:>7.1%}   {m.rings_detected} of {m.rings_total} "
      f"seeded rings were found")
    a(f"  FP cost    INR {m.cost.total_inr:>7,.0f}   "
      f"{m.false_positives} false positive(s) x "
      f"INR {m.cost.review_cost_per_fp_inr:,.0f} review time")
    a("")
    a(wrap(
        "Precision is counted in clusters (analyst time is spent per cluster). "
        "Recall is counted in rings (the question is how many real rings exist "
        "that we found). The two use different units on purpose; a single F1 "
        "would be tidier and mean less."
    ))
    a("")

    # ---- exceptions -----------------------------------------------------
    a(f"EXCEPTIONS — {len(m.needs_review)} cluster(s) marked needs_review")
    a(THIN)
    if m.needs_review:
        for e in m.needs_review:
            a(f"  score {e.score:.3f}  {e.size} accounts  {e.cadence}")
            a(f"    {e.headline[:66]}")
        a("")
        a(wrap(
            f"These sit in [{m.score_threshold}, {m.confident_threshold}) and are "
            "flagged but not asserted. The detector is reporting low confidence "
            "rather than forcing a binary it cannot justify. They still reach a "
            "human; they are simply not counted as confident findings."
        ))
    else:
        a("  none — every flagged cluster scored above the confidence threshold")
    a("")

    # ---- cadence and sweep ----------------------------------------------
    a("SECONDARY")
    a(THIN)
    a(f"  cadence classified correctly : {m.cadence_correct}/{m.rings_detected}")
    a(f"  clean accounts swept into a flag : {m.normal_accounts_swept_in} of "
      f"{m.normal_accounts_total}")
    a("")

    # ---- weakest --------------------------------------------------------
    a("WHERE IT IS WEAKEST")
    a(THIN)
    for point in weakest_points(m):
        a(wrap(point))
        a("")

    # ---- caveat ---------------------------------------------------------
    a("CAVEAT")
    a(THIN)
    a(wrap(
        "This is a synthetic corpus generated by this project, and it is "
        "separable by construction: ring identities are salted per ring so no "
        "two seeded rings share an entity, and each background account owns its "
        "device, address, and instrument. Real merchant data is messier — rings "
        "bridge into one another, benign sharing is dense, and attribute hygiene "
        "is poor. These numbers show the detector does what it was designed to "
        "do on data of this shape and did not overfit the tuning split. They are "
        "not a production accuracy claim."
    ))
    a("")

    a("COST MODEL ASSUMPTIONS (estimates, not measurements)")
    a(THIN)
    for key, value in assumptions().items():
        if key == "disclaimer":
            continue
        a(f"  {key:<38} {value}")
    a("")
    a(RULE)
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print an evaluation summary.")
    parser.add_argument(
        "--split", choices=(SPLIT_HOLDOUT, SPLIT_TUNING, SPLIT_ALL), default=SPLIT_HOLDOUT
    )
    parser.add_argument(
        "--store",
        action="store_true",
        help="record this snapshot so /metrics serves exactly these numbers",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        metrics = compute_metrics(db, args.split)
        print(render(metrics, args.split))

        if args.store:
            run_id = store_metrics(db, metrics)
            db.commit()
            print(f"[stored] evaluation_runs row {run_id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
