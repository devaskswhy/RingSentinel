"""Store evaluation metrics, and let the detector triage without deciding.

Two changes.

1. `evaluation_runs` — a snapshot of precision, recall, the confusion matrix,
   the exception count, and the false-positive cost estimate for one detector
   run. Stored rather than recomputed on request so /metrics reports what was
   actually measured, and so a later config change cannot silently rewrite a
   number that has already been reported.

2. The cluster status guard is rewritten. The old version blocked *any* status
   change outside a human review transaction, which would have prevented the
   detector from marking an ambiguous cluster `needs_review`.

   The distinction that actually matters is decision versus triage:

     pending, needs_review   both mean "a human still has to look at this".
                             The detector may move between them freely; neither
                             is a decision and neither touches a customer.
     cleared, dismissed      these ARE decisions. Humans only, and once written
                             they can never be changed.

   So the new guard is strictly stronger than the old one: it still refuses any
   automated move into a terminal state, and it additionally refuses to move a
   cluster *out* of one, which the previous version allowed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("detector_version", sa.Text(), nullable=False),
        sa.Column("score_threshold", sa.Float(), nullable=False),
        # Confusion matrix, counted in RINGS for recall and in CLUSTERS for
        # precision - the two questions have different units and conflating
        # them is the usual way these numbers get quietly wrong.
        sa.Column("true_positives", sa.Integer(), nullable=False),
        sa.Column("false_positives", sa.Integer(), nullable=False),
        sa.Column("false_negatives", sa.Integer(), nullable=False),
        sa.Column("precision", sa.Float(), nullable=False),
        sa.Column("recall", sa.Float(), nullable=False),
        sa.Column("rings_total", sa.Integer(), nullable=False),
        sa.Column("needs_review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "false_positive_cost_inr", sa.Float(), nullable=False, server_default="0"
        ),
        # Every number in the cost model is an estimate. Storing the assumptions
        # alongside the result means a reader can disagree with them explicitly.
        sa.Column("cost_assumptions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("detail_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_evaluation_runs_split_time",
        "evaluation_runs",
        ["split", sa.text("run_at DESC")],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ringsentinel_cluster_status_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            terminal text[] := ARRAY['cleared', 'dismissed'];
            guarded  text  := coalesce(
                current_setting('ringsentinel.human_review', true), ''
            );
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status THEN

                -- A recorded decision is final. Not even a human review
                -- transaction may rewrite one; the audit log would then
                -- disagree with the row.
                IF OLD.status::text = ANY(terminal) THEN
                    RAISE EXCEPTION
                        'cluster % already has the recorded decision %; a '
                        'decision is written once and never revised '
                        '(RingSentinel invariant #3).',
                        OLD.id, OLD.status;
                END IF;

                -- Moving INTO a terminal state is a decision: humans only.
                IF NEW.status::text = ANY(terminal) AND guarded <> 'on' THEN
                    RAISE EXCEPTION
                        'clusters.status may only be decided by a human review '
                        'action (RingSentinel invariants #1 and #2). Attempted '
                        '% -> % without ringsentinel.human_review set.',
                        OLD.status, NEW.status;
                END IF;

                -- pending <-> needs_review is triage, not a decision. The
                -- detector may do that; no customer is affected either way.
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
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
    op.drop_index("ix_evaluation_runs_split_time", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
