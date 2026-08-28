"""Turn the entity graph into candidate clusters.

Connected components are the natural unit: accounts reachable from one another
through shared attributes. That works cleanly when sharing is sparse.

It fails when it is not. One popular attribute is enough to chain thousands of
unrelated accounts into a single component that is useless to review - the
"giant component" problem, and the usual way naive graph fraud detection falls
over in production. Two defences:

  1. `graph.py` drops hub attributes before we get here.
  2. Any component still holding more than `max_component_customers` accounts is
     split into communities with Louvain modularity.

The current corpus never triggers the second path - its components are small and
well separated - but a real merchant graph would hit it immediately, and a
detector that only works on tidy data is not a detector.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import networkx as nx

from detection.config import DetectorConfig
from detection.graph import ATTRIBUTE_TYPES, GraphBundle

#: Fixed seed so Louvain's randomised refinement is reproducible run to run.
LOUVAIN_SEED = 20260828


@dataclass
class CandidateCluster:
    """A connected group of accounts, before scoring."""

    customers: list[uuid.UUID]
    attributes: list[uuid.UUID]
    subgraph: nx.Graph
    #: How this cluster came to exist, for the evidence trail.
    origin: str = "connected_component"
    component_size: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        """Cluster size means ACCOUNTS, not total nodes."""
        return len(self.customers)


def _split_customers_attributes(
    nodes: set[uuid.UUID], bundle: GraphBundle
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    customers, attributes = [], []
    for node in nodes:
        kind = bundle.node_type.get(node)
        if kind == "customer":
            customers.append(node)
        elif kind in ATTRIBUTE_TYPES:
            attributes.append(node)
    return customers, attributes


def find_clusters(
    bundle: GraphBundle, config: DetectorConfig | None = None
) -> list[CandidateCluster]:
    """Find every candidate cluster meeting the minimum account count."""
    config = config or DetectorConfig()
    clusters: list[CandidateCluster] = []

    for component in nx.connected_components(bundle.graph):
        customers, attributes = _split_customers_attributes(component, bundle)

        if len(customers) < config.min_cluster_customers:
            continue

        if len(customers) <= config.max_component_customers:
            clusters.append(
                CandidateCluster(
                    customers=sorted(customers, key=str),
                    attributes=sorted(attributes, key=str),
                    subgraph=bundle.graph.subgraph(component).copy(),
                    origin="connected_component",
                    component_size=len(customers),
                )
            )
            continue

        clusters.extend(
            _refine_oversized_component(component, customers, bundle, config)
        )

    # Biggest first - reviewers care about the widest blast radius.
    clusters.sort(key=lambda c: c.size, reverse=True)
    return clusters


def _refine_oversized_component(
    component: set[uuid.UUID],
    customers: list[uuid.UUID],
    bundle: GraphBundle,
    config: DetectorConfig,
) -> list[CandidateCluster]:
    """Split a giant component into modularity communities.

    Edge weights matter here: an attribute used by two accounts fifty times is a
    stronger tie than one used twice, and Louvain will respect that.
    """
    subgraph = bundle.graph.subgraph(component).copy()

    communities = nx.community.louvain_communities(
        subgraph,
        weight="weight",
        resolution=config.community_resolution,
        seed=LOUVAIN_SEED,
    )

    note = (
        f"component held {len(customers)} accounts, above the "
        f"{config.max_component_customers} limit; split into "
        f"{len(communities)} communities by Louvain modularity "
        f"(resolution {config.community_resolution})"
    )

    refined: list[CandidateCluster] = []
    for community in communities:
        sub_customers, sub_attributes = _split_customers_attributes(community, bundle)
        if len(sub_customers) < config.min_cluster_customers:
            continue
        refined.append(
            CandidateCluster(
                customers=sorted(sub_customers, key=str),
                attributes=sorted(sub_attributes, key=str),
                subgraph=subgraph.subgraph(community).copy(),
                origin="louvain_community",
                component_size=len(customers),
                notes=[note],
            )
        )
    return refined
