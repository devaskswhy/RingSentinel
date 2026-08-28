"""Ingestion pipeline: Razorpay event -> entity graph.

This is the ONLY path by which transactions enter the database. The generator
never writes to Postgres directly; it creates real Razorpay records and the
resulting events flow through here. That keeps the seeding path and the
production path identical.

Graph shape
-----------
Edges are bipartite: each order links its **customer** entity to each attribute
entity it touched.

    customer --shared_device------> device
    customer --shared_address-----> address
    customer --shared_instrument--> instrument

A ring therefore appears as many customer nodes converging on one attribute
node, and NetworkX connected components (Phase 3) recover it directly. Storing
customer-to-customer edges instead would leave device/address/instrument nodes
isolated and make `cluster_members` meaningless.

Idempotency
-----------
Re-delivering the same event is a no-op: `transactions.razorpay_order_id` is
unique and `entity_links` is unique on (pair, link_type, transaction). Razorpay
retries webhooks, so this is a correctness requirement, not a nicety.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    AuditActor,
    AuditLog,
    Entity,
    EntityLink,
    EntityType,
    LinkType,
    Transaction,
)

log = logging.getLogger(__name__)

SUPPORTED_EVENTS = ("payment.captured", "order.paid")

#: Which attribute note maps to which entity type and edge label.
_ATTRIBUTE_MAP: tuple[tuple[str, EntityType, LinkType, str], ...] = (
    ("rs_device_ref", EntityType.device, LinkType.shared_device, "device_entity_id"),
    ("rs_address_ref", EntityType.address, LinkType.shared_address, "address_entity_id"),
    (
        "rs_instrument_ref",
        EntityType.instrument,
        LinkType.shared_instrument,
        "instrument_entity_id",
    ),
)


class IngestError(ValueError):
    """The event could not be turned into graph data."""


@dataclass
class IngestResult:
    order_id: str
    transaction_id: uuid.UUID | None
    created: bool
    entities_created: int
    links_created: int
    reason: str = ""


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def _entity_payload(event: dict[str, Any], name: str) -> dict[str, Any] | None:
    node = event.get("payload", {}).get(name)
    if isinstance(node, dict):
        inner = node.get("entity")
        if isinstance(inner, dict):
            return inner
    return None


def extract_facts(event: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we need out of a payment.captured / order.paid envelope.

    Notes are looked for on the order first, then the payment - Razorpay copies
    order notes onto the payment in most flows, but not all.
    """
    order = _entity_payload(event, "order")
    payment = _entity_payload(event, "payment")

    if order is None and payment is None:
        raise IngestError("event payload contained neither an order nor a payment")

    notes: dict[str, Any] = {}
    for source in (order, payment):
        if source and isinstance(source.get("notes"), dict):
            merged = dict(source["notes"])
            merged.update(notes)  # order notes win
            notes = merged

    order_id = None
    if order:
        order_id = order.get("id")
    if not order_id and payment:
        order_id = payment.get("order_id")
    if not order_id:
        raise IngestError("could not determine a Razorpay order id from the event")

    amount = None
    for source in (order, payment):
        if source and source.get("amount") is not None:
            amount = source["amount"]
            break
    if amount is None:
        raise IngestError(f"no amount present on event for order {order_id}")

    currency = (order or payment or {}).get("currency") or "INR"

    # Prefer the synthetic event time carried in notes; fall back to Razorpay's
    # own created_at for genuinely externally-originated events.
    occurred_at = _resolve_timestamp(notes, order, payment)

    return {
        "order_id": str(order_id),
        "amount": int(amount),
        "currency": str(currency)[:3],
        "notes": notes,
        "occurred_at": occurred_at,
        "payment_id": (payment or {}).get("id"),
    }


