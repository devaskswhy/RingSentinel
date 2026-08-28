"""Load the entity graph out of Postgres into NetworkX.

Ground-truth isolation
----------------------
Every query here reads `v_transactions_detector`, never the `transactions` base
table. The view does not contain `is_synthetic_ring_id`, so the detector cannot
see evaluation labels even by accident - CLAUDE.md invariant #4 is enforced by
the database rather than by care.

Split selection is NOT a detector concern. When the caller wants to restrict a
run (for example, to the tuning split), it passes an opaque set of transaction
ids to exclude. The detector has no idea why those ids are excluded and never
learns what split anything belongs to.

Graph shape
-----------
Bipartite: customer entities on one side, attribute entities (device, address,
instrument) on the other. An edge means "this customer was observed using this
attribute", weighted by how many transactions made that observation. A ring
shows up as several customer nodes converging on one attribute node.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import networkx as nx
from sqlalchemy import text
from sqlalchemy.orm import Session

from detection.config import DetectorConfig

ATTRIBUTE_TYPES = ("device", "address", "instrument")

#: link_type -> the attribute entity type it connects a customer to.
LINK_TO_ATTRIBUTE = {
    "shared_device": "device",
    "shared_address": "address",
    "shared_instrument": "instrument",
}


@dataclass
class GraphBundle:
    """The graph plus the side data the scorer needs."""

    graph: nx.Graph
    #: entity id -> ("customer" | "device" | "address" | "instrument")
    node_type: dict[uuid.UUID, str]
    #: entity id -> external_ref, for human-readable evidence
    node_ref: dict[uuid.UUID, str]
    #: customer entity id -> sorted transaction timestamps
    customer_timestamps: dict[uuid.UUID, list[datetime]]
    #: attribute entities dropped as hubs, with the reason
    dropped_hubs: list[dict] = field(default_factory=list)
    total_customers: int = 0
    total_transactions: int = 0

    def customers(self) -> list[uuid.UUID]:
        return [n for n, t in self.node_type.items() if t == "customer"]


def _exclusion_clause(param: str, excluded: set[uuid.UUID] | None) -> str:
    if not excluded:
        return ""
    return f" AND NOT (t.id = ANY(:{param}))"


def load_graph(
    db: Session,
    config: DetectorConfig | None = None,
    exclude_transaction_ids: set[uuid.UUID] | None = None,
) -> GraphBundle:
    """Build the NetworkX graph from entity_links.

    `exclude_transaction_ids` is applied opaquely - see the module docstring.
    """
    config = config or DetectorConfig()
    excluded = set(exclude_transaction_ids or ())
    params: dict = {}
    if excluded:
        params["excluded"] = [str(x) for x in excluded]

    # ---- entities -------------------------------------------------------
    entity_rows = db.execute(
        text("SELECT id, type::text AS type, external_ref FROM entities")
    ).all()
    node_type = {row.id: row.type for row in entity_rows}
    node_ref = {row.id: row.external_ref for row in entity_rows}

    # ---- edges, weighted by observation count ---------------------------
    edge_sql = f"""
        SELECT el.entity_id_a,
               el.entity_id_b,
               el.link_type::text AS link_type,
               count(*)           AS weight
        FROM entity_links el
        JOIN v_transactions_detector t ON t.id = el.transaction_id
        WHERE TRUE{_exclusion_clause("excluded", excluded)}
        GROUP BY 1, 2, 3
    """
    edge_rows = db.execute(text(edge_sql), params).all()

    graph = nx.Graph()
    for entity_id, kind in node_type.items():
        graph.add_node(entity_id, type=kind, external_ref=node_ref[entity_id])

    for row in edge_rows:
        a, b = row.entity_id_a, row.entity_id_b
        type_a, type_b = node_type.get(a), node_type.get(b)
        if type_a is None or type_b is None:
            continue

        # Orient the edge so we always know which end is the account.
        if type_a == "customer":
            customer, attribute = a, b
        elif type_b == "customer":
            customer, attribute = b, a
        else:
            # Attribute-to-attribute edges are not produced by the current
            # ingest, but skipping them keeps this robust if that changes.
            continue

        graph.add_edge(
            customer,
            attribute,
            weight=int(row.weight),
            link_type=row.link_type,
            attribute_type=LINK_TO_ATTRIBUTE.get(row.link_type, "unknown"),
        )

    # ---- per-customer timing --------------------------------------------
    ts_sql = f"""
        SELECT t.customer_entity_id AS customer_id, t.created_at
        FROM v_transactions_detector t
        WHERE TRUE{_exclusion_clause("excluded", excluded)}
        ORDER BY t.customer_entity_id, t.created_at
    """
    customer_timestamps: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    total_transactions = 0
    for row in db.execute(text(ts_sql), params):
        customer_timestamps[row.customer_id].append(row.created_at)
        total_transactions += 1

    bundle = GraphBundle(
        graph=graph,
        node_type=node_type,
        node_ref=node_ref,
        customer_timestamps=dict(customer_timestamps),
        total_customers=sum(1 for t in node_type.values() if t == "customer"),
        total_transactions=total_transactions,
    )

    _drop_hub_attributes(bundle, config)
    _drop_isolated_nodes(bundle)
    return bundle


def _drop_hub_attributes(bundle: GraphBundle, config: DetectorConfig) -> None:
    """Remove attributes so widely used that they are infrastructure, not evidence.

    A corporate proxy IP, a marketplace warehouse return address, or a shared
    prepaid BIN would otherwise chain thousands of unrelated accounts into one
    meaningless component. Anything touched by more than
    `hub_attribute_customer_fraction` of all accounts is dropped, and recorded so
    the decision is visible rather than silent.
    """
    if bundle.total_customers == 0:
        return

    # The absolute floor is what keeps a genuine 9-account ring pivot from being
    # written off as infrastructure on a small graph; the percentage only takes
    # over once the population is large enough for it to be meaningful.
    limit = max(
        config.hub_attribute_min_customers,
        int(bundle.total_customers * config.hub_attribute_customer_fraction),
    )

    to_drop = []
    for node, kind in bundle.node_type.items():
        if kind not in ATTRIBUTE_TYPES or node not in bundle.graph:
            continue
        degree = bundle.graph.degree(node)
        if degree > limit:
            to_drop.append((node, kind, degree))

    for node, kind, degree in to_drop:
        bundle.graph.remove_node(node)
        bundle.dropped_hubs.append(
            {
                "entity_id": str(node),
                "type": kind,
                "external_ref": bundle.node_ref.get(node, ""),
                "customer_degree": degree,
                "reason": (
                    f"touched by {degree} accounts, above the hub limit of {limit} "
                    f"({config.hub_attribute_customer_fraction:.0%} of "
                    f"{bundle.total_customers} accounts); treated as shared "
                    "infrastructure rather than evidence"
                ),
            }
        )


def _drop_isolated_nodes(bundle: GraphBundle) -> None:
    """Drop nodes with no edges - they cannot be part of any cluster."""
    isolated = [n for n in bundle.graph.nodes if bundle.graph.degree(n) == 0]
    bundle.graph.remove_nodes_from(isolated)
