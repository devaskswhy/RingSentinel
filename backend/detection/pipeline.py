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

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuditActor, AuditLog, CadenceClass, Cluster, ClusterMember
from detection.baseline import TimingBaseline, population_baseline
from detection.clustering import find_clusters
from detection.config import DetectorConfig
from detection.graph import GraphBundle, load_graph
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
    persisted_ids: dict[int, uuid.UUID] = field(default_factory=dict)
    deleted_pending: int = 0
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

    scored = [score_cluster(c, bundle, baseline, config) for c in candidates]
    scored.sort(key=lambda s: s.score, reverse=True)
    flagged = [s for s in scored if s.score >= config.score_threshold]

    run = DetectionRun(
        scored=scored,
        flagged=flagged,
        baseline=baseline,
        bundle=bundle,
        config=config,
    )

    if persist:
        _persist(db, run)

    run.elapsed_seconds = time.monotonic() - started
    return run


_CADENCE_TO_ENUM = {
    "human_like": CadenceClass.human_like,
    "agent_like": CadenceClass.agent_like,
    "inconclusive": CadenceClass.inconclusive,
}


def _persist(db: Session, run: DetectionRun) -> None:
    """Write flagged clusters, replacing only previously-pending ones."""
    preserved = db.execute(
        text("SELECT count(*) FROM clusters WHERE status <> 'pending'")
    ).scalar_one()
    run.preserved_reviewed = int(preserved)

    # cluster_members cascades on delete.
    deleted = db.execute(
        text("DELETE FROM clusters WHERE status = 'pending'")
    ).rowcount
    run.deleted_pending = int(deleted or 0)

    for index, item in enumerate(run.flagged):
        cluster_id = uuid.uuid4()
        db.add(
            Cluster(
                id=cluster_id,
                score=round(item.score, 6),
                cadence=_CADENCE_TO_ENUM[item.cadence.classification],
                evidence_json=item.to_evidence(run.config),
                detector_version=run.config.version,
                # status defaults to 'pending'. Never set here - only a human
                # review action may move it.
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

        # Per-cluster flag event. The run-level row below records the pass as a
        # whole; this one makes each cluster's own history complete, so
        # GET /clusters/{id} can show flagged -> case file -> decision.
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
                "candidates_examined": len(run.scored),
                "clusters_flagged": len(run.flagged),
                "score_threshold": run.config.score_threshold,
                "pending_clusters_replaced": run.deleted_pending,
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
