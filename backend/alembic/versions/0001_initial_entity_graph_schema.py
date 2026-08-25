"""Initial RingSentinel entity-graph schema.

Creates the four enum types, six tables, the append-only guard on audit_log,
and the ground-truth-free view the detector is expected to read.

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


ENTITY_TYPE = postgresql.ENUM(
    "customer", "device", "instrument", "address", name="entity_type"
)
LINK_TYPE = postgresql.ENUM(
    "shared_device", "shared_address", "shared_instrument", name="link_type"
)
CLUSTER_STATUS = postgresql.ENUM(
    "pending", "cleared", "dismissed", "needs_review", name="cluster_status"
)
AUDIT_ACTOR = postgresql.ENUM("system", "claude", "human", name="audit_actor")


def upgrade() -> None:
    bind = op.get_bind()

    # ---- Enum types -------------------------------------------------------
    for enum_type in (ENTITY_TYPE, LINK_TYPE, CLUSTER_STATUS, AUDIT_ACTOR):
        enum_type.create(bind, checkfirst=True)

    entity_type = postgresql.ENUM(name="entity_type", create_type=False)
    link_type = postgresql.ENUM(name="link_type", create_type=False)
    cluster_status = postgresql.ENUM(name="cluster_status", create_type=False)
    audit_actor = postgresql.ENUM(name="audit_actor", create_type=False)

    # ---- entities ---------------------------------------------------------
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", entity_type, nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("type", "external_ref", name="uq_entities_type_external_ref"),
    )
    op.create_index("ix_entities_type", "entities", ["type"])

    # ---- transactions -----------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("razorpay_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "customer_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "device_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "address_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "instrument_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Minor units (paise), matching the Razorpay API.
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # GROUND TRUTH - evaluation only, never read by the detector.
        sa.Column("is_synthetic_ring_id", sa.Text(), nullable=True),
        sa.CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
    )
    op.create_index("ix_transactions_customer", "transactions", ["customer_entity_id"])
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])

    # ---- entity_links -----------------------------------------------------
    op.create_table(
        "entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id_a",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id_b",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", link_type, nullable=False),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entity_id_a < entity_id_b", name="ck_entity_links_canonical_order"
        ),
        sa.UniqueConstraint(
            "entity_id_a",
            "entity_id_b",
            "link_type",
            "transaction_id",
            name="uq_entity_links_observation",
        ),
    )
    op.create_index("ix_entity_links_a", "entity_links", ["entity_id_a"])
    op.create_index("ix_entity_links_b", "entity_links", ["entity_id_b"])
    op.create_index("ix_entity_links_type", "entity_links", ["link_type"])

    # ---- clusters ---------------------------------------------------------
    op.create_table(
        "clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", cluster_status, nullable=False, server_default="pending"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_clusters_status", "clusters", ["status"])

    # ---- cluster_members --------------------------------------------------
    op.create_table(
        "cluster_members",
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_cluster_members_entity", "cluster_members", ["entity_id"])

    # ---- audit_log --------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor", audit_actor, nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column(
            "detail_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # ---- Append-only enforcement for audit_log ----------------------------
    # Makes the "append-only" guarantee a database property rather than a
    # convention future code could quietly break.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ringsentinel_audit_log_append_only()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_log is append-only; % is not permitted', TG_OP;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION ringsentinel_audit_log_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION ringsentinel_audit_log_append_only();
        """
    )

    # ---- Ground-truth-free view for the detector --------------------------
    # Detection code (Phase 3) must read this view, never the base table, so the
    # synthetic ring label cannot leak into the model being evaluated.
    op.execute(
        """
        CREATE VIEW v_transactions_detector AS
        SELECT
            id,
            razorpay_order_id,
            customer_entity_id,
            device_entity_id,
            address_entity_id,
            instrument_entity_id,
            amount,
            currency,
            created_at
        FROM transactions;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_transactions_detector;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON audit_log;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update_delete ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS ringsentinel_audit_log_append_only();")

    op.drop_table("audit_log")
    op.drop_table("cluster_members")
    op.drop_table("clusters")
    op.drop_table("entity_links")
    op.drop_table("transactions")
    op.drop_table("entities")

    bind = op.get_bind()
    for enum_name in ("audit_actor", "cluster_status", "link_type", "entity_type"):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
