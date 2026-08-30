"""Make the audit-chain trigger safe under an empty search_path.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-30

`ringsentinel_audit_chain()` referenced `audit_log` unqualified. That works
whenever `search_path` includes `public`, which is every ordinary session — and
fails in the one case that matters most for a system built around an audit log:
restoring it.

`pg_dump` emits `SELECT pg_catalog.set_config('search_path', '', false)` as a
hardening measure, so a restore runs with no search path at all. The BEFORE
INSERT trigger then fires on the first copied row and cannot resolve its own
table:

    ERROR:  relation "audit_log" does not exist
    QUERY:  SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1
    CONTEXT: PL/pgSQL function public.ringsentinel_audit_chain() line 9

Found while restoring the audit log into the deployed database. An append-only,
hash-chained log that cannot be restored from its own dump is a backup that does
not exist, so this is a durability fix rather than a cosmetic one.

⚠ THE HASH COMPUTATION IS UNCHANGED, DELIBERATELY AND EXACTLY. The same
`sha256(convert_to(previous || ringsentinel_audit_payload(...), 'UTF8'))`, the
same advisory-lock key, the same coalesce. Altering any of it would change every
row_hash, and a chain that verifies only because it was silently recomputed
proves nothing. The only edits are the schema qualification and the attached
`SET search_path`, which gives the function its own resolution rules regardless
of the caller's session and closes the same hole for anything added later.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ringsentinel_audit_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            previous text;
        BEGIN
            -- Serialise audit inserts so the chain cannot fork. Transaction
            -- scoped, so it is released automatically.
            PERFORM pg_advisory_xact_lock(hashtext('ringsentinel.audit_chain'));

            SELECT row_hash INTO previous
            FROM public.audit_log ORDER BY id DESC LIMIT 1;
            previous := coalesce(previous, '');

            NEW.prev_hash := previous;
            NEW.row_hash := encode(
                sha256(convert_to(
                    previous || public.ringsentinel_audit_payload(
                        NEW.id, NEW.actor::text, NEW.action, NEW.target_type,
                        NEW.target_id, NEW.detail_json, NEW.created_at
                    ), 'UTF8')
                ), 'hex');
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Deliberately not reverting to the unqualified form. Restoring the bug
    # would make the audit log unrestorable from its own dump again, and
    # nothing depends on the old body — the hash computation is identical.
    pass
