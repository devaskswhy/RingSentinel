"""How unusual is this attribute, in this population?

The reuse signal scored an attribute on an absolute curve —
`f(k) = (k-1)/(k-1+2)` — calibrated on a corpus where three accounts on one
card is remarkable. Run against real payment data that assumption collapses:
IEEE-CIS clusters run 50 to 282 accounts, every attribute saturates the signal
at 1.00, every cluster scores about 0.72, and the detector flagged 98% of the
dataset with a lift of 1.01x. The measurement is in `scripts/evaluate_ieee.py`
and was committed before this module existed.

The diagnosis: **k accounts on one card means nothing until you know what k
usually is here.** Fifty accounts is damning where the median is two and
unremarkable where the median is forty. So an attribute is now scored against
the observed distribution of its own type, in the graph being scored, rather
than against a constant chosen on one corpus.

Rarity is the empirical exceedance complement: `1 - P(count >= k)` among
attributes of the same type. It needs no fitted distribution and no new
constant, and it is computed per run, so a merchant whose customers genuinely
share devices gets a different baseline than one whose customers do not.

⚠ Rarity is a MULTIPLIER on the existing strength, never a replacement.
An attribute must be BOTH structurally significant (enough accounts to be
evidence at all) AND unusual for its population. Rarity alone would make a
two-account attribute look damning in a population of singletons; saturation
alone is what failed on real data. The product requires both.

This reads only graph structure — never labels, never the evaluation package.
"""

from __future__ import annotations

import uuid
from bisect import bisect_left
from dataclasses import dataclass, field

import networkx as nx

ATTRIBUTE_TYPES = ("device", "address", "instrument")


@dataclass
class AttributePopulation:
    """Per-type distribution of how many accounts touch one attribute."""

    #: attribute type -> sorted list of account counts, one entry per attribute
    counts: dict[str, list[int]] = field(default_factory=dict)

    def median(self, kind: str) -> float:
        c = self.counts.get(kind) or []
        if not c:
            return 0.0
        mid = len(c) // 2
        return float(c[mid] if len(c) % 2 else (c[mid - 1] + c[mid]) / 2)

    def rarity(self, kind: str, k: int) -> float:
        """1 - P(count >= k) among attributes of this type.

        Returns 1.0 when the type has no population to compare against, so a
        graph too small to have a distribution falls back to the absolute
        behaviour rather than silently scoring everything as unremarkable.
        """
        c = self.counts.get(kind)
        if not c:
            return 1.0
        # counts is sorted ascending; everything from the first index >= k
        # onwards is an attribute at least as shared as this one.
        at_or_above = len(c) - bisect_left(c, k)
        if at_or_above <= 0:
            return 1.0
        return 1.0 - (at_or_above / len(c))

    def describe(self, kind: str) -> str:
        c = self.counts.get(kind) or []
        if not c:
            return f"{kind}: no population"
        return (
            f"{kind}: {len(c)} attributes, median {self.median(kind):.0f} "
            f"accounts, max {c[-1]}"
        )


def build_population(
    graph: nx.Graph, node_type: dict[uuid.UUID, str]
) -> AttributePopulation:
    """Count accounts per attribute across the WHOLE graph, not per cluster.

    Whole-graph on purpose: the question is whether this attribute is unusual
    for the merchant, and a within-cluster comparison would be circular — the
    cluster exists *because* the attribute is shared.
    """
    pop = AttributePopulation(counts={k: [] for k in ATTRIBUTE_TYPES})

    # Iterate the GRAPH, not node_type: hub-filtered attributes are dropped
    # from the graph but stay in node_type, and asking networkx for a node it
    # no longer holds raises rather than returning empty.
    for node in graph.nodes:
        kind = node_type.get(node)
        if kind not in ATTRIBUTE_TYPES:
            continue
        accounts = sum(
            1 for n in graph.neighbors(node) if node_type.get(n) == "customer"
        )
        if accounts:
            pop.counts[kind].append(accounts)

    for kind in pop.counts:
        pop.counts[kind].sort()
    return pop
