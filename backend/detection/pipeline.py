"""Detection pipeline: graph -> clusters -> scores -> Postgres.

    load_graph  ->  population_baseline  ->  find_clusters  ->  score_cluster
                ->  filter by threshold  ->  persist

Persistence rules
-----------------
Clusters are written with `status = 'pending'`. Nothing here ever sets a
terminal status, and nothing here blocks, declines, or restricts any account -
CLAUDE.md invariants #1 and #2. A human moves a cluster out of `pending`, and
only a human.

Re-running the detector deletes previously *pending* clusters and leaves any
cluster a human has already actioned (`cleared`, `dismissed`, `needs_review`)
untouched. Wiping those would silently destroy review work.

Every run appends to `audit_log` with `actor = 'system'`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    AuditActor,
    AuditLog,
    CadenceClass,
    Cluster,
    ClusterMember,
    ClusterStatus,
)
from detection.baseline import TimingBaseline, population_baseline
from detection.clustering import find_clusters
from detection.config import DetectorConfig
from detection.graph import GraphBundle, load_graph
from detection.population import build_population
from detection.thresholds import select_flagged
from detection.scoring import ScoredCluster, score_cluster

log = logging.getLogger(__name__)


@dataclass
class DetectionRun:
    """Everything a caller needs to report on one detection pass."""

    scored: list[ScoredCluster]
    flagged: list[ScoredCluster]
    baseline: TimingBaseline
    bundle: GraphBundle
    config: DetectorConfig
    #: Purely descriptive label for the audit log, e.g. "tuning". The detector
    #: never branches on it - scope is applied through the opaque exclusion set.
    scope_label: str = "all"
    persisted_ids: dict[int, uuid.UUID] = field(default_factory=dict)
    deleted_pending: int = 0
    updated_existing: int = 0
    preserved_reviewed: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_seconds: float = 0.0

    @property
    def candidates(self) -> int:
        return len(self.scored)

    def below_threshold(self) -> list[ScoredCluster]:
        flagged = {id(c) for c in self.flagged}
        return [c for c in self.scored if id(c) not in flagged]


def run_detection(
    db: Session,
    config: DetectorConfig | None = None,
    exclude_transaction_ids: set[uuid.UUID] | None = None,
    persist: bool = True,
    scope_label: str = "all",
) -> DetectionRun:
    """Run one full detection pass.

    `exclude_transaction_ids` is opaque to the detector - the caller decides
    what is in scope. See `detection/graph.py` for why that separation matters.
    """
    import time

    config = config or DetectorConfig()
    started = time.monotonic()

    bundle = load_graph(db, config, exclude_transaction_ids)
    baseline = population_baseline(bundle.customer_timestamps, config)
    candidates = find_clusters(bundle, config)

    # Built once from the whole graph: the question is whether an attribute is
    # unusual for this merchant, so a per-cluster comparison would be circular.
    population = (
        build_population(bundle.graph, bundle.node_type)
        if config.population_relative_reuse
        else None
    )
    scored = [
        score_cluster(c, bundle, baseline, config, population) for c in candidates
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    flagged = select_flagged(scored, config)

    run = DetectionRun(
        scored=scored,
        flagged=flagged,
        baseline=baseline,
        bundle=bundle,
        config=config,
        scope_label=scope_label,
    )

    if persist:
        _persist(db, run)

    run.elapsed_seconds = time.monotonic() - started
    return run


def cluster_fingerprint(customer_ids: list[uuid.UUID]) -> str:
    """Stable identity for a cluster: a hash of its sorted customer accounts.

    Attribute nodes are excluded deliberately. A ring's accounts are what a
    reviewer decides about; which particular device the crew happened to use in
    the last window is incidental, and including it would break the match every
    time the cluster picked up one extra shared attribute.
    """
    joined = "|".join(sorted(str(c) for c in customer_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def triage_status(score: float, config: DetectorConfig) -> ClusterStatus:
    """Which pre-decision state a newly flagged cluster starts in.

    Both outcomes mean "a human still has to look at this" - neither is a
    decision and neither touches a customer:

      pending       flagged, and the detector is confident in the evidence
      needs_review  flagged, but the score sits in the ambiguous band where
                    detection depends on where the threshold was placed

    `cleared` and `dismissed` are the decisions, and remain unreachable from
    here - the database trigger refuses them outside a human review action.
    Marking a cluster `needs_review` is the detector declining to assert
    something it cannot support, which is the opposite of deciding.
    """
    if score >= config.confident_score_threshold:
        return ClusterStatus.pending
    return ClusterStatus.needs_review


_CADENCE_TO_ENUM = {
    "human_like": CadenceClass.human_like,
    "agent_like": CadenceClass.agent_like,
    "inconclusive": CadenceClass.inconclusive,
}


def _persist(db: Session, run: DetectionRun) -> None:
    """Write flagged clusters, replacing only previously-pending ones."""
    preserved = db.execute(
        text(
            "SELECT count(*) FROM clusters "
            "WHERE status NOT IN ('pending', 'needs_review')"
        )
    ).scalar_one()
    run.preserved_reviewed = int(preserved)

    # Existing clusters keyed by fingerprint, so a re-run can update in place
    # rather than delete and re-insert. Updating preserves the cluster's status,
    # its case files, and its audit history.
    existing = {
        row.fingerprint: (row.id, row.status)
        for row in db.execute(
            text(
                "SELECT id, fingerprint, status::text AS status FROM clusters "
                "WHERE fingerprint IS NOT NULL"
            )
        )
    }

    flagged_fingerprints = {
        cluster_fingerprint(item.candidate.customers) for item in run.flagged
    }

    # Retire only pending clusters that are no longer flagged at all. Anything a
    # human has actioned stays, and anything still flagged is updated below.
    stale = [
        cid
        for fp, (cid, st) in existing.items()
        if st in ("pending", "needs_review") and fp not in flagged_fingerprints
    ]
    if stale:
        db.execute(
            text("DELETE FROM clusters WHERE id = ANY(:ids)"),
            {"ids": [str(c) for c in stale]},
        )
    run.deleted_pending = len(stale)

    for index, item in enumerate(run.flagged):
        fingerprint = cluster_fingerprint(item.candidate.customers)
        prior = existing.get(fingerprint)

        if prior is not None:
            # Same accounts as a cluster we already know about. Refresh the
            # detector's view of it; never touch status - that is the human's.
            cluster_id = prior[0]
            db.execute(
                text(
                    "UPDATE clusters SET score = :score, cadence = CAST(:cad AS cadence_class), "
                    "evidence_json = CAST(:ev AS jsonb), detector_version = :ver "
                    "WHERE id = :cid"
                ),
                {
                    "score": round(item.score, 6),
                    "cad": item.cadence.classification,
                    "ev": json.dumps(item.to_evidence(run.config)),
                    "ver": run.config.version,
                    "cid": str(cluster_id),
                },
            )
            # Refresh triage only while the cluster is still undecided. Once
            # a human has ruled, the row is theirs and the trigger enforces it.
            if prior[1] in ("pending", "needs_review"):
                db.execute(
                    text(
                        "UPDATE clusters SET status = CAST(:s AS cluster_status) "
                        "WHERE id = :cid"
                    ),
                    {
                        "s": triage_status(item.score, run.config).value,
                        "cid": str(cluster_id),
                    },
                )
            db.execute(
                text("DELETE FROM cluster_members WHERE cluster_id = :cid"),
                {"cid": str(cluster_id)},
            )
            run.updated_existing += 1
        else:
            cluster_id = uuid.uuid4()
            db.add(
                Cluster(
                    id=cluster_id,
                    score=round(item.score, 6),
                    cadence=_CADENCE_TO_ENUM[item.cadence.classification],
                    evidence_json=item.to_evidence(run.config),
                    detector_version=run.config.version,
                    fingerprint=fingerprint,
                    # Triage only: pending or needs_review. A terminal status
                    # is never set here - see triage_status().
                    status=triage_status(item.score, run.config),
                )
            )
        # Members are the accounts AND the shared attributes that implicated
        # them, so a reviewer can see the whole picture from cluster_members.
        member_ids = list(item.candidate.customers) + [
            a.entity_id for a in item.shared_attributes
        ]
        for entity_id in dict.fromkeys(member_ids):
            db.add(ClusterMember(cluster_id=cluster_id, entity_id=entity_id))

        run.persisted_ids[index] = cluster_id

        # Per-cluster flag event, only for clusters seen for the first time.
        # Re-flagging an existing cluster every run would bury its real history.
        if prior is not None:
            continue
        db.add(
            AuditLog(
                actor=AuditActor.system,
                action="cluster_flagged",
                target_type="cluster",
                target_id=str(cluster_id),
                detail_json={
                    "score": round(item.score, 6),
                    "size": item.size,
                    "cadence": item.cadence.classification,
                    "detector_version": run.config.version,
                    "score_threshold": run.config.score_threshold,
                    "headline": item.headline(),
                    "shared_attributes": [
                        {
                            "type": a.attribute_type,
                            "external_ref": a.external_ref,
                            "customer_count": a.customer_count,
                            "observations": a.observations,
                        }
                        for a in item.top_attributes(5)
                    ],
                    "note": (
                        "Flagged for human review. Status is 'pending' and no "
                        "customer-facing action has been taken."
                    ),
                },
            )
        )

    db.add(
        AuditLog(
            actor=AuditActor.system,
            action="detection_run",
            target_type="detector",
            target_id=run.config.version,
            detail_json={
                "scope_label": run.scope_label,
                "candidates_examined": len(run.scored),
                "clusters_flagged": len(run.flagged),
                "score_threshold": run.config.score_threshold,
                "stale_pending_removed": run.deleted_pending,
                "existing_clusters_updated": run.updated_existing,
                "reviewed_clusters_preserved": run.preserved_reviewed,
                "graph_nodes": run.bundle.graph.number_of_nodes(),
                "graph_edges": run.bundle.graph.number_of_edges(),
                "hub_attributes_dropped": len(run.bundle.dropped_hubs),
                "baseline_median_gap_seconds": round(
                    run.baseline.median_gap_seconds, 2
                ),
                "transactions_in_scope": run.bundle.total_transactions,
            },
        )
    )
