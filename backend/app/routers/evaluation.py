"""Scorecard for the review console. READS GROUND TRUTH - evaluation surface.

Lives under /eval and is named accordingly, because precision and recall are not
computable without labels. Detection code must never call this.

The scorecard has two halves, kept separate on purpose:

  detector_benchmark  needs ground truth, so it only means anything on the
                      synthetic corpus. On real merchant data this half would
                      simply be unavailable.
  review_operations   works anywhere. Queue progress, analyst effort, and how
                      often the human agreed with Claude - all derived from
                      review outcomes, no labels required.

Conflating the two would let a demo number masquerade as a production one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from evaluation.cost import build_cost_model, describe
from evaluation.metrics import compute_metrics, latest_stored

router = APIRouter(prefix="/eval", tags=["evaluation"])

#: Rough analyst minutes per cluster review. Used only to express review effort
#: in human terms; nothing depends on the exact figure.
MINUTES_PER_REVIEW = 12


def _scope_of_last_run(db: Session) -> str:
    """Which split the clusters currently in the queue came from."""
    scope = db.execute(
        text(
            "SELECT detail_json->>'scope_label' FROM audit_log "
            "WHERE action = 'detection_run' ORDER BY id DESC LIMIT 1"
        )
    ).scalar()
    return scope or "all"


@router.get("/scorecard")
def scorecard(db: Session = Depends(get_db)) -> dict:
    """Detector performance plus live review progress."""
    scope = _scope_of_last_run(db)

    # ---- ground truth, scoped to the split the queue was built from -------
    ring_rows = db.execute(
        text(
            """
            SELECT split_part(is_synthetic_ring_id, '|', 1) AS ring,
                   split_part(is_synthetic_ring_id, '|', 4) AS split,
                   array_agg(DISTINCT customer_entity_id)   AS customers
            FROM transactions
            WHERE is_synthetic_ring_id IS NOT NULL
            GROUP BY 1, 2
            """
        )
    ).mappings().all()

    rings = [
        r for r in ring_rows if scope == "all" or r["split"] == scope
    ]
    ring_accounts: dict[str, set[uuid.UUID]] = {
        r["ring"]: set(r["customers"]) for r in rings
    }
    all_ring_accounts: set[uuid.UUID] = set()
    for accounts in ring_accounts.values():
        all_ring_accounts |= accounts

    normal_total = db.execute(
        text(
            """
            SELECT count(*) FROM (
                SELECT customer_entity_id FROM transactions
                GROUP BY customer_entity_id
                HAVING count(*) FILTER (WHERE is_synthetic_ring_id IS NOT NULL) = 0
            ) t
            """
        )
    ).scalar_one()

    # ---- what is in the queue right now -----------------------------------
    cluster_rows = db.execute(
        text(
            """
            SELECT c.id, c.status::text AS status, c.score,
                   c.cadence::text AS cadence,
                   cf.suggested_action::text AS suggested_action,
                   array_remove(array_agg(
                       CASE WHEN e.type = 'customer' THEN e.id END
                   ), NULL) AS customers
            FROM clusters c
            LEFT JOIN cluster_members m ON m.cluster_id = c.id
            LEFT JOIN entities e ON e.id = m.entity_id
            LEFT JOIN LATERAL (
                SELECT suggested_action FROM case_files
                WHERE cluster_id = c.id ORDER BY generated_at DESC LIMIT 1
            ) cf ON TRUE
            GROUP BY c.id, c.status, c.score, c.cadence, cf.suggested_action
            """
        )
    ).mappings().all()

    detected_rings: set[str] = set()
    true_positives = 0
    false_flags = 0
    normal_swept: set[uuid.UUID] = set()
    wrong_dismissals: list[str] = []

    for row in cluster_rows:
        members = set(row["customers"] or [])
        hits = members & all_ring_accounts
        purity = len(hits) / len(members) if members else 0.0

        if purity >= 0.5:
            true_positives += 1
        else:
            false_flags += 1

        normal_swept |= members - all_ring_accounts

        for ring, accounts in ring_accounts.items():
            if accounts and len(members & accounts) / len(accounts) >= 0.5:
                detected_rings.add(ring)

        # A dismissal of something that really was a ring is the expensive
        # mistake - a missed ring, not just wasted time.
        if row["status"] == "dismissed" and purity >= 0.5:
            wrong_dismissals.append(str(row["id"]))

    status_counts = dict(
        db.execute(
            text("SELECT status::text, count(*) FROM clusters GROUP BY 1")
        ).all()
    )
    total_clusters = sum(status_counts.values())
    reviewed = total_clusters - status_counts.get("pending", 0) - status_counts.get(
        "needs_review", 0
    )

    # ---- "needs more data" exceptions --------------------------------------
    needs_more = [
        {
            "cluster_id": str(r["id"]),
            "score": r["score"],
            "reason": (
                "Claude recommended gathering more evidence"
                if r["suggested_action"] == "review_closer"
                else "timing was too ambiguous to classify"
            ),
        }
        for r in cluster_rows
        if r["suggested_action"] == "review_closer" or r["cadence"] == "inconclusive"
    ]

    # ---- did the human agree with Claude? ----------------------------------
    agreements = 0
    disagreements = 0
    for row in cluster_rows:
        if row["status"] == "pending" or row["suggested_action"] is None:
            continue
        claude_says_ring = row["suggested_action"] == "likely_ring"
        human_says_ring = row["status"] == "cleared"
        if claude_says_ring == human_says_ring:
            agreements += 1
        else:
            disagreements += 1

    ring_total = len(ring_accounts)
    flagged_total = len(cluster_rows)

    return {
        "scope": scope,
        "detector_benchmark": {
            "available": ring_total > 0,
            "note": (
                "Requires ground-truth labels, so this half is meaningful only on "
                "the synthetic corpus. It would be unavailable on real data."
            ),
            "rings_total": ring_total,
            "rings_detected": len(detected_rings),
            "recall": round(len(detected_rings) / ring_total, 4) if ring_total else 0.0,
            "clusters_flagged": flagged_total,
            "true_positives": true_positives,
            "false_flags": false_flags,
            "precision": round(true_positives / flagged_total, 4) if flagged_total else 0.0,
            "normal_accounts_total": normal_total,
            "normal_accounts_swept_in": len(normal_swept),
        },
        "review_operations": {
            "note": "Derived from review outcomes only. Works without labels.",
            "total": total_clusters,
            "pending": status_counts.get("pending", 0),
            "approved": status_counts.get("cleared", 0),
            "dismissed": status_counts.get("dismissed", 0),
            "needs_review": status_counts.get("needs_review", 0),
            "reviewed": reviewed,
            "reviewed_fraction": round(reviewed / total_clusters, 4) if total_clusters else 0.0,
        },
        "false_positive_cost": {
            "false_flags": false_flags,
            "dismissed_by_human": status_counts.get("dismissed", 0),
            "analyst_minutes_on_dismissed": status_counts.get("dismissed", 0)
            * MINUTES_PER_REVIEW,
            "minutes_per_review_assumed": MINUTES_PER_REVIEW,
            "dismissed_that_were_real_rings": len(wrong_dismissals),
            "note": (
                "A false flag costs analyst time. Dismissing a cluster that really "
                "was a ring is the expensive error - that is a missed ring, and it "
                "is counted separately."
            ),
        },
        "needs_more_data": {
            "count": len(needs_more),
            "note": (
                "Clusters where Claude asked for more evidence, or where the "
                "timing signal was too ambiguous to classify. These are "
                "exceptions, not failures."
            ),
            "clusters": needs_more[:20],
        },
        "claude_agreement": {
            "decided": agreements + disagreements,
            "agreed": agreements,
            "disagreed": disagreements,
            "rate": round(agreements / (agreements + disagreements), 4)
            if (agreements + disagreements)
            else None,
            "note": (
                "How often the human decision matched Claude's recommendation. "
                "Claude never decides; this only measures whether its advice "
                "was useful."
            ),
        },
    }



# ---------------------------------------------------------------------------
# GET /metrics — held-out precision, recall, cost, and exceptions
# ---------------------------------------------------------------------------

metrics_router = APIRouter(tags=["evaluation"])


@metrics_router.get("/metrics")
def metrics(
    split: str = "holdout",
    recompute: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Precision, recall, false-positive cost, and the exception list.

    Serves the stored snapshot from the last recorded evaluation run by default.
    Storing rather than always recomputing is the point: a number that has been
    reported should not silently change because someone edited a threshold
    afterwards. `?recompute=true` runs the detector again and returns fresh
    numbers without writing them.

    `split=holdout` is the honest one — rings 9-12, never used for tuning.
    """
    if not recompute:
        stored = latest_stored(db, split)
        if stored is not None:
            stored["source"] = "stored snapshot from the recorded evaluation run"
            stored["live_review_state"] = _live_review_state(db)
            return stored

    computed = compute_metrics(db, split)
    payload = computed.to_dict()
    payload["source"] = (
        "recomputed live; not stored. Run scripts.report to record a snapshot."
    )
    payload["live_review_state"] = _live_review_state(db)
    return payload


