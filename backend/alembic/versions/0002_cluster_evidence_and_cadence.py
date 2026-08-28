"""Add explainability columns to clusters.

Phase 3 requires that every score be explainable - "store which specific edges
and attributes contributed, never just a black-box number". The Phase 1
`clusters` table has only (id, status, score, created_at), so there is nowhere
to put that. These three columns are the minimum needed:

  evidence_json     the full score breakdown: per-signal contributions, the
                    specific shared attribute entities that drove the score,
                    and the timing statistics behind the cadence call
  cadence           human_like | agent_like | inconclusive
  detector_version  which scoring configuration produced this row, so results
                    stay traceable when thresholds are tuned later

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CADENCE_CLASS = postgresql.ENUM(
    "human_like", "agent_like", "inconclusive", name="cadence_class"
)


def upgrade() -> None:
    bind = op.get_bind()
    CADENCE_CLASS.create(bind, checkfirst=True)

    op.add_column(
        "clusters",
        sa.Column(
            "evidence_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "clusters",
        sa.Column(
            "cadence",
            postgresql.ENUM(name="cadence_class", create_type=False),
            nullable=False,
            server_default="inconclusive",
        ),
    )
    op.add_column(
        "clusters",
        sa.Column(
            "detector_version",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )

    # Reviewers work the queue by score within a status.
    op.create_index(
        "ix_clusters_status_score", "clusters", ["status", sa.text("score DESC")]
    )


def downgrade() -> None:
    op.drop_index("ix_clusters_status_score", table_name="clusters")
    op.drop_column("clusters", "detector_version")
    op.drop_column("clusters", "cadence")
    op.drop_column("clusters", "evidence_json")

    bind = op.get_bind()
    postgresql.ENUM(name="cadence_class").drop(bind, checkfirst=True)
