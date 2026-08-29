"""Cluster review API - the human gate.

    GET  /clusters                  queue, filterable by status
    GET  /clusters/{id}             full case file + evidence + graph
    POST /clusters/{id}/case-file   generate (or reuse) the case file
    POST /clusters/{id}/approve     human confirms the flag   - reason required
    POST /clusters/{id}/dismiss     human rejects the flag    - reason required

The two review endpoints are the ONLY code in the project that changes
`clusters.status`. They are also the only code that sets
`ringsentinel.human_review`, the transaction-local flag the Postgres trigger
requires before it will permit a status change. Anything else attempting a
status update - the detector, the case-file writer, a script, a psql session -
gets an exception from the database.

Neither endpoint blocks, freezes, declines, or restricts anything. Approving a
flag records a human's judgement that the cluster looks coordinated and moves it
out of the pending queue for manual handling. No customer-facing action is taken
anywhere in this codebase (invariant #1).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.case_files import CaseFileError, generate_case_file
from app.db import get_db
from app.models import AuditActor, AuditLog, ClusterStatus

router = APIRouter(prefix="/clusters", tags=["clusters"])

#: What each human action means, and which status it records.
#:
#: NOTE ON NAMING: the Phase 1 enum offers `cleared` / `dismissed` /
#: `needs_review`. "approve" maps to `cleared` in the sense of *cleared out of
#: the review queue as a confirmed case*, not "the accounts are cleared of
#: suspicion" - that is what `dismissed` means here. With only these statuses
#: available and two endpoints, this is the only mapping that leaves every
#: status reachable.
ACTION_TO_STATUS = {
    "approve": ClusterStatus.cleared,
    "dismiss": ClusterStatus.dismissed,
}

#: Audit action names, spelled out rather than derived from the verb - building
#: them with f"cluster_{action}d" produced "cluster_dismissd", and an audit trail
#: with a typo in the action name is one nobody can reliably query.
ACTION_TO_AUDIT_NAME = {
    "approve": "cluster_approved",
    "dismiss": "cluster_dismissed",
}

#: Statuses a human may still decide from. Both are pre-decision triage states
#: set by the detector; neither has touched a customer.
_DECIDABLE_FROM = frozenset(
    {ClusterStatus.pending.value, ClusterStatus.needs_review.value}
)


class ReviewRequest(BaseModel):
    """A human decision. The reason is mandatory and goes into the audit log."""

    reason: str = Field(
        min_length=5,
        max_length=2000,
        description="Why the reviewer reached this decision. Recorded permanently.",
    )
    reviewer: str = Field(
        default="unspecified",
        max_length=200,
        description="Who reviewed it. Recorded permanently.",
    )


class ClusterSummary(BaseModel):
    id: uuid.UUID
    status: str
    score: float
    cadence: str
    size: int
    detector_version: str
    has_case_file: bool
    suggested_action: str | None
    headline: str | None


def _cluster_row(db: Session, cluster_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT id, status::text AS status, score, cadence::text AS cadence, "
            "evidence_json, detector_version, created_at "
            "FROM clusters WHERE id = :cid"
        ),
        {"cid": str(cluster_id)},
    ).mappings().first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"cluster {cluster_id} not found",
        )
    return dict(row)


@router.get("", response_model=list[ClusterSummary])
def list_clusters(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(
        default=None, alias="status", description="pending|cleared|dismissed|needs_review"
    ),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ClusterSummary]:
    """The review queue, highest suspicion first."""
    rows = db.execute(
        text(
            """
            SELECT c.id,
                   c.status::text   AS status,
                   c.score,
                   c.cadence::text  AS cadence,
                   c.detector_version,
                   c.evidence_json->>'headline'          AS headline,
                   (c.evidence_json->>'size')::int       AS size,
                   cf.suggested_action::text             AS suggested_action,
                   (cf.id IS NOT NULL)                   AS has_case_file
            FROM clusters c
            LEFT JOIN LATERAL (
                SELECT id, suggested_action FROM case_files
                WHERE cluster_id = c.id
                ORDER BY generated_at DESC LIMIT 1
            ) cf ON TRUE
            -- Explicit cast: Postgres cannot infer a bare parameter's type
            -- inside IS NULL, and errors with AmbiguousParameter.
            WHERE (CAST(:status_filter AS text) IS NULL
                   OR c.status::text = CAST(:status_filter AS text))
              AND c.score >= :min_score
            ORDER BY c.score DESC
            LIMIT :limit
            """
        ),
        {"status_filter": status_filter, "min_score": min_score, "limit": limit},
    ).mappings().all()

    return [
        ClusterSummary(
            id=r["id"],
            status=r["status"],
            score=r["score"],
            cadence=r["cadence"],
            size=r["size"] or 0,
            detector_version=r["detector_version"],
            has_case_file=bool(r["has_case_file"]),
            suggested_action=r["suggested_action"],
            headline=r["headline"],
        )
        for r in rows
    ]


@router.get("/{cluster_id}")
def get_cluster(cluster_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Everything a reviewer needs: case file, evidence breakdown, graph, history.

    Never generates a case file - that would mean an LLM call on every page view.
    Use POST /clusters/{id}/case-file to create one.
    """
    cluster = _cluster_row(db, cluster_id)

    case_file = db.execute(
        text(
            """
            SELECT id, summary, confidence_note, suggested_action::text AS suggested_action,
                   key_signals, caveats, model, prompt_version,
                   cluster_score_at_generation, detector_version, generated_at
            FROM case_files WHERE cluster_id = :cid
            ORDER BY generated_at DESC LIMIT 1
            """
        ),
        {"cid": str(cluster_id)},
    ).mappings().first()

    members = db.execute(
        text(
            """
            SELECT e.id, e.type::text AS type, e.external_ref, e.first_seen_at
            FROM cluster_members m
            JOIN entities e ON e.id = m.entity_id
            WHERE m.cluster_id = :cid
            ORDER BY e.type, e.external_ref
            """
        ),
        {"cid": str(cluster_id)},
    ).mappings().all()

    member_ids = [str(m["id"]) for m in members]
    edges = db.execute(
        text(
            """
            SELECT el.entity_id_a, el.entity_id_b, el.link_type::text AS link_type,
                   count(*) AS weight
            FROM entity_links el
            WHERE el.entity_id_a = ANY(:ids) AND el.entity_id_b = ANY(:ids)
            GROUP BY 1, 2, 3
            """
        ),
        {"ids": member_ids},
    ).mappings().all() if member_ids else []

    history = db.execute(
        text(
            """
            SELECT actor::text AS actor, action, detail_json, created_at
            FROM audit_log
            WHERE target_type = 'cluster' AND target_id = :cid
            ORDER BY created_at, id
            """
        ),
        {"cid": str(cluster_id)},
    ).mappings().all()

    stale = bool(
        case_file
        and abs(float(case_file["cluster_score_at_generation"]) - float(cluster["score"]))
        > 1e-9
    )

    return {
        "cluster": {
            "id": str(cluster["id"]),
            "status": cluster["status"],
            "score": cluster["score"],
            "cadence": cluster["cadence"],
            "detector_version": cluster["detector_version"],
            "created_at": cluster["created_at"].isoformat(),
        },
        "case_file": (
            {
                **{
                    k: (str(v) if isinstance(v, uuid.UUID) else v)
                    for k, v in dict(case_file).items()
                    if k != "generated_at"
                },
                "generated_at": case_file["generated_at"].isoformat(),
                "stale": stale,
                "disclaimer": (
                    "Written by Claude. suggested_action is a recommendation for "
                    "the reviewer; it has not been and will not be acted on "
                    "automatically."
                ),
            }
            if case_file
            else None
        ),
        "evidence": cluster["evidence_json"],
        "graph": {
            "nodes": [
                {
                    "id": str(m["id"]),
                    "type": m["type"],
                    "external_ref": m["external_ref"],
                    "first_seen_at": m["first_seen_at"].isoformat(),
                }
                for m in members
            ],
            "edges": [
                {
                    "source": str(e["entity_id_a"]),
                    "target": str(e["entity_id_b"]),
                    "link_type": e["link_type"],
                    "weight": e["weight"],
                }
                for e in edges
            ],
        },
        "audit_trail": [
            {
                "actor": h["actor"],
                "action": h["action"],
                "detail": h["detail_json"],
                "at": h["created_at"].isoformat(),
            }
            for h in history
        ],
    }


@router.post("/{cluster_id}/case-file")
async def create_case_file(
    cluster_id: uuid.UUID,
    force: bool = Query(default=False, description="regenerate even if cached"),
    db: Session = Depends(get_db),
) -> dict:
    """Generate the case file, or return the cached one.

    Does not touch cluster status - Claude has no say in that.
    """
    _cluster_row(db, cluster_id)
    try:
        outcome = await generate_case_file(db, cluster_id, force=force)
        db.commit()
    except CaseFileError as exc:
        db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=f"case file generation failed: {exc}",
        ) from exc

    return {
        "cluster_id": str(cluster_id),
        "case_file_id": str(outcome.case_file_id) if outcome.case_file_id else None,
        "created": outcome.created,
        "reused_cache": outcome.reused,
        "reason": outcome.reason,
    }


def _record_review(
    db: Session,
    cluster_id: uuid.UUID,
    action: Literal["approve", "dismiss"],
    body: ReviewRequest,
) -> dict:
    """Apply a human decision. The only path that changes cluster status."""
    cluster = _cluster_row(db, cluster_id)
    previous = cluster["status"]
    new_status = ACTION_TO_STATUS[action]

    # Both pre-decision states are decidable. `needs_review` in particular MUST
    # be: it means "the detector is unsure, a human should look", so refusing to
    # let a human then decide it would strand exactly the clusters that most
    # need judgement. Only an already-recorded decision blocks a second one.
    if previous not in _DECIDABLE_FROM:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"cluster {cluster_id} is already '{previous}'. A decision is "
                "recorded once; re-deciding would overwrite an audit fact."
            ),
        )

    # Declare this transaction a human review action. The Postgres trigger
    # refuses the UPDATE below without it. Transaction-local (third arg true),
    # so it cannot leak into any other statement.
    db.execute(text("SELECT set_config('ringsentinel.human_review', 'on', true)"))

    db.execute(
        text("UPDATE clusters SET status = CAST(:s AS cluster_status) WHERE id = :cid"),
        {"s": new_status.value, "cid": str(cluster_id)},
    )

    db.add(
        AuditLog(
            actor=AuditActor.human,
            action=ACTION_TO_AUDIT_NAME[action],
            target_type="cluster",
            target_id=str(cluster_id),
            detail_json={
                "action": action,
                "previous_status": previous,
                "new_status": new_status.value,
                "reason": body.reason,
                "reviewer": body.reviewer,
                "cluster_score": cluster["score"],
                "detector_version": cluster["detector_version"],
                "note": (
                    "Review decision recorded. No customer-facing action is "
                    "taken by RingSentinel (invariant #1)."
                ),
            },
        )
    )
    db.commit()

    return {
        "cluster_id": str(cluster_id),
        "previous_status": previous,
        "status": new_status.value,
        "action": action,
        "reviewer": body.reviewer,
        "reason": body.reason,
        "note": (
            "Decision recorded in the append-only audit log. No account has been "
            "blocked, frozen, or restricted - RingSentinel never takes "
            "customer-facing action."
        ),
    }


@router.post("/{cluster_id}/approve")
def approve_cluster(
    cluster_id: uuid.UUID, body: ReviewRequest, db: Session = Depends(get_db)
) -> dict:
    """A human confirms this cluster looks like a coordinated ring."""
    return _record_review(db, cluster_id, "approve", body)


@router.post("/{cluster_id}/dismiss")
def dismiss_cluster(
    cluster_id: uuid.UUID, body: ReviewRequest, db: Session = Depends(get_db)
) -> dict:
    """A human rejects the flag as a false positive."""
    return _record_review(db, cluster_id, "dismiss", body)
