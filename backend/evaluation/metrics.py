"""Precision, recall, cost, and the exception list. READS GROUND TRUTH.

Lives in `evaluation/` because it needs labels. Nothing under `detection/`
imports this, and `scripts/verify_detector_isolation.py` fails the build if that
ever changes.

A note on units, because this is where these numbers usually go quietly wrong
-----------------------------------------------------------------------------
Precision and recall are counted in DIFFERENT units here, deliberately:

  recall     counted in RINGS.    "of the rings that exist, how many did we
                                   find?" A ring is found when some flagged
                                   cluster contains at least half its accounts.
  precision  counted in CLUSTERS. "of the things we put in front of an analyst,
                                   how many were real?" The analyst's time is
                                   spent per cluster, not per ring.

Mixing them into a single confusion matrix and reporting one F1 would be tidier
and would mean less. Both are reported with their unit attached.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from detection.config import DetectorConfig
from detection.pipeline import run_detection
from detection.scoring import ScoredCluster
from evaluation.cost import assumptions, build_cost_model, describe
from evaluation.report import MIN_ACCOUNT_RECALL, MIN_RING_PURITY
from evaluation.splits import (
    SPLIT_ALL,
    load_ring_truth,
    normal_customer_ids,
    transactions_to_exclude,
)


@dataclass
class Exception_:
    """One cluster the detector declined to be confident about."""

    cluster_index: int
    score: float
    size: int
    cadence: str
    headline: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "size": self.size,
            "cadence": self.cadence,
            "headline": self.headline,
            "reason": self.reason,
        }


@dataclass
class Metrics:
    split: str
    detector_version: str
    score_threshold: float
    confident_threshold: float

    rings_total: int
    rings_detected: int
    true_positives: int  # clusters that matched a real ring
    false_positives: int  # clusters that matched nothing
    false_negatives: int  # rings nobody found

    clusters_flagged: int
    needs_review: list[Exception_] = field(default_factory=list)

    normal_accounts_total: int = 0
    normal_accounts_swept_in: int = 0
    accounts_in_false_positives: int = 0
    cadence_correct: int = 0

    ring_rows: list[dict] = field(default_factory=list)
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def precision(self) -> float:
        """TP / (TP + FP), counted in CLUSTERS."""
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN), counted in RINGS."""
        denominator = self.rings_detected + self.false_negatives
        return self.rings_detected / denominator if denominator else 0.0

    @property
    def cost(self):
        return build_cost_model(
            false_positives=self.false_positives,
            accounts_in_false_positives=self.accounts_in_false_positives,
            # Nothing has been approved at evaluation time; the contingent half
            # is driven by live review outcomes in /metrics instead.
            approved_false_positives=0,
        )

    def to_dict(self) -> dict:
        return {
            "split": self.split,
            "run_at": self.run_at.isoformat(),
            "detector_version": self.detector_version,
            "score_threshold": self.score_threshold,
            "confident_threshold": self.confident_threshold,
            "headline": {
                "precision": round(self.precision, 4),
                "precision_unit": "clusters — of what we showed an analyst, how much was real",
                "recall": round(self.recall, 4),
                "recall_unit": "rings — of the rings that exist, how many we found",
                "false_positive_cost_inr": round(self.cost.total_inr, 2),
            },
            "confusion": {
                "true_positives_clusters": self.true_positives,
                "false_positives_clusters": self.false_positives,
                "false_negatives_rings": self.false_negatives,
                "rings_total": self.rings_total,
                "rings_detected": self.rings_detected,
                "clusters_flagged": self.clusters_flagged,
                "match_rule": (
                    f"a ring counts as found when a cluster holds >= "
                    f"{MIN_ACCOUNT_RECALL:.0%} of its accounts; a cluster counts "
                    f"as real when >= {MIN_RING_PURITY:.0%} of its accounts "
                    "belong to some ring"
                ),
            },
            "cadence": {
                "correct": self.cadence_correct,
                "of_detected": self.rings_detected,
            },
            "clean_accounts": {
                "total": self.normal_accounts_total,
                "swept_into_a_flag": self.normal_accounts_swept_in,
            },
            "needs_review": {
                "count": len(self.needs_review),
                "band": [self.score_threshold, self.confident_threshold],
                "note": (
                    "Scores inside this band are flagged but not asserted. The "
                    "detector is reporting that its own confidence is low, "
                    "rather than forcing a binary it cannot justify."
                ),
                "clusters": [e.to_dict() for e in self.needs_review],
            },
            "cost": self.cost.to_dict(),
            "cost_model": describe(),
            "rings": self.ring_rows,
        }


