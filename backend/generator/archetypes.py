"""The six ring archetypes: 3 fraud patterns x 2 cadence variants.

Each archetype gets its own named function with its tunable constants declared
at the top of the function body, because these are the knobs that get adjusted
while calibrating the detector. Shared mechanics (choosing between a ring's
pivot attribute and an account's private one) live in small helpers so the
behavioural differences stay visible rather than buried in boilerplate.

Every function has the same shape:

    generate_<pattern>_<cadence>(spec, identities, rng, window_end, seq) -> list

What distinguishes the patterns
-------------------------------
card_testing   many low-value orders, a couple of shared instruments, probing
promo_farming  many accounts funnelling into one address/device, discount codes
return_abuse   fewer, larger orders on a shared payout account, high return rate

What distinguishes the cadences
-------------------------------
human  irregular heavy-tailed gaps, diurnal, above human reaction floor
agent  near-uniform sub-second-ish gaps, no diurnal shape, systematic promos
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from random import Random

from generator.cadence import offsets_for, promo_sequence
from generator.config import RingSpec
from generator.identities import RingIdentities
from generator.planned import INTENT_ORDER, INTENT_PAYMENT_LINK, PlannedTransaction

# ---------------------------------------------------------------------------
# Shared mechanics
# ---------------------------------------------------------------------------


def _pivot_or_private(
    rng: Random,
    density: float,
    shared_pool: tuple[str, ...],
    private_value: str,
) -> str:
    """Use the ring's shared attribute, or fall back to a private one.

    `density` is the probability of touching the pivot. Lower density means a
    sparser graph and a genuinely harder cluster to find.
    """
    if shared_pool and rng.random() < density:
        return rng.choice(shared_pool)
    return private_value


def _timestamps(
    cadence: str, rng: Random, count: int, window_end: datetime, window_seconds: float
) -> list[datetime]:
    """Turn cadence offsets into absolute timestamps ending before `window_end`."""
    offsets = offsets_for(cadence, rng, count, window_seconds)
    if not offsets:
        return []
    span = max(offsets) or 1.0
    # Anchor the burst so its last order lands inside the window.
    start = window_end - timedelta(seconds=span + rng.uniform(0, 3600))
    return [start + timedelta(seconds=o) for o in offsets]


def _build(
    spec: RingSpec,
    seq: Iterator[int],
    occurred_at: datetime,
    amount_paise: int,
    currency: str,
    customer_ref: str,
    device_ref: str | None,
    address_ref: str | None,
    instrument_ref: str | None,
    attributes: dict[str, str],
    intent: str = INTENT_ORDER,
) -> PlannedTransaction:
    return PlannedTransaction(
        seq=next(seq),
        occurred_at=occurred_at,
        amount_paise=amount_paise,
        currency=currency,
        customer_ref=customer_ref,
        device_ref=device_ref,
        address_ref=address_ref,
        instrument_ref=instrument_ref,
        ring_label=spec.label,
        archetype=spec.archetype,
        cadence=spec.cadence,
        split=spec.split,
        intent=intent,
        attributes=attributes,
    )


# ---------------------------------------------------------------------------
# 1. Card testing - human cadence
# ---------------------------------------------------------------------------


def generate_card_testing_human(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Small-value probing on shared cards, paced like a person doing it by hand.

    A human card tester works in sittings: a handful of attempts, a break, then
    more. Volume per account is well below the agent variant because a person
    gets bored.
    """
    # --- tuning knobs ---
    orders_per_account = (6, 14)
    amount_paise_range = (100, 4900)  # Rs 1 - Rs 49, classic probe amounts
    round_amount_bias = 0.25  # humans reach for round numbers sometimes

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)

        for attempt, occurred_at in enumerate(stamps):
            if rng.random() < round_amount_bias:
                amount = rng.choice([100, 500, 1000, 2000, 5000])
            else:
                amount = rng.randint(*amount_paise_range)

            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    amount,
                    currency,
                    customer_ref=customer,
                    device_ref=_pivot_or_private(
                        rng,
                        spec.density * 0.6,  # device sharing is secondary here
                        ids.shared_devices,
                        ids.private_devices[account_index],
                    ),
                    address_ref=None,  # card testing rarely ships anything
                    instrument_ref=_pivot_or_private(
                        rng,
                        spec.density,
                        ids.shared_instruments,
                        ids.private_instruments[account_index],
                    ),
                    attributes={"probe_index": str(attempt)},
                )
            )
    return rows


