"""RingSentinel API.

Phase 1 is scaffolding only: health/readiness endpoints and nothing else.
Detection, ingest, and case-file routes arrive in later phases - see CLAUDE.md.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

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