def compute_metrics(
    db: Session, split: str, config: DetectorConfig | None = None
) -> Metrics:
    """Run the detector on `split` and score it against ground truth."""
    config = config or DetectorConfig()

    excluded = transactions_to_exclude(db, split)
    rings = load_ring_truth(db, None if split == SPLIT_ALL else split)
    normals = normal_customer_ids(db)

    run = run_detection(
        db, config=config, exclude_transaction_ids=excluded, persist=False,
        scope_label=split,
    )
    db.rollback()

    ring_accounts = {r.ring: set(r.customer_entity_ids) for r in rings}
    all_ring_accounts: set[uuid.UUID] = set()
    for accounts in ring_accounts.values():
        all_ring_accounts |= accounts

    flagged: list[ScoredCluster] = run.flagged
    cluster_accounts = [set(c.candidate.customers) for c in flagged]

    true_positives = 0
    false_positives = 0
    accounts_in_fp = 0
    swept: set[uuid.UUID] = set()
    exceptions: list[Exception_] = []

    for index, (item, accounts) in enumerate(zip(flagged, cluster_accounts)):
        hits = accounts & all_ring_accounts
        purity = len(hits) / len(accounts) if accounts else 0.0
        if purity >= MIN_RING_PURITY:
            true_positives += 1
        else:
            false_positives += 1
            accounts_in_fp += len(accounts)
        swept |= accounts - all_ring_accounts

        if item.score < config.confident_score_threshold:
            exceptions.append(
                Exception_(
                    cluster_index=index,
                    score=item.score,
                    size=item.size,
                    cadence=item.cadence.classification,
                    headline=item.headline(),
                    reason=(
                        f"score {item.score:.3f} sits in the ambiguous band "
                        f"[{config.score_threshold}, "
                        f"{config.confident_score_threshold}) — detection here "
                        "depends on where the threshold is placed"
                    ),
                )
            )

    detected = 0
    cadence_correct = 0
    ring_rows: list[dict] = []
    for ring in rings:
        truth_accounts = set(ring.customer_entity_ids)
        best, best_overlap = None, 0
        for index, accounts in enumerate(cluster_accounts):
            overlap = len(truth_accounts & accounts)
            if overlap > best_overlap:
                best_overlap, best = overlap, index

        found = (
            best_overlap / len(truth_accounts) >= MIN_ACCOUNT_RECALL
            if truth_accounts
            else False
        )
        if found:
            detected += 1
            if best is not None and flagged[best].cadence.classification.startswith(
                ring.cadence
            ):
                cadence_correct += 1

        ring_rows.append(
            {
                "ring": ring.ring,
                "pattern": ring.pattern,
                "cadence": ring.cadence,
                "split": ring.split,
                "accounts": len(truth_accounts),
                "accounts_found": best_overlap,
                "detected": found,
                "score": round(flagged[best].score, 4) if (found and best is not None) else None,
            }
        )

    return Metrics(
        split=split,
        detector_version=config.version,
        score_threshold=config.score_threshold,
        confident_threshold=config.confident_score_threshold,
        rings_total=len(rings),
        rings_detected=detected,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=len(rings) - detected,
        clusters_flagged=len(flagged),
        needs_review=exceptions,
        normal_accounts_total=len(normals),
        normal_accounts_swept_in=len(swept),
        accounts_in_false_positives=accounts_in_fp,
        cadence_correct=cadence_correct,
        ring_rows=ring_rows,
    )


def store_metrics(db: Session, metrics: Metrics) -> uuid.UUID:
    """Persist a metrics snapshot so a later config change cannot rewrite it."""
    run_id = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO evaluation_runs (
                id, run_at, split, detector_version, score_threshold,
                true_positives, false_positives, false_negatives,
                precision, recall, rings_total, needs_review_count,
                false_positive_cost_inr, cost_assumptions, detail_json
            ) VALUES (
                :id, :run_at, :split, :ver, :thr,
                :tp, :fp, :fn,
                :precision, :recall, :rings_total, :needs_review,
                :cost, CAST(:assumptions AS jsonb), CAST(:detail AS jsonb)
            )
            """
        ),
        {
            "id": str(run_id),
            "run_at": metrics.run_at,
            "split": metrics.split,
            "ver": metrics.detector_version,
            "thr": metrics.score_threshold,
            "tp": metrics.true_positives,
            "fp": metrics.false_positives,
            "fn": metrics.false_negatives,
            "precision": metrics.precision,
            "recall": metrics.recall,
            "rings_total": metrics.rings_total,
            "needs_review": len(metrics.needs_review),
            "cost": metrics.cost.total_inr,
            "assumptions": __import__("json").dumps(assumptions()),
            "detail": __import__("json").dumps(metrics.to_dict()),
        },
    )
    return run_id


def latest_stored(db: Session, split: str) -> dict | None:
    row = db.execute(
        text(
            "SELECT detail_json, run_at FROM evaluation_runs "
            "WHERE split = :split ORDER BY run_at DESC LIMIT 1"
        ),
        {"split": split},
    ).mappings().first()
    return dict(row["detail_json"]) if row else None
