"""Case files, plus a database guard on cluster status changes.

Two things here.

1. `case_files` - Claude's plain-language explanation of a flagged cluster,
   cached so a page view never triggers regeneration. One row per generation
   rather than one per cluster, so a regenerated case file leaves the previous
   one intact and the history stays auditable.

2. `trg_clusters_status_human_only` - the enforcement half of invariants #1
   and #2. `clusters.status` may only change inside a transaction that has
   explicitly declared itself a human review action by setting
   `ringsentinel.human_review = 'on'`. Only the approve/dismiss endpoints do
   that. The detector, the case-file writer, a stray script, or someone at a
   psql prompt all get an exception instead.

   This turns "nothing auto-blocks" from a code-review promise into something
   the database refuses to allow.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SUGGESTED_ACTION = postgresql.ENUM(
    "likely_ring",
    "review_closer",
    "likely_false_positive",
    name="suggested_action",
)


def upgrade() -> None:
    bind = op.get_bind()
    SUGGESTED_ACTION.create(bind, checkfirst=True)

    op.create_table(
        "case_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=False),
        # A RECOMMENDATION ONLY. Nothing acts on this value automatically; it is
        # advice for the human reviewing the cluster.
        sa.Column(
            "suggested_action",
            postgresql.ENUM(name="suggested_action", create_type=False),
            nullable=False,
        ),
        sa.Column("key_signals", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("caveats", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("raw_response", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("model", sa.Text(), nullable=False, server_default=""),
        # Bumping the prompt version invalidates cached case files.
        sa.Column("prompt_version", sa.Text(), nullable=False, server_default=""),
        # What the cluster looked like when this was written, so a stale case
        # file can be spotted after the detector is retuned.
        sa.Column("cluster_score_at_generation", sa.Float(), nullable=False, server_default="0"),
        sa.Column("detector_version", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_case_files_cluster", "case_files", ["cluster_id"])
    op.create_index(
        "ix_case_files_cluster_generated",
        "case_files",
        ["cluster_id", sa.text("generated_at DESC")],
    )

    # ---- Human-review guard on cluster status ---------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ringsentinel_cluster_status_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF coalesce(
                       current_setting('ringsentinel.human_review', true), ''
                   ) <> 'on' THEN
                    RAISE EXCEPTION
                        'clusters.status may only be changed by a human review '
                        'action (RingSentinel invariants #1 and #2). Attempted '
                        '% -> % without ringsentinel.human_review set.',
                        OLD.status, NEW.status;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_clusters_status_human_only
        BEFORE UPDATE ON clusters
        FOR EACH ROW EXECUTE FUNCTION ringsentinel_cluster_status_guard();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_clusters_status_human_only ON clusters;")
    op.execute("DROP FUNCTION IF EXISTS ringsentinel_cluster_status_guard();")
    op.drop_index("ix_case_files_cluster_generated", table_name="case_files")
    op.drop_index("ix_case_files_cluster", table_name="case_files")
    op.drop_table("case_files")
    postgresql.ENUM(name="suggested_action").drop(op.get_bind(), checkfirst=True)
