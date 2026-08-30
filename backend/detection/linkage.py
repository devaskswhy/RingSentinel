"""How much of this cluster is actually joined together?

Every ring that `scripts/adversarial_cases` got past the detector used the same
move: keep the number of accounts on any ONE attribute at or below the evidence
floor, while linking many accounts overall. Twelve pairs each sharing their own
card is twenty-four coordinated accounts, and `find_shared_attributes` discards
every one of those attributes because `min_customers_per_shared_attribute` is 3.
Attribute reuse then reads near zero and the cluster is not flagged, even though
the clustering step had already joined all twenty-four.

That is the gap this closes. Linkage asks a question the per-attribute signals
structurally cannot: **what fraction of the accounts in this cluster are tied to
another account in it by anything at all**, counting the attributes the evidence
floor throws away.

The floor is not removed — it should stay. Two accounts on one card is weak
evidence and presenting it as a shared attribute would fill the console's
evidence table with noise. Linkage is a separate reading of the same graph:
the floor governs what is shown as evidence, linkage governs what is noticed.

⚠ WHAT THIS DOES NOT FIX, stated because the same run measured it. The two
false positives — a family sharing a card, a device and an address, and a
campus kiosk cohort — score HIGH linkage, because a household is the most
tightly joined thing in any graph. Linkage will make those slightly worse, not
better. It addresses the three missed rings and nothing else, and separating a
household from a crew remains the job of account shallowness and timing.

Reads graph structure only. No labels, no evaluation imports.
"""

from __future__ import annotations

from detection.clustering import CandidateCluster
from detection.graph import GraphBundle

ATTRIBUTE_TYPES = ("device", "address", "instrument")


def linkage_signal(cluster: CandidateCluster, bundle: GraphBundle) -> float:
    """Fraction of the cluster's accounts joined to another by any attribute.

    Counts an attribute as joining accounts at two or more, deliberately below
    the evidence floor. Returns 0.0 for a cluster of one, where the question
    does not arise.
    """
    customers = set(cluster.customers)
    if len(customers) < 2:
        return 0.0

    joined: set = set()
    for attribute in cluster.attributes:
        if bundle.node_type.get(attribute) not in ATTRIBUTE_TYPES:
            continue
        touching = [
            n for n in cluster.subgraph.neighbors(attribute) if n in customers
        ]
        # Two is the point. The evidence floor is three, and everything this
        # signal exists to catch lives underneath it.
        if len(touching) >= 2:
            joined.update(touching)

    return len(joined) / len(customers)