def _resolve_timestamp(
    notes: dict[str, Any],
    order: dict[str, Any] | None,
    payment: dict[str, Any] | None,
) -> datetime:
    raw = notes.get("rs_occurred_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            log.warning("unparseable rs_occurred_at note: %r", raw)

    for source in (order, payment):
        if source and source.get("created_at"):
            return datetime.fromtimestamp(int(source["created_at"]), tz=timezone.utc)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


def get_or_create_entity(
    db: Session, entity_type: EntityType, external_ref: str, first_seen_at: datetime
) -> tuple[uuid.UUID, bool]:
    """Resolve (type, external_ref) to an entity id, creating it if new.

    Uses ON CONFLICT DO NOTHING against the unique (type, external_ref) index so
    concurrent webhook deliveries cannot create duplicates.
    """
    stmt = (
        pg_insert(Entity)
        .values(
            id=uuid.uuid4(),
            type=entity_type,
            external_ref=external_ref,
            first_seen_at=first_seen_at,
        )
        .on_conflict_do_nothing(index_elements=["type", "external_ref"])
        .returning(Entity.id)
    )
    created_id = db.execute(stmt).scalar()
    if created_id is not None:
        return created_id, True

    existing = db.execute(
        select(Entity.id).where(
            Entity.type == entity_type, Entity.external_ref == external_ref
        )
    ).scalar_one()
    return existing, False


def _link(
    db: Session,
    a: uuid.UUID,
    b: uuid.UUID,
    link_type: LinkType,
    transaction_id: uuid.UUID,
    created_at: datetime,
) -> bool:
    """Insert one undirected edge, honouring the canonical a < b ordering."""
    if a == b:
        return False
    lo, hi = (a, b) if str(a) < str(b) else (b, a)

    stmt = (
        pg_insert(EntityLink)
        .values(
            id=uuid.uuid4(),
            entity_id_a=lo,
            entity_id_b=hi,
            link_type=link_type,
            transaction_id=transaction_id,
            created_at=created_at,
        )
        .on_conflict_do_nothing(
            index_elements=[
                "entity_id_a",
                "entity_id_b",
                "link_type",
                "transaction_id",
            ]
        )
        .returning(EntityLink.id)
    )
    return db.execute(stmt).scalar() is not None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def ingest_event(db: Session, event: dict[str, Any]) -> IngestResult:
    """Turn one Razorpay webhook event into entities, links, and a transaction."""
    event_name = event.get("event", "")
    if event_name not in SUPPORTED_EVENTS:
        raise IngestError(f"unsupported event type: {event_name!r}")

    facts = extract_facts(event)
    notes = facts["notes"]
    order_id = facts["order_id"]
    occurred_at = facts["occurred_at"]

    customer_ref = notes.get("rs_customer_ref")
    if not customer_ref:
        raise IngestError(
            f"order {order_id} carries no rs_customer_ref note; cannot place it "
            "in the graph"
        )

    # Already ingested? Webhook redelivery is normal and must be a no-op.
    existing = db.execute(
        select(Transaction.id).where(Transaction.razorpay_order_id == order_id)
    ).scalar()
    if existing is not None:
        return IngestResult(order_id, existing, False, 0, 0, "already ingested")

    entities_created = 0

    customer_id, was_new = get_or_create_entity(
        db, EntityType.customer, str(customer_ref), occurred_at
    )
    entities_created += int(was_new)

    attribute_ids: dict[str, uuid.UUID | None] = {
        "device_entity_id": None,
        "address_entity_id": None,
        "instrument_entity_id": None,
    }
    edges: list[tuple[uuid.UUID, LinkType]] = []

    for note_key, entity_type, link_type, column in _ATTRIBUTE_MAP:
        ref = notes.get(note_key)
        if not ref:
            continue
        entity_id, was_new = get_or_create_entity(
            db, entity_type, str(ref), occurred_at
        )
        entities_created += int(was_new)
        attribute_ids[column] = entity_id
        edges.append((entity_id, link_type))

    # Ground truth. Written here, never read by detection code, which queries
    # v_transactions_detector instead.
    ring_label = notes.get("rs_ring_label")

    transaction_id = uuid.uuid4()
    insert_txn = (
        pg_insert(Transaction)
        .values(
            id=transaction_id,
            razorpay_order_id=order_id,
            customer_entity_id=customer_id,
            device_entity_id=attribute_ids["device_entity_id"],
            address_entity_id=attribute_ids["address_entity_id"],
            instrument_entity_id=attribute_ids["instrument_entity_id"],
            amount=facts["amount"],
            currency=facts["currency"],
            created_at=occurred_at,
            is_synthetic_ring_id=str(ring_label) if ring_label else None,
        )
        .on_conflict_do_nothing(index_elements=["razorpay_order_id"])
        .returning(Transaction.id)
    )
    inserted = db.execute(insert_txn).scalar()
    if inserted is None:
        # Lost a race with a concurrent delivery of the same event.
        existing = db.execute(
            select(Transaction.id).where(Transaction.razorpay_order_id == order_id)
        ).scalar()
        return IngestResult(order_id, existing, False, entities_created, 0, "raced")

    links_created = sum(
        int(_link(db, customer_id, entity_id, link_type, transaction_id, occurred_at))
        for entity_id, link_type in edges
    )

    db.add(
        AuditLog(
            actor=AuditActor.system,
            action="ingest_transaction",
            target_type="transaction",
            target_id=str(transaction_id),
            detail_json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": facts.get("payment_id"),
                "event": event_name,
                "entities_created": entities_created,
                "links_created": links_created,
            },
        )
    )

    return IngestResult(
        order_id, transaction_id, True, entities_created, links_created
    )
