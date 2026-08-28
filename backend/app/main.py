"""RingSentinel API.

Phase 2 adds the Razorpay webhook receiver, which is the only path by which
transactions enter the database. Detection and case-file routes arrive in later
phases - see CLAUDE.md.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.webhooks import router as webhooks_router

settings = get_settings()

app = FastAPI(
    title="RingSentinel API",
    description="Fraud-ring detection via entity graphs. Human-in-the-loop by design.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)

EXPECTED_TABLES = (
    "entities",
    "entity_links",
    "transactions",
    "clusters",
    "cluster_members",
    "audit_log",
)


@app.get("/")
def root() -> dict:
    return {
        "service": "ringsentinel-api",
        "version": "0.1.0",
        "phase": "1 - scaffolding",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict:
    """Liveness - does the process respond at all."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    """Readiness - is Postgres reachable and is the schema migrated."""
    db.execute(text("SELECT 1"))

    rows = db.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
    ).scalars()
    present = set(rows)
    missing = [t for t in EXPECTED_TABLES if t not in present]

    return {
        "status": "ok" if not missing else "schema_incomplete",
        "tables_present": sorted(present & set(EXPECTED_TABLES)),
        "tables_missing": missing,
    }


@app.get("/eval/corpus", tags=["evaluation"])
def eval_corpus(db: Session = Depends(get_db)) -> dict:
    """Ground-truth corpus summary. EVALUATION SURFACE ONLY.

    This endpoint deliberately reads `transactions.is_synthetic_ring_id`, which
    is why it lives under /eval and is named as such. Detection code (Phase 3)
    must never call it and must read `v_transactions_detector` instead - see
    CLAUDE.md invariant #4. It exists so a human can confirm that what landed in
    Postgres matches what was actually sent to Razorpay.
    """
    totals = db.execute(
        text(
            """
            SELECT
                (SELECT count(*) FROM entities)     AS entities,
                (SELECT count(*) FROM entity_links) AS entity_links,
                (SELECT count(*) FROM transactions) AS transactions
            """
        )
    ).mappings().one()

    by_type = dict(
        db.execute(
            text("SELECT type::text, count(*) FROM entities GROUP BY 1 ORDER BY 1")
        ).all()
    )
    by_link = dict(
        db.execute(
            text("SELECT link_type::text, count(*) FROM entity_links GROUP BY 1 ORDER BY 1")
        ).all()
    )

    rings = db.execute(
        text(
            """
            SELECT
                split_part(is_synthetic_ring_id, '|', 1) AS ring,
                split_part(is_synthetic_ring_id, '|', 2) AS pattern,
                split_part(is_synthetic_ring_id, '|', 3) AS cadence,
                split_part(is_synthetic_ring_id, '|', 4) AS split,
                count(*)                                 AS transactions,
                count(DISTINCT customer_entity_id)       AS accounts
            FROM transactions
            WHERE is_synthetic_ring_id IS NOT NULL
            GROUP BY 1, 2, 3, 4
            ORDER BY 1
            """
        )
    ).mappings().all()

    normal_count = db.execute(
        text("SELECT count(*) FROM transactions WHERE is_synthetic_ring_id IS NULL")
    ).scalar_one()

    return {
        "totals": dict(totals),
        "entities_by_type": by_type,
        "links_by_type": by_link,
        "normal_transactions": normal_count,
        "rings": [dict(r) for r in rings],
        "holdout_note": (
            "Rings 09-12 are the held-out evaluation set. Do not tune the "
            "detector against them."
        ),
    }