# ---------------------------------------------------------------------------
# 2. Card testing - agent cadence
# ---------------------------------------------------------------------------


def generate_card_testing_agent(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """The same probing, executed by a script.

    Higher volume, tighter amount ladder, and inter-order gaps below human
    reaction time. The amounts walk a deliberate ascending ladder rather than
    scattering - that systematic sweep is the tell.
    """
    # --- tuning knobs ---
    orders_per_account = (18, 34)
    amount_ladder_paise = (100, 200, 300, 500, 700, 1100, 1300, 1700, 1900, 2300)
    ladder_drift = 0.12  # chance of stepping off the ladder to look less rigid

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)

        for attempt, occurred_at in enumerate(stamps):
            if rng.random() < ladder_drift:
                amount = rng.randint(100, 2500)
            else:
                amount = amount_ladder_paise[attempt % len(amount_ladder_paise)]

            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    amount,
                    currency,
                    customer_ref=customer,
                    device_ref=_pivot_or_private(
                        rng,
                        spec.density,  # a script reuses one browser profile
                        ids.shared_devices,
                        ids.private_devices[account_index],
                    ),
                    address_ref=None,
                    instrument_ref=_pivot_or_private(
                        rng,
                        spec.density,
                        ids.shared_instruments,
                        ids.private_instruments[account_index],
                    ),
                    attributes={"probe_index": str(attempt), "ladder": "1"},
                )
            )
    return rows


# ---------------------------------------------------------------------------
# 3. Promo farming - human cadence
# ---------------------------------------------------------------------------


def generate_promo_farming_human(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Sock-puppet accounts claiming first-order discounts, created by hand.

    Each account places only a couple of orders - the whole point is the
    *first-order* discount - so the signal is account breadth converging on one
    shipping address, not per-account volume.
    """
    # --- tuning knobs ---
    orders_per_account = (1, 3)
    amount_paise_range = (39900, 189900)  # Rs 399 - Rs 1899 basket
    payment_link_share = 0.20  # some are paid via a shared payment link

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)
        codes = promo_sequence(spec.cadence, rng, count)

        for order_index, occurred_at in enumerate(stamps):
            intent = (
                INTENT_PAYMENT_LINK
                if rng.random() < payment_link_share
                else INTENT_ORDER
            )
            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    rng.randrange(*amount_paise_range, 100),
                    currency,
                    customer_ref=customer,
                    device_ref=_pivot_or_private(
                        rng,
                        spec.density * 0.7,
                        ids.shared_devices,
                        ids.private_devices[account_index],
                    ),
                    address_ref=_pivot_or_private(
                        rng,
                        spec.density,  # everything ships to the same door
                        ids.shared_addresses,
                        ids.private_addresses[account_index],
                    ),
                    instrument_ref=ids.private_instruments[account_index],
                    attributes={
                        "promo_code": codes[order_index],
                        "first_order": "1" if order_index == 0 else "0",
                    },
                    intent=intent,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# 4. Promo farming - agent cadence
# ---------------------------------------------------------------------------


def generate_promo_farming_agent(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Scripted account farming with systematic promo-code exploration.

    The distinguishing behaviour is the code walk: instead of using whichever
    coupon they saw, the agent enumerates the promo space in order, one code per
    account, hunting for which ones still validate.
    """
    # --- tuning knobs ---
    orders_per_account = (2, 4)
    amount_paise_range = (49900, 129900)
    amount_quantum = 5000  # scripts pick suspiciously tidy basket values
    device_reuse = 0.92  # one headless browser profile, reused hard

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)
        codes = promo_sequence(spec.cadence, rng, count)

        for order_index, occurred_at in enumerate(stamps):
            low, high = amount_paise_range
            amount = rng.randrange(low, high, amount_quantum)

            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    amount,
                    currency,
                    customer_ref=customer,
                    device_ref=_pivot_or_private(
                        rng,
                        device_reuse,
                        ids.shared_devices,
                        ids.private_devices[account_index],
                    ),
                    address_ref=_pivot_or_private(
                        rng,
                        spec.density,
                        ids.shared_addresses,
                        ids.private_addresses[account_index],
                    ),
                    instrument_ref=ids.private_instruments[account_index],
                    attributes={
                        "promo_code": codes[order_index],
                        "systematic": "1",
                    },
                )
            )
    return rows


