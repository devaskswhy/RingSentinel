"""Scoring: turn a candidate cluster into a 0-1 suspicion score plus evidence.

Design rule: **no black-box numbers**. Every score decomposes into named signals,
each of which names the specific entities that produced it. The evidence dict
built here is persisted verbatim to `clusters.evidence_json`, so a reviewer -
and Claude, in Phase 4 - can always answer "why was this flagged?" without
re-running anything.

The four signals
----------------
1. **Attribute reuse** (0.45). The backbone. How many distinct accounts funnel
   through the same device, instrument, or address, weighted by how incriminating
   that attribute type is. Sharing a payment instrument is hard to explain
   innocently; sharing a delivery address is a household as often as it is a
   crew, so address carries 0.40 against the instrument's 1.00. This is what
   stops a family from being flagged.

2. **Timing regularity** (0.25). How metronomic and how fast the cluster is
   versus the population baseline. This is what catches automated rings.
   Human-cadence rings score near zero here *by design* and must be caught by
   attribute reuse alone.

3. **Concentration** (0.15). What share of the cluster's total activity actually
   flows through the shared attributes. Guards against clusters whose sharing is
   incidental to everything else they do.

4. **Account shallowness** (0.15). What fraction of the accounts have almost no
   transaction history. Added because the weakest genuine ring (promo farming on
   a shared address) and the strongest benign cluster (a household trio on one
   device) scored 0.02 apart - too narrow to separate with a threshold without
   simply fitting noise. Sock puppets exist to place one discounted order; people
   who genuinely share a device have histories. Weak alone by design: at 0.15 it
   can tip an already-suspicious cluster over the line but never flag one itself.

Signals are combined as a weighted sum rather than a product, so a single strong
signal can still raise a flag without every other signal having to agree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from detection.baseline import (
    ClusterTiming,
    TimingBaseline,
    regularity_signal,
    velocity_signal,
)
from detection.cadence import CadenceCall, classify_cadence
from detection.clustering import CandidateCluster
from detection.config import DetectorConfig
from detection.graph import ATTRIBUTE_TYPES, GraphBundle


@dataclass
class SharedAttribute:
    """One attribute that several accounts in the cluster have in common."""

    entity_id: uuid.UUID
    attribute_type: str
    external_ref: str
    #: Distinct accounts in this cluster touching it.
    customer_count: int
    #: Total transaction observations backing the sharing.
    observations: int
    reuse_strength: float
    type_weight: float
    contribution: float

    def to_dict(self) -> dict:
        return {
            "entity_id": str(self.entity_id),
            "attribute_type": self.attribute_type,
            "external_ref": self.external_ref,
            "customer_count": self.customer_count,
            "observations": self.observations,
            "reuse_strength": round(self.reuse_strength, 3),
            "type_weight": self.type_weight,
            "contribution": round(self.contribution, 3),
        }

    def describe(self) -> str:
        return (
            f"{self.customer_count} accounts share one {self.attribute_type} "
            f"({self.external_ref[:18]}...) across {self.observations} transactions"
        )


@dataclass
class ScoredCluster:
    """A candidate cluster with its score and the reasoning behind it."""

    candidate: CandidateCluster
    score: float
    attribute_reuse: float
    timing_regularity: float
    concentration: float
    account_shallowness: float
    shallow_account_count: int
    shared_attributes: list[SharedAttribute]
    cadence: CadenceCall
    timing: ClusterTiming
    baseline: TimingBaseline
    signal_notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return self.candidate.size

    def top_attributes(self, limit: int = 3) -> list[SharedAttribute]:
        return sorted(
            self.shared_attributes, key=lambda a: a.contribution, reverse=True
        )[:limit]

    def headline(self) -> str:
        """One-line plain-language summary of what drove the score."""
        top = self.top_attributes(2)
        if not top:
            return "no shared attributes above threshold"
        return "; ".join(a.describe() for a in top)

    def to_evidence(self, config: DetectorConfig) -> dict:
        """The full breakdown persisted to clusters.evidence_json."""
        return {
            "detector_version": config.version,
            "score": round(self.score, 4),
            "size": self.size,
            "origin": self.candidate.origin,
            "signals": {
                "attribute_reuse": {
                    "value": round(self.attribute_reuse, 4),
                    "weight": config.weight_attribute_reuse,
                    "weighted": round(
                        self.attribute_reuse * config.weight_attribute_reuse, 4
                    ),
                    "explanation": (
                        "how many distinct accounts share the same device, "
                        "instrument, or address, weighted by attribute type"
                    ),
                },
                "timing_regularity": {
                    "value": round(self.timing_regularity, 4),
                    "weight": config.weight_timing_regularity,
                    "weighted": round(
                        self.timing_regularity * config.weight_timing_regularity, 4
                    ),
                    "explanation": (
                        "how metronomic and how fast this cluster is versus the "
                        "population baseline"
                    ),
                },
                "concentration": {
                    "value": round(self.concentration, 4),
                    "weight": config.weight_concentration,
                    "weighted": round(
                        self.concentration * config.weight_concentration, 4
                    ),
                    "explanation": (
                        "share of the cluster's transaction volume that flows "
                        "through the shared attributes"
                    ),
                },
                "account_shallowness": {
                    "value": round(self.account_shallowness, 4),
                    "weight": config.weight_account_shallowness,
                    "weighted": round(
                        self.account_shallowness * config.weight_account_shallowness,
                        4,
                    ),
                    "shallow_accounts": self.shallow_account_count,
                    "explanation": (
                        (
                            f"{self.shallow_account_count} of {self.size} accounts "
                            f"have at most "
                            f"{config.shallow_account_max_transactions} "
                            "transactions - consistent with sock puppets created "
                            "for a first-order discount rather than customers with "
                            "a history"
                        )
                        if self.shallow_account_count
                        else (
                            f"all {self.size} accounts have more than "
                            f"{config.shallow_account_max_transactions} "
                            "transactions, so none look like throwaway sock "
                            "puppets; this signal contributed nothing"
                        )
                    ),
                },
            },
            "shared_attributes": [a.to_dict() for a in self.shared_attributes],
            "cadence": self.cadence.to_dict(),
            "timing": {
                "cluster_median_gap_seconds": round(
                    self.timing.median_gap_seconds, 2
                ),
                "cluster_cv": round(self.timing.median_coefficient_of_variation, 3),
                "baseline_median_gap_seconds": round(
                    self.baseline.median_gap_seconds, 2
                ),
                "baseline_cv": round(
                    self.baseline.median_coefficient_of_variation, 3
                ),
                "accounts_measured": self.timing.customers_measured,
            },
            "notes": self.signal_notes + self.candidate.notes,
            "headline": self.headline(),
        }


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def _reuse_strength(customer_count: int, config: DetectorConfig) -> float:
    """Saturating f(k) = (k-1)/(k-1+K).

    Saturating matters: the jump from 2 to 4 accounts on one card is far more
    informative than the jump from 20 to 22, and a linear function would let one
    enormous cluster dominate every score in the system.
    """
    k = max(0, customer_count - 1)
    return k / (k + config.reuse_saturation_k)


def find_shared_attributes(
    cluster: CandidateCluster, bundle: GraphBundle, config: DetectorConfig
) -> list[SharedAttribute]:
    """Identify every attribute that multiple accounts in the cluster share."""
    customer_set = set(cluster.customers)
    shared: list[SharedAttribute] = []

    for attribute in cluster.attributes:
        kind = bundle.node_type.get(attribute)
        if kind not in ATTRIBUTE_TYPES:
            continue

        neighbours = [n for n in cluster.subgraph.neighbors(attribute)]
        touching = [n for n in neighbours if n in customer_set]
        if len(touching) < config.min_customers_per_shared_attribute:
            continue

        observations = sum(
            cluster.subgraph[attribute][c].get("weight", 1) for c in touching
        )
        strength = _reuse_strength(len(touching), config)
        weight = config.attribute_weights.get(kind, 0.5)

        shared.append(
            SharedAttribute(
                entity_id=attribute,
                attribute_type=kind,
                external_ref=bundle.node_ref.get(attribute, ""),
                customer_count=len(touching),
                observations=int(observations),
                reuse_strength=strength,
                type_weight=weight,
                contribution=strength * weight,
            )
        )

    return sorted(shared, key=lambda a: a.contribution, reverse=True)


def attribute_reuse_signal(shared: list[SharedAttribute]) -> float:
    """Combine per-attribute contributions with a probabilistic soft-OR.

    1 - prod(1 - c_i). Independent pieces of evidence accumulate - a cluster
    sharing both a card and a device is more suspicious than one sharing either -
    but the result stays bounded in [0, 1] without an arbitrary cap.
    """
    remaining = 1.0
    for attribute in shared:
        remaining *= 1.0 - min(1.0, max(0.0, attribute.contribution))
    return 1.0 - remaining


def concentration_signal(
    cluster: CandidateCluster,
    shared: list[SharedAttribute],
    bundle: GraphBundle,
) -> float:
    """Share of the cluster's transaction volume flowing through shared attributes.

    A cluster where the shared card accounts for most activity is far more
    suspicious than one where it appears in a handful of orders among thousands.
    """
    shared_ids = {a.entity_id for a in shared}
    total = 0
    on_shared = 0

    for u, v, data in cluster.subgraph.edges(data=True):
        weight = data.get("weight", 1)
        total += weight
        if u in shared_ids or v in shared_ids:
            on_shared += weight

    if total == 0:
        return 0.0
    return on_shared / total


def shallowness_signal(
    cluster: CandidateCluster, bundle: GraphBundle, config: DetectorConfig
) -> tuple[float, int]:
    """Fraction of the cluster's accounts that have almost no transaction history.

    Promo-farming crews create accounts to claim one first-order discount each,
    so their accounts are numerous and shallow. A household that genuinely shares
    a device or an address has ordinary order histories behind it. That contrast
    is what separates the two cases structurally, rather than by threading a
    score threshold through a two-point gap.

    Deliberately weak on its own - at weight 0.15 it can tip an already
    suspicious cluster over the line, but can never flag one by itself.
    """
    if not cluster.customers:
        return 0.0, 0

    shallow = 0
    for customer in cluster.customers:
        count = len(bundle.customer_timestamps.get(customer, []))
        if count <= config.shallow_account_max_transactions:
            shallow += 1
    return shallow / len(cluster.customers), shallow


def score_cluster(
    cluster: CandidateCluster,
    bundle: GraphBundle,
    baseline: TimingBaseline,
    config: DetectorConfig,
) -> ScoredCluster:
    """Score one candidate cluster and assemble its evidence."""
    from detection.baseline import cluster_timing

    shared = find_shared_attributes(cluster, bundle, config)
    reuse = attribute_reuse_signal(shared)
    concentration = concentration_signal(cluster, shared, bundle)

    timing = cluster_timing(cluster.customers, bundle.customer_timestamps, config)
    regularity = regularity_signal(timing, baseline)
    velocity = velocity_signal(timing, baseline, config)
    # Regularity dominates. Velocity mostly measures "is this account busy",
    # which benign heavy shoppers also are; regularity is what actually
    # separates a script from a person. Taking max() here let velocity saturate
    # the signal for every cluster and stop it discriminating at all.
    timing_signal = min(
        1.0,
        config.timing_regularity_share * regularity
        + config.timing_velocity_share * velocity,
    )

    cadence = classify_cadence(timing, config)

    shallowness, shallow_count = shallowness_signal(cluster, bundle, config)

    score = (
        config.weight_attribute_reuse * reuse
        + config.weight_timing_regularity * timing_signal
        + config.weight_concentration * concentration
        + config.weight_account_shallowness * shallowness
    )
    score = max(0.0, min(1.0, score))

    notes: list[str] = []
    if not shared:
        notes.append(
            "no attribute met the shared-attribute threshold; accounts are "
            "connected only indirectly"
        )
    if timing.customers_measured == 0:
        notes.append(
            "no account had enough transactions to measure timing, so the "
            "timing signal contributed nothing"
        )
    if shallowness >= 0.6:
        notes.append(
            f"{shallow_count} of {len(cluster.customers)} accounts have almost no "
            "transaction history, which is what sock-puppet farming looks like"
        )
    if regularity > velocity:
        notes.append(
            f"timing signal driven by regularity ({regularity:.2f}) rather than "
            f"raw speed ({velocity:.2f})"
        )
    elif velocity > 0:
        notes.append(
            f"timing signal driven by speed ({velocity:.2f}) rather than "
            f"regularity ({regularity:.2f})"
        )

    return ScoredCluster(
        candidate=cluster,
        score=score,
        attribute_reuse=reuse,
        timing_regularity=timing_signal,
        concentration=concentration,
        account_shallowness=shallowness,
        shallow_account_count=shallow_count,
        shared_attributes=shared,
        cadence=cadence,
        timing=timing,
        baseline=baseline,
        signal_notes=notes,
    )
