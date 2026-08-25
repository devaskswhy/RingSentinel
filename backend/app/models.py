"""RingSentinel entity-graph schema.

Design notes
------------
The product detects *coordinated rings*, not bad single transactions. The core
idea is a graph: accounts (customer entities) become connected when they share a
device, address, or payment instrument. Detection (Phase 3) reads `entity_links`
into NetworkX and looks for dense components.

Ground-truth isolation
----------------------
`transactions.is_synthetic_ring_id` is an evaluation label ONLY. The detector
must never read it, or the benchmark is meaningless. The migration also creates
a view (`v_transactions_detector`) that omits the column; detection code should
query that view so the guarantee is enforced by the database, not by discipline.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Enums (created as native Postgres ENUM types)
# --------------------------------------------------------------------------


class EntityType(str, enum.Enum):
    customer = "customer"
    device = "device"
    instrument = "instrument"
    address = "address"


class LinkType(str, enum.Enum):
    shared_device = "shared_device"
    shared_address = "shared_address"
    shared_instrument = "shared_instrument"


class ClusterStatus(str, enum.Enum):
    pending = "pending"
    cleared = "cleared"
    dismissed = "dismissed"
    needs_review = "needs_review"


class AuditActor(str, enum.Enum):
    system = "system"
    claude = "claude"
    human = "human"


entity_type_enum = SAEnum(EntityType, name="entity_type", native_enum=True)
link_type_enum = SAEnum(LinkType, name="link_type", native_enum=True)
cluster_status_enum = SAEnum(ClusterStatus, name="cluster_status", native_enum=True)
audit_actor_enum = SAEnum(AuditActor, name="audit_actor", native_enum=True)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class Entity(Base):
    """A node in the fraud graph: an account, device, instrument, or address."""

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[EntityType] = mapped_column(entity_type_enum, nullable=False)

    # NOTE: addition beyond the original brief. Without a natural key there is no
    # way to recognise that two transactions used the *same* device/address/card,
    # which is the entire basis of ring detection. Store a hash or opaque token
    # here (device fingerprint, normalised address hash, Razorpay token) - never
    # a raw card number or raw PII.
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("type", "external_ref", name="uq_entities_type_external_ref"),
        Index("ix_entities_type", "type"),
    )


class EntityLink(Base):
    """An undirected edge asserting two entities share an attribute.

    One row per (pair, link_type, transaction) observation, so repeated
    co-occurrence naturally becomes edge weight when the graph is built.
    """

    __tablename__ = "entity_links"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_id_a: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id_b: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[LinkType] = mapped_column(link_type_enum, nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Canonical ordering keeps each undirected edge stored exactly one way.
        CheckConstraint(
            "entity_id_a < entity_id_b", name="ck_entity_links_canonical_order"
        ),
        UniqueConstraint(
            "entity_id_a",
            "entity_id_b",
            "link_type",
            "transaction_id",
            name="uq_entity_links_observation",
        ),
        Index("ix_entity_links_a", "entity_id_a"),
        Index("ix_entity_links_b", "entity_id_b"),
        Index("ix_entity_links_type", "link_type"),
    )


class Transaction(Base):
    """A Razorpay TEST-MODE order, resolved into its four entities."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    razorpay_order_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )

    customer_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    address_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    instrument_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # Minor units (paise), matching the Razorpay API. Never a float.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="INR"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # GROUND TRUTH - evaluation only. The detector must never read this column.
    # Query v_transactions_detector from detection code instead.
    is_synthetic_ring_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_transactions_amount_non_negative"),
        Index("ix_transactions_customer", "customer_entity_id"),
        Index("ix_transactions_created_at", "created_at"),
    )


class Cluster(Base):
    """A candidate fraud ring surfaced by the detector, awaiting human review."""

    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[ClusterStatus] = mapped_column(
        cluster_status_enum, nullable=False, server_default=ClusterStatus.pending.value
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_clusters_status", "status"),)


class ClusterMember(Base):
    """Which entities belong to a cluster.

    NOTE: addition beyond the original brief - `clusters` alone has no way to
    reference the entities it flags, so a cluster could not be reviewed.
    """

    __tablename__ = "cluster_members"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (Index("ix_cluster_members_entity", "entity_id"),)


class AuditLog(Base):
    """Append-only record of every action taken by system, Claude, or a human.

    UPDATE/DELETE/TRUNCATE are blocked by a database trigger created in the
    migration - the append-only property is enforced by Postgres, not by policy.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[AuditActor] = mapped_column(audit_actor_enum, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )
