"""Generator configuration.

Everything that controls the shape of the synthetic corpus lives here so the
archetype functions stay about *behaviour* rather than about magic numbers.

Reproducibility
---------------
`RANDOM_SEED` fixes the plan: the same seed always produces the same entities,
amounts, timings, and ring membership. It does NOT fix the Razorpay order ids -
those are assigned by Razorpay at call time and differ on every run. The plan is
reproducible; the external ids are not.

Held-out split
--------------
Rings 1-8 are the tuning set. Rings 9-12 are HELD OUT - see
`HOLDOUT_RING_NUMBERS`. They were sealed through Phase 3 tuning and opened once,
on 2026-08-28, for the evaluation recorded in CLAUDE.md 5b-eval.

They remain off-limits for tuning. Adjusting any threshold to improve a number
on these rings converts them from held-out data into a second tuning set, and
there is no third set to fall back on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RANDOM_SEED = 20260828

# ---------------------------------------------------------------------------
# The six archetypes: 3 fraud patterns x 2 cadence variants.
# ---------------------------------------------------------------------------

PATTERNS = ("card_testing", "promo_farming", "return_abuse")
CADENCES = ("human", "agent")

ARCHETYPES: tuple[str, ...] = tuple(
    f"{pattern}:{cadence}" for pattern in PATTERNS for cadence in CADENCES
)

# ---------------------------------------------------------------------------
# Ring layout. 12 rings, one pass over the six archetypes twice.
# Rings are numbered 1..12; 9-12 are held out.
# ---------------------------------------------------------------------------

RING_COUNT = 12
HOLDOUT_RING_NUMBERS: frozenset[int] = frozenset({9, 10, 11, 12})
TUNING_RING_NUMBERS: frozenset[int] = frozenset(range(1, 9))

SPLIT_TUNING = "tuning"
SPLIT_HOLDOUT = "holdout"
SPLIT_NORMAL = "normal"


def split_for_ring(ring_number: int) -> str:
    """Which evaluation split a ring number belongs to."""
    return SPLIT_HOLDOUT if ring_number in HOLDOUT_RING_NUMBERS else SPLIT_TUNING


@dataclass(frozen=True)
class RingSpec:
    """One seeded ring cluster."""

    number: int
    pattern: str
    cadence: str
    account_count: int
    #: How tightly the ring shares its pivot attribute. 1.0 means every account
    #: touches the same shared entity on every order; lower values mean some
    #: orders use a private attribute instead, which thins the graph out.
    density: float

    @property
    def archetype(self) -> str:
        return f"{self.pattern}:{self.cadence}"

    @property
    def split(self) -> str:
        return split_for_ring(self.number)

    @property
    def label(self) -> str:
        """Ground-truth label written to `transactions.is_synthetic_ring_id`.

        Encoded as a single pipe-delimited string because the schema gives us
        exactly one text column for ground truth.
        """
        return f"ring_{self.number:02d}|{self.pattern}|{self.cadence}|{self.split}"


#: Account counts and densities are varied deliberately so the detector has to
#: cope with both blatant and subtle clusters rather than one uniform shape.
RING_SPECS: tuple[RingSpec, ...] = (
    # --- Tuning set: rings 1-8 -------------------------------------------
    RingSpec(1, "card_testing", "human", account_count=4, density=0.95),
    RingSpec(2, "card_testing", "agent", account_count=7, density=1.00),
    RingSpec(3, "promo_farming", "human", account_count=5, density=0.80),
    RingSpec(4, "promo_farming", "agent", account_count=9, density=0.95),
    RingSpec(5, "return_abuse", "human", account_count=3, density=0.70),
    RingSpec(6, "return_abuse", "agent", account_count=6, density=0.90),
    RingSpec(7, "card_testing", "agent", account_count=5, density=0.60),
    RingSpec(8, "promo_farming", "human", account_count=6, density=0.55),
    # --- Held out: rings 9-12. Do not inspect while tuning. ---------------
    RingSpec(9, "card_testing", "human", account_count=6, density=0.85),
    RingSpec(10, "promo_farming", "agent", account_count=8, density=0.75),
    RingSpec(11, "return_abuse", "human", account_count=4, density=0.65),
    RingSpec(12, "return_abuse", "agent", account_count=5, density=0.95),
)


# ---------------------------------------------------------------------------
# Volume targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratorConfig:
    """Top-level knobs for a generation run."""

    seed: int = RANDOM_SEED

    #: Uncorrelated background accounts. These plus ring accounts and their
    #: attribute entities land the entity count near the ~600 target.
    normal_customer_count: int = 105

    #: Background orders placed by normal accounts.
    normal_transaction_count: int = 900

    #: Attribute pools for background traffic. Each pool is sized to exactly the
    #: customer count so every normal account gets its OWN device, address, and
    #: instrument. A pool smaller than the population would make
    #: `index % pool_size` wrap and manufacture systematic accidental sharing -
    #: which would look like rings and make any precision measurement
    #: meaningless. All benign sharing is introduced explicitly and in small
    #: doses by `generator/normal.py`, never as an artefact of pool sizing.
    normal_device_pool: int = 105
    normal_address_pool: int = 105
    normal_instrument_pool: int = 105

    #: Window the corpus spans, ending "now".
    window_days: int = 21

    #: Currency for every order. Integer paise throughout.
    currency: str = "INR"

    ring_specs: tuple[RingSpec, ...] = field(default=RING_SPECS)

    def describe(self) -> str:
        tuning = sum(1 for r in self.ring_specs if r.split == SPLIT_TUNING)
        holdout = sum(1 for r in self.ring_specs if r.split == SPLIT_HOLDOUT)
        return (
            f"seed={self.seed} rings={len(self.ring_specs)} "
            f"(tuning={tuning}, holdout={holdout}) "
            f"normal_customers={self.normal_customer_count} "
            f"normal_transactions={self.normal_transaction_count}"
        )
