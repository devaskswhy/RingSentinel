"""Cases built to reveal where the detector is weak.

This is diagnostic. Each case is a shape the detector might plausibly get wrong,
constructed so that running it tells us something we did not already know. The
output is a measurement of our own blind spots - there is no guidance here for
avoiding detection, and nothing in this module is usable for that.

Three shapes, each targeting one assumption in the Phase 3 scoring:

  irregular_timing   A real ring paced like people. The timing signal is
                     designed to contribute almost nothing here, so this asks
                     whether attribute reuse alone carries a ring.

  innocent_coincidence
                     Unrelated accounts that genuinely share one address - a
                     household, a shared flat - with no shared card, no shared
                     device, and ordinary rhythms. This asks whether the
                     address weight of 0.40 is low enough. It should NOT be
                     flagged.

  low_density        A real ring that moves slowly: a couple of orders per
                     account spread over two months rather than a burst. This
                     asks whether detection quietly depends on transaction
                     density in a short window.

Deliberately NOT persisted. `evaluation/blindspots.py` inserts these inside a
transaction, measures, and rolls back - so the corpus keeps its property that
every stored transaction traces to a real Razorpay order, and the held-out
numbers are not disturbed by diagnostic data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random

#: Fixed so a blind-spot measurement is reproducible run to run.
ROBUSTNESS_SEED = 20260830


@dataclass(frozen=True)
class RobustnessTransaction:
    """One synthetic order, in the shape ingest expects."""

    case: str
    customer_ref: str
    device_ref: str | None
    address_ref: str | None
    instrument_ref: str | None
    amount_paise: int
    occurred_at: datetime


@dataclass(frozen=True)
class RobustnessCase:
    """One diagnostic scenario and what it is meant to reveal."""

    key: str
    title: str
    should_be_flagged: bool
    question: str
    transactions: tuple[RobustnessTransaction, ...]

    @property
    def customer_refs(self) -> set[str]:
        return {t.customer_ref for t in self.transactions}


def _ref(kind: str, case: str, index: int) -> str:
    """Opaque token, same shape the main generator produces. No PII exists."""
    digest = hashlib.sha256(f"robustness|{case}|{kind}|{index}".encode()).hexdigest()[:20]
    return f"{kind}_robust_{digest}"


def _human_gaps(rng: Random, count: int) -> list[float]:
    """Heavy-tailed, human-plausible gaps in seconds."""
    return [max(4.0, rng.lognormvariate(5.4, 1.25)) for _ in range(count)]


def build_irregular_timing_ring(rng: Random, window_end: datetime) -> RobustnessCase:
    """A real ring that paces itself like people rather than like a script.

    Four accounts on one shared card and one shared address. The timing signal
    should contribute close to nothing, which is the point: it isolates whether
    attribute reuse alone is enough to carry a ring over the threshold.
    """
    case = "irregular_timing"
    accounts = 4
    instrument = _ref("inst", case, 0)
    address = _ref("addr", case, 0)

    rows: list[RobustnessTransaction] = []
    for index in range(accounts):
        customer = _ref("cust", case, index)
        device = _ref("dev", case, index)  # each has their own device
        count = rng.randint(5, 7)
        cursor = window_end - timedelta(days=rng.uniform(6, 16))
        for gap in _human_gaps(rng, count):
            cursor += timedelta(seconds=gap * rng.uniform(40, 260))
            rows.append(
                RobustnessTransaction(
                    case=case,
                    customer_ref=customer,
                    device_ref=device,
                    address_ref=address,
                    instrument_ref=instrument,
                    amount_paise=rng.randrange(89900, 449900, 100),
                    occurred_at=cursor,
                )
            )

    return RobustnessCase(
        key=case,
        title="Irregular-timing ring",
        should_be_flagged=True,
        question=(
            "Does a genuine ring still surface when its timing looks entirely "
            "human, so the cadence signal contributes nothing?"
        ),
        transactions=tuple(rows),
    )


def build_innocent_coincidence(rng: Random, window_end: datetime) -> RobustnessCase:
    """Four unrelated people who genuinely share one address.

    A household or a shared flat: same delivery address, different cards,
    different devices, ordinary shopping rhythms, real order histories. Address
    carries a weight of 0.40 precisely so this does not get flagged - this
    measures whether that is actually low enough.
    """
    case = "innocent_coincidence"
    address = _ref("addr", case, 0)

    rows: list[RobustnessTransaction] = []
    for index in range(4):
        customer = _ref("cust", case, index)
        for _ in range(rng.randint(5, 9)):
            rows.append(
                RobustnessTransaction(
                    case=case,
                    customer_ref=customer,
                    device_ref=_ref("dev", case, index),
                    address_ref=address,
                    instrument_ref=_ref("inst", case, index),
                    amount_paise=rng.randrange(19900, 649900, 100),
                    occurred_at=window_end - timedelta(
                        days=rng.uniform(0, 21), seconds=rng.uniform(0, 86400)
                    ),
                )
            )

    return RobustnessCase(
        key=case,
        title="Innocent coincidence",
        should_be_flagged=False,
        question=(
            "Is the address weight low enough that a household sharing one "
            "delivery address is left alone?"
        ),
        transactions=tuple(rows),
    )


def build_low_density_ring(rng: Random, window_end: datetime) -> RobustnessCase:
    """A real ring that moves slowly instead of in a burst.

    Five accounts on one shared card, two or three orders each, spread across
    two months. Nothing about it is fast or regular. This measures whether
    detection quietly depends on volume inside a short window.
    """
    case = "low_density"
    instrument = _ref("inst", case, 0)

    rows: list[RobustnessTransaction] = []
    for index in range(5):
        customer = _ref("cust", case, index)
        for _ in range(rng.randint(2, 3)):
            rows.append(
                RobustnessTransaction(
                    case=case,
                    customer_ref=customer,
                    device_ref=_ref("dev", case, index),
                    address_ref=_ref("addr", case, index),
                    instrument_ref=instrument,
                    amount_paise=rng.randrange(29900, 199900, 100),
                    occurred_at=window_end - timedelta(
                        days=rng.uniform(0, 60), seconds=rng.uniform(0, 86400)
                    ),
                )
            )

    return RobustnessCase(
        key=case,
        title="Low-density ring",
        should_be_flagged=True,
        question=(
            "Does detection depend on a burst, or does a ring spread thinly "
            "over two months still surface?"
        ),
        transactions=tuple(rows),
    )


def build_all(window_end: datetime | None = None) -> list[RobustnessCase]:
    """All three diagnostic cases, deterministic in ROBUSTNESS_SEED."""
    rng = Random(ROBUSTNESS_SEED)
    end = window_end or datetime.now(timezone.utc)
    return [
        build_irregular_timing_ring(rng, end),
        build_innocent_coincidence(rng, end),
        build_low_density_ring(rng, end),
    ]
