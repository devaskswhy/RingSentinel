"""Detector configuration. THIS IS THE TUNING SURFACE.

Every threshold, weight, and cut-off the detector uses lives here as a named
constant. Nothing numeric should be buried in the scoring code - when these get
calibrated against the held-out rings in Phase 6, this file is the only thing
that should need to change.

`DETECTOR_VERSION` is stamped onto every cluster row. Bump it whenever a value
below changes, so results produced under different settings stay distinguishable
in the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DETECTOR_VERSION = "0.4.0"


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

#: A cluster needs at least this many DISTINCT CUSTOMER accounts to be worth
#: reviewing. Two accounts sharing something is a coincidence; three is a
#: pattern. This is the single biggest lever on false-positive volume.
MIN_CLUSTER_CUSTOMERS = 3

#: Connected components larger than this are split with community detection.
#: Without this, one popular shared attribute can chain half the graph into a
#: single useless "cluster". Not hit by the current corpus, but a real graph
#: will hit it constantly.
MAX_COMPONENT_CUSTOMERS = 40

#: Resolution passed to Louvain when splitting an oversized component. Higher
#: values produce smaller, tighter communities.
COMMUNITY_RESOLUTION = 1.15

#: Attributes touched by more than this fraction of ALL customers in the graph
#: are treated as infrastructure, not evidence (a shared corporate proxy, a
#: warehouse return address). They are dropped before clustering so they cannot
#: chain unrelated accounts together.
HUB_ATTRIBUTE_CUSTOMER_FRACTION = 0.05

#: ...but never below this absolute floor. On a small graph the fraction alone is
#: dangerous: 5% of 173 accounts is 8, which would classify a genuine 9-account
#: ring pivot as "infrastructure" and delete the very evidence we want. Real
#: rings here run 3-9 accounts, so the floor sits well clear of them and the
#: percentage only takes over once the graph is large enough for it to mean
#: something.
HUB_ATTRIBUTE_MIN_CUSTOMERS = 25


# ---------------------------------------------------------------------------
# Attribute reuse signal
# ---------------------------------------------------------------------------

#: How much each attribute type counts as evidence of coordination.
#:
#: The ordering is the whole point: sharing a payment instrument or a device
#: fingerprint is hard to explain innocently, whereas a shared delivery address
#: is a household, a student hostel, or an office postroom far more often than
#: it is a fraud ring. Address alone must not be enough to flag a cluster.
ATTRIBUTE_WEIGHTS: dict[str, float] = {
    "instrument": 1.00,
    "device": 0.85,
    "address": 0.40,
}

#: Saturation constant for reuse strength f(k) = (k-1)/(k-1+K), where k is the
#: number of distinct customers sharing one attribute. Lower K saturates faster.
#:   K=2 ->  k=2:0.33  k=3:0.50  k=4:0.60  k=5:0.67  k=7:0.75  k=9:0.80
REUSE_SATURATION_K = 2.0

#: An attribute must be touched by at least this many distinct customers before
#: it counts toward the reuse signal.
#:
#: Three, not two. Two accounts on one card is a couple; the corpus is full of
#: such pairs and they are mostly benign. Worse, the soft-OR combination lets
#: many weak pairs accumulate into a strong-looking score - five unrelated pairs
#: is a completely different (and far less suspicious) pattern than five accounts
#: on a single card. Pairs are still recorded in the evidence, they just do not
#: drive the score.
MIN_CUSTOMERS_PER_SHARED_ATTRIBUTE = 3


# ---------------------------------------------------------------------------
# Timing / cadence
# ---------------------------------------------------------------------------

#: A customer needs this many transactions (so this many gaps) before their
#: timing is worth measuring at all.
MIN_TRANSACTIONS_FOR_TIMING = 3

#: A cluster needs this many customers with usable timing before we are willing
#: to make a cadence call.
MIN_CUSTOMERS_FOR_CADENCE = 2

#: Coefficient of variation of inter-transaction gaps at or below this is
#: metronomic - the hallmark of a script. Measured on the seeded corpus: agent
#: rings sit near 0.06, human rings near 1.9.
AGENT_CV_MAX = 0.50

#: ...and the gaps must also be fast. Both conditions must hold, so a slow but
#: regular cron job is not mistaken for a human, nor vice versa.
AGENT_MEDIAN_GAP_MAX_SECONDS = 30.0

#: Irregular enough to look like a person making decisions.
HUMAN_CV_MIN = 0.90

#: Or simply slow enough that no script is implied.
HUMAN_MEDIAN_GAP_MIN_SECONDS = 60.0

#: How many orders of magnitude faster than the population baseline a cluster
#: must be for the velocity signal to reach 1.0.
#:
#: Four, because the baseline median gap is ~32 hours (normal shoppers buy every
#: few days) while any burst is measured in seconds. At 2.0 decades essentially
#: every cluster saturated at 1.0 and the signal stopped discriminating.
VELOCITY_DECADES = 4.0

#: How the two timing components combine into one signal.
#:
#: Regularity carries the weight because it is what actually separates a script
#: from a person: measured on this corpus, agent rings sit at CV 0.04, human
#: rings at 0.96, and the population baseline at 0.76. Velocity, by contrast,
#: mostly measures "is this account busy", which benign heavy shoppers also are.
#: Taking max() of the two let velocity drown out regularity entirely.
TIMING_REGULARITY_SHARE = 0.80
TIMING_VELOCITY_SHARE = 0.20


# ---------------------------------------------------------------------------
# Score composition
# ---------------------------------------------------------------------------

#: Weights must sum to 1.0 (asserted below).
#:
#: Attribute reuse is the backbone - it is what makes a ring a ring. Timing
#: regularity is a strong secondary signal that specifically catches automated
#: rings; human-cadence rings score near zero on it by design and must still be
#: caught by attribute reuse alone. Concentration guards against clusters whose
#: sharing is incidental to their overall activity.
#: A fourth signal, account shallowness, was added after the first evaluation.
#: Without it the weakest true ring (promo farming on a shared address, 0.270)
#: and the strongest benign cluster (a household trio on one device, 0.250) sat
#: 0.02 apart - a gap far too narrow to put a threshold through without simply
#: fitting noise. Shallowness separates them structurally instead: sock puppets
#: exist to place one discounted order, real people sharing a device do not.
WEIGHT_ATTRIBUTE_REUSE = 0.45
WEIGHT_TIMING_REGULARITY = 0.25
WEIGHT_CONCENTRATION = 0.15
WEIGHT_ACCOUNT_SHALLOWNESS = 0.15

#: An account with at most this many transactions is "shallow" - consistent with
#: a sock puppet created to claim one first-order discount, rather than a real
#: customer with a history.
SHALLOW_ACCOUNT_MAX_TRANSACTIONS = 3

#: Clusters scoring below this are not persisted.
#:
#: Chosen from the threshold sweep on the tuning split, not guessed. Every value
#: in [0.25, 0.35] yields 8/8 rings with zero false flags; below 0.25 a benign
#: household cluster creeps in, above 0.35 the two weakest rings drop out. 0.30
#: is the centre of that plateau, so it has the most room on both sides before
#: behaviour changes - which is what should survive contact with the held-out
#: rings in Phase 6.
#:
#: Measured margin at 0.30: weakest true ring 0.371, strongest benign cluster
#: below 0.25.
SCORE_THRESHOLD = 0.30


@dataclass(frozen=True)
class DetectorConfig:
    """Bundles the tunables so a run can override them without global edits."""

    min_cluster_customers: int = MIN_CLUSTER_CUSTOMERS
    max_component_customers: int = MAX_COMPONENT_CUSTOMERS
    community_resolution: float = COMMUNITY_RESOLUTION
    hub_attribute_customer_fraction: float = HUB_ATTRIBUTE_CUSTOMER_FRACTION
    hub_attribute_min_customers: int = HUB_ATTRIBUTE_MIN_CUSTOMERS

    attribute_weights: dict[str, float] = field(
        default_factory=lambda: dict(ATTRIBUTE_WEIGHTS)
    )
    reuse_saturation_k: float = REUSE_SATURATION_K
    min_customers_per_shared_attribute: int = MIN_CUSTOMERS_PER_SHARED_ATTRIBUTE

    min_transactions_for_timing: int = MIN_TRANSACTIONS_FOR_TIMING
    min_customers_for_cadence: int = MIN_CUSTOMERS_FOR_CADENCE
    agent_cv_max: float = AGENT_CV_MAX
    agent_median_gap_max_seconds: float = AGENT_MEDIAN_GAP_MAX_SECONDS
    human_cv_min: float = HUMAN_CV_MIN
    human_median_gap_min_seconds: float = HUMAN_MEDIAN_GAP_MIN_SECONDS
    velocity_decades: float = VELOCITY_DECADES
    timing_regularity_share: float = TIMING_REGULARITY_SHARE
    timing_velocity_share: float = TIMING_VELOCITY_SHARE

    weight_attribute_reuse: float = WEIGHT_ATTRIBUTE_REUSE
    weight_timing_regularity: float = WEIGHT_TIMING_REGULARITY
    weight_concentration: float = WEIGHT_CONCENTRATION
    weight_account_shallowness: float = WEIGHT_ACCOUNT_SHALLOWNESS
    shallow_account_max_transactions: int = SHALLOW_ACCOUNT_MAX_TRANSACTIONS

    score_threshold: float = SCORE_THRESHOLD
    version: str = DETECTOR_VERSION

    def __post_init__(self) -> None:
        total = (
            self.weight_attribute_reuse
            + self.weight_timing_regularity
            + self.weight_concentration
            + self.weight_account_shallowness
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"score weights must sum to 1.0, got {total}")
