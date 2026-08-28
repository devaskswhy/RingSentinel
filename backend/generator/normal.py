"""Uncorrelated background traffic.

This is the majority of the corpus and its job is to be *boring*: if the
background accidentally produces dense shared-attribute clusters, the detector's
precision measurement becomes meaningless because the "false positives" would
actually be real structure.

So each normal account gets its own device, address, and instrument by default.
A small, deliberate amount of benign sharing is mixed in - households on one
shipping address, one person with a phone and a laptop, a couple sharing a card
- because a detector that cannot tolerate benign sharing is useless in
production. That benign sharing is kept to pairs and triples, well below the
size of a seeded ring.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from random import Random

from generator.identities import NormalIdentities
from generator.planned import INTENT_ORDER, PlannedTransaction

# --- tuning knobs ---------------------------------------------------------
#: Fraction of accounts that legitimately share an address with 1-2 others.
BENIGN_ADDRESS_SHARING = 0.06
#: Fraction of accounts that use a second device.
SECOND_DEVICE_RATE = 0.18
#: Fraction of accounts sharing an instrument with exactly one other account.
BENIGN_INSTRUMENT_SHARING = 0.04
#: Normal population return rate, for contrast with the return-abuse archetype.
NORMAL_RETURN_RATE = 0.04
#: Realistic retail basket spread, in paise.
AMOUNT_PAISE_RANGE = (19900, 649900)


def generate_normal_traffic(
    ids: NormalIdentities,
    transaction_count: int,
    rng: Random,
    window_end: datetime,
    window_days: int,
    currency: str,
    seq: Iterator[int],
) -> list[PlannedTransaction]:
    """Produce uncorrelated orders across the background population."""
    customers = list(ids.customers)
    window_seconds = window_days * 24 * 3600

    # Assign each account its stable attribute set up front, so an account looks
    # like the same person across all of its orders.
    profile: dict[str, dict[str, list[str] | None]] = {}
    for index, customer in enumerate(customers):
        devices = [ids.devices[index % len(ids.devices)]]
        if rng.random() < SECOND_DEVICE_RATE:
            devices.append(ids.devices[rng.randrange(len(ids.devices))])

        # Benign household sharing: a few accounts fold onto a neighbour's address.
        if rng.random() < BENIGN_ADDRESS_SHARING and index > 0:
            address = ids.addresses[(index - 1) % len(ids.addresses)]
        else:
            address = ids.addresses[index % len(ids.addresses)]

        if rng.random() < BENIGN_INSTRUMENT_SHARING and index > 0:
            instrument = ids.instruments[(index - 1) % len(ids.instruments)]
        else:
            instrument = ids.instruments[index % len(ids.instruments)]

        profile[customer] = {
            "devices": devices,
            "address": [address],
            "instrument": [instrument],
        }

    rows: list[PlannedTransaction] = []
    for _ in range(transaction_count):
        customer = rng.choice(customers)
        prof = profile[customer]

        # Spread orders uniformly across the window with a mild waking-hours
        # bias, but no burst structure - normal people are not coordinated.
        offset = rng.uniform(0, window_seconds)
        occurred_at = window_end - timedelta(seconds=offset)

        low, high = AMOUNT_PAISE_RANGE
        amount = rng.randrange(low, high, 100)
        returned = rng.random() < NORMAL_RETURN_RATE

        rows.append(
            PlannedTransaction(
                seq=next(seq),
                occurred_at=occurred_at,
                amount_paise=amount,
                currency=currency,
                customer_ref=customer,
                device_ref=rng.choice(prof["devices"]),
                address_ref=prof["address"][0],
                instrument_ref=prof["instrument"][0],
                ring_label=None,  # ground truth: not part of any ring
                archetype="normal",
                cadence=None,
                split="normal",
                intent=INTENT_ORDER,
                attributes={"return_requested": "1" if returned else "0"},
            )
        )

    return rows