# ---------------------------------------------------------------------------
# 5. Return abuse - human cadence
# ---------------------------------------------------------------------------


def generate_return_abuse_human(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Order-then-return crews funnelling refunds to one bank account.

    Fewer, larger orders than the other patterns, and a return rate far above a
    normal population's. The shared *instrument* here stands for the refund
    destination - that is what ties the accounts together.
    """
    # --- tuning knobs ---
    orders_per_account = (3, 7)
    amount_paise_range = (249900, 899900)  # Rs 2499 - Rs 8999, worth returning
    return_rate = 0.62  # vs a few percent for normal traffic

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)

        for occurred_at in stamps:
            returned = rng.random() < return_rate
            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    rng.randrange(*amount_paise_range, 100),
                    currency,
                    customer_ref=customer,
                    device_ref=ids.private_devices[account_index],
                    address_ref=_pivot_or_private(
                        rng,
                        spec.density * 0.5,
                        ids.shared_addresses,
                        ids.private_addresses[account_index],
                    ),
                    instrument_ref=_pivot_or_private(
                        rng,
                        spec.density,  # the shared refund account
                        ids.shared_instruments,
                        ids.private_instruments[account_index],
                    ),
                    attributes={"return_requested": "1" if returned else "0"},
                )
            )
    return rows


# ---------------------------------------------------------------------------
# 6. Return abuse - agent cadence
# ---------------------------------------------------------------------------


def generate_return_abuse_agent(
    spec: RingSpec,
    ids: RingIdentities,
    rng: Random,
    window_end: datetime,
    window_seconds: float,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Scripted return abuse: near-total return rate, machine timing.

    An operator running this at scale barely bothers to vary anything - the
    return rate approaches 1.0 and the order values cluster tightly around
    whatever price band refunds most cleanly.
    """
    # --- tuning knobs ---
    orders_per_account = (5, 10)
    amount_band_paise = (299900, 499900)
    amount_quantum = 10000
    return_rate = 0.88

    rows: list[PlannedTransaction] = []
    for account_index, customer in enumerate(ids.customers):
        count = rng.randint(*orders_per_account)
        stamps = _timestamps(spec.cadence, rng, count, window_end, window_seconds)

        for occurred_at in stamps:
            low, high = amount_band_paise
            returned = rng.random() < return_rate
            rows.append(
                _build(
                    spec,
                    seq,
                    occurred_at,
                    rng.randrange(low, high, amount_quantum),
                    currency,
                    customer_ref=customer,
                    device_ref=_pivot_or_private(
                        rng,
                        spec.density * 0.8,
                        ids.shared_devices,
                        ids.private_devices[account_index],
                    ),
                    address_ref=ids.private_addresses[account_index],
                    instrument_ref=_pivot_or_private(
                        rng,
                        spec.density,
                        ids.shared_instruments,
                        ids.private_instruments[account_index],
                    ),
                    attributes={
                        "return_requested": "1" if returned else "0",
                        "systematic": "1",
                    },
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps "<pattern>:<cadence>" to its generator. Adding an archetype means adding
#: a named function above and one line here.
ARCHETYPE_GENERATORS = {
    "card_testing:human": generate_card_testing_human,
    "card_testing:agent": generate_card_testing_agent,
    "promo_farming:human": generate_promo_farming_human,
    "promo_farming:agent": generate_promo_farming_agent,
    "return_abuse:human": generate_return_abuse_human,
    "return_abuse:agent": generate_return_abuse_agent,
}

#: How many pivot attributes each pattern concentrates on. Card testing shares
#: 1-2 instruments; promo farming funnels into 1 address; return abuse shares
#: one payout account.
PIVOT_COUNTS = {
    "card_testing": {"devices": 2, "addresses": 0, "instruments": 2},
    "promo_farming": {"devices": 2, "addresses": 1, "instruments": 0},
    "return_abuse": {"devices": 1, "addresses": 1, "instruments": 1},
}