def _live_review_state(db: Session) -> dict:
    """Queue state right now, plus the contingent half of the cost model.

    Kept apart from the benchmark numbers: this half needs no labels and would
    work identically on real merchant data.
    """
    status_counts = dict(
        db.execute(text("SELECT status::text, count(*) FROM clusters GROUP BY 1")).all()
    )

    # A false positive that a human APPROVED is the only path by which the
    # contingent trust cost could ever be incurred.
    approved_false = db.execute(
        text(
            """
            SELECT count(*) FROM (
                SELECT c.id,
                       count(*) FILTER (
                           WHERE t.is_synthetic_ring_id IS NOT NULL
                       ) AS ring_txns
                FROM clusters c
                JOIN cluster_members m ON m.cluster_id = c.id
                JOIN entities e ON e.id = m.entity_id AND e.type = 'customer'
                LEFT JOIN transactions t ON t.customer_entity_id = e.id
                WHERE c.status = 'cleared'
                GROUP BY c.id
                HAVING count(*) FILTER (
                    WHERE t.is_synthetic_ring_id IS NOT NULL
                ) = 0
            ) x
            """
        )
    ).scalar_one()

    accounts_in_approved_false = 0
    model = build_cost_model(
        false_positives=max(1, approved_false),
        accounts_in_false_positives=max(1, accounts_in_approved_false or approved_false),
        approved_false_positives=approved_false,
    )

    return {
        "queue": {
            "pending": status_counts.get("pending", 0),
            "needs_review": status_counts.get("needs_review", 0),
            "approved": status_counts.get("cleared", 0),
            "dismissed": status_counts.get("dismissed", 0),
        },
        "approved_false_positives": approved_false,
        "contingent_trust_cost_inr": round(model.contingent_trust_cost_inr, 2)
        if approved_false
        else 0.0,
        "note": (
            "Queue state needs no ground-truth labels and would work the same on "
            "real data. The contingent trust cost is non-zero only when a human "
            "has approved a flag that was not a real ring."
        ),
    }
