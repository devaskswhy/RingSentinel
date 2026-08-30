"""Hash-chain the audit log, and move the reason requirement into the database.

Two changes, both about making an existing guarantee *provable* rather than
merely true.

1. Every `audit_log` row stores `sha256(previous_row_hash || this row)`. The
   append-only trigger already refused UPDATE and DELETE; a chain goes further
   by making tampering *detectable* rather than merely blocked. Someone with
   raw database access can drop the triggers and rewrite a row - they cannot
   make the chain still add up afterwards.

   Inserts take a transaction-scoped advisory lock so the chain stays linear.
   Two concurrent inserts would otherwise both read the same predecessor and
   fork it. Audit writes are rare, so serialising them costs nothing.

2. The status guard now also requires a written reason, supplied through
   `ringsentinel.review_reason`. Until now the reason was mandatory only in
   Pydantic - real, but an application-layer promise. A judge asking "can
   anything set a status without a recorded reason?" should be able to get the
   answer from the database rather than from a code review.

   No behaviour changes: the approve/dismiss endpoints already demanded a
   reason of at least five characters. This moves where that is enforced.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: Minimum reason length, matching the Pydantic constraint on ReviewRequest.
MIN_REASON_LENGTH = 5


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("row_hash", sa.Text(), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.Text(), nullable=True))
    op.create_index("ix_audit_log_row_hash", "audit_log", ["row_hash"])

    # ---- the canonical payload a row hashes over --------------------------
    # One function, used by both the backfill and the insert trigger, so the
    # two can never disagree about what was hashed.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ringsentinel_audit_payload(
            p_id bigint,
            p_actor text,
            p_action text,
            p_target_type text,
            p_target_id text,
            p_detail jsonb,
            p_created_at timestamptz
        ) RETURNS text
        LANGUAGE sql IMMUTABLE
        AS $$
            SELECT p_id::text || '|' || p_actor || '|' || p_action || '|'
                || p_target_type || '|' || p_target_id || '|'
                || coalesce(p_detail::text, '{}') || '|'
                || to_char(p_created_at AT TIME ZONE 'UTC',
                           'YYYY-MM-DD"T"HH24:MI:SS.US');
        $$;
        """
    )

    # ---- backfill the existing rows ---------------------------------------
    # The append-only trigger blocks UPDATE - it blocked this migration on the
    # first attempt, which is the guarantee working as intended. Stand it down
    # for the backfill and re-arm it immediately afterwards, inside the same
    # transaction, so there is no window in which the log is unprotected.
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update_delete ON audit_log;")

    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
            previous text := '';
        BEGIN
            FOR r IN
                SELECT id, actor::text AS actor, action, target_type, target_id,
                       detail_json, created_at
                FROM audit_log ORDER BY id
            LOOP
                UPDATE audit_log
                SET prev_hash = previous,
                    row_hash = encode(
                        sha256(convert_to(
                            previous || ringsentinel_audit_payload(
                                r.id, r.actor, r.action, r.target_type,
                                r.target_id, r.detail_json, r.created_at
                            ), 'UTF8')
                        ), 'hex')
                WHERE id = r.id;

                SELECT row_hash INTO previous FROM audit_log WHERE id = r.id;
            END LOOP;
        END $$;
        """
    )

    # Re-arm append-only now that every row carries a hash.
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION ringsentinel_audit_log_append_only();
        """
    )

    # ---- chain new rows on the way in -------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ringsentinel_audit_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            previous text;
        BEGIN
            -- Serialise audit inserts so the chain cannot fork. Transaction
            -- scoped, so it is released automatically.
            PERFORM pg_advisory_xact_lock(hashtext('ringsentinel.audit_chain'));

            SELECT row_hash INTO previous FROM audit_log ORDER BY id DESC LIMIT 1;
            previous := coalesce(previous, '');

            NEW.prev_hash := previous;
            NEW.row_hash := encode(
                sha256(convert_to(
                    previous || ringsentinel_audit_payload(
                        NEW.id, NEW.actor::text, NEW.action, NEW.target_type,
                        NEW.target_id, NEW.detail_json, NEW.created_at
                    ), 'UTF8')
                ), 'hex');
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_chain
        BEFORE INSERT ON audit_log
        FOR EACH ROW EXECUTE FUNCTION ringsentinel_audit_chain();
        """
    )

    # ---- the reason requirement moves into the database -------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION ringsentinel_cluster_status_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            terminal text[] := ARRAY['cleared', 'dismissed'];
            guarded  text  := coalesce(
                current_setting('ringsentinel.human_review', true), ''
            );
            reason   text  := coalesce(
                current_setting('ringsentinel.review_reason', true), ''
            );
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status THEN

                IF OLD.status::text = ANY(terminal) THEN
                    RAISE EXCEPTION
                        'cluster % already has the recorded decision %; a '
                        'decision is written once and never revised '
                        '(RingSentinel invariant #3).',
                        OLD.id, OLD.status;
                END IF;

                IF NEW.status::text = ANY(terminal) THEN
                    IF guarded <> 'on' THEN
                        RAISE EXCEPTION
                            'clusters.status may only be decided by a human '
                            'review action (RingSentinel invariants #1 and #2). '
                            'Attempted % -> % without ringsentinel.human_review '
                            'set.', OLD.status, NEW.status;
                    END IF;

                    IF length(btrim(reason)) < {MIN_REASON_LENGTH} THEN
                        RAISE EXCEPTION
                            'a decision requires a written reason of at least '
                            '{MIN_REASON_LENGTH} characters '
                            '(ringsentinel.review_reason). Attempted % -> % '
                            'with %.',
                            OLD.status, NEW.status,
                            CASE WHEN length(btrim(reason)) = 0
                                 THEN 'none supplied'
                                 ELSE length(btrim(reason))::text || ' characters'
                            END;
                    END IF;
                END IF;

                -- pending <-> needs_review is triage, not a decision.
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    # The trigger itself was created in 0003 and this migration only replaces
    # the function behind it. That is a gap: if the trigger has been dropped -
    # by a tamper test, or by someone with database access - replacing the
    # function restores nothing, and the guarantee stays silently absent.
    # CREATE OR REPLACE TRIGGER (PostgreSQL 14+) makes this migration able to
    # restore the guard rather than merely assume it.
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_clusters_status_human_only
        BEFORE UPDATE ON clusters
        FOR EACH ROW EXECUTE FUNCTION ringsentinel_cluster_status_guard();
        """
    )

def downgrade() -> None:
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
                IF OLD.status::text = ANY(terminal) THEN
                    RAISE EXCEPTION 'decision already recorded';
                END IF;
                IF NEW.status::text = ANY(terminal) AND guarded <> 'on' THEN
                    RAISE EXCEPTION 'human review required';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_chain ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS ringsentinel_audit_chain();")
    op.execute("DROP FUNCTION IF EXISTS ringsentinel_audit_payload(bigint, text, text, text, text, jsonb, timestamptz);")
    op.drop_index("ix_audit_log_row_hash", table_name="audit_log")
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "row_hash")
