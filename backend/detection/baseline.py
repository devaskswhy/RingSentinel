"""Timing statistics and the population baseline.

The detector has to answer "is this cluster's rhythm unusual?" without being
told what normal looks like. It cannot read ground-truth labels, so the baseline
is built from the *entire* in-scope population: ring accounts are a minority of
any realistic corpus, so the population median is a serviceable stand-in for
normal behaviour.

Everything here uses medians rather than means. A handful of metronomic ring
accounts would drag a mean noticeably; they barely move a median, which is
exactly the robustness we want from a baseline that includes the thing we are
trying to detect.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime

from detection.config import DetectorConfig


@dataclass(frozen=True)
class CustomerTiming:
    """Inter-transaction rhythm for a single account."""

    customer_id: uuid.UUID
    transaction_count: int
    median_gap_seconds: float
    #: Coefficient of variation (std/mean) of the gaps. Near 0 is metronomic.
    coefficient_of_variation: float
    gap_count: int


@dataclass(frozen=True)
class TimingBaseline:
    """What 'normal' rhythm looks like across the whole in-scope population."""

    median_gap_seconds: float
    median_coefficient_of_variation: float
    customers_measured: int

    @property
    def usable(self) -> bool:
        return self.customers_measured >= 5 and self.median_gap_seconds > 0


@dataclass(frozen=True)
class ClusterTiming:
    """Pooled rhythm for the accounts inside one cluster."""

    median_gap_seconds: float
    median_coefficient_of_variation: float
    customers_measured: int
    fastest_median_gap_seconds: float

    @property
    def usable(self) -> bool:
        return self.customers_measured > 0


def _gaps(timestamps: list[datetime]) -> list[float]:
    """Seconds between consecutive transactions for one account."""
    if len(timestamps) < 2:
        return []
    ordered = sorted(timestamps)
    return [
        (ordered[i + 1] - ordered[i]).total_seconds() for i in range(len(ordered) - 1)
    ]


def customer_timing(
    customer_id: uuid.UUID, timestamps: list[datetime], config: DetectorConfig
) -> CustomerTiming | None:
    """Rhythm for one account, or None if it has too few transactions to judge."""
    if len(timestamps) < config.min_transactions_for_timing:
        return None

    gaps = _gaps(timestamps)
    if len(gaps) < 2:
        return None

    mean_gap = statistics.fmean(gaps)
    # A degenerate all-zero gap sequence is perfectly regular, not undefined.
    cv = (statistics.pstdev(gaps) / mean_gap) if mean_gap > 0 else 0.0

    return CustomerTiming(
        customer_id=customer_id,
        transaction_count=len(timestamps),
        median_gap_seconds=statistics.median(gaps),
        coefficient_of_variation=cv,
        gap_count=len(gaps),
    )


def population_baseline(
    customer_timestamps: dict[uuid.UUID, list[datetime]], config: DetectorConfig
) -> TimingBaseline:
    """Baseline rhythm across every measurable account in scope.

    Label-free by construction: it looks at all accounts, including whatever
    rings are present. Medians keep those rings from distorting it.
    """
    measurements = [
        t
        for cid, stamps in customer_timestamps.items()
        if (t := customer_timing(cid, stamps, config)) is not None
    ]
    if not measurements:
        return TimingBaseline(0.0, 0.0, 0)

    return TimingBaseline(
        median_gap_seconds=statistics.median(
            m.median_gap_seconds for m in measurements
        ),
        median_coefficient_of_variation=statistics.median(
            m.coefficient_of_variation for m in measurements
        ),
        customers_measured=len(measurements),
    )


def cluster_timing(
    customer_ids: list[uuid.UUID],
    customer_timestamps: dict[uuid.UUID, list[datetime]],
    config: DetectorConfig,
) -> ClusterTiming:
    """Rhythm across the accounts in one cluster.

    Each account's gaps are summarised on their own before being combined, so
    interleaving between accounts cannot manufacture a fake burst. Several
    people acting in parallel would otherwise look like one very fast actor.
    """
    measurements = [
        t
        for cid in customer_ids
        if (t := customer_timing(cid, customer_timestamps.get(cid, []), config))
        is not None
    ]
    if not measurements:
        return ClusterTiming(0.0, 0.0, 0, 0.0)

    return ClusterTiming(
        median_gap_seconds=statistics.median(
            m.median_gap_seconds for m in measurements
        ),
        median_coefficient_of_variation=statistics.median(
            m.coefficient_of_variation for m in measurements
        ),
        customers_measured=len(measurements),
        fastest_median_gap_seconds=min(m.median_gap_seconds for m in measurements),
    )


# ---------------------------------------------------------------------------
# Derived signals
# ---------------------------------------------------------------------------


def regularity_signal(
    cluster: ClusterTiming, baseline: TimingBaseline
) -> float:
    """0-1: how much more metronomic this cluster is than the population.

    1.0 means perfectly regular gaps against a baseline that varies normally.
    0.0 means no more regular than everyone else.
    """
    if not cluster.usable or not baseline.usable:
        return 0.0
    if baseline.median_coefficient_of_variation <= 0:
        return 0.0

    ratio = (
        cluster.median_coefficient_of_variation
        / baseline.median_coefficient_of_variation
    )
    return max(0.0, min(1.0, 1.0 - ratio))


def velocity_signal(
    cluster: ClusterTiming, baseline: TimingBaseline, config: DetectorConfig
) -> float:
    """0-1: how much faster this cluster moves than the population.

    Measured in orders of magnitude, because transaction rhythms span seconds to
    days and a linear ratio would be dominated by the slow tail.
    """
    if not cluster.usable or not baseline.usable:
        return 0.0
    if cluster.median_gap_seconds <= 0:
        return 1.0

    decades = math.log10(baseline.median_gap_seconds / cluster.median_gap_seconds)
    if decades <= 0:
        return 0.0
    return max(0.0, min(1.0, decades / config.velocity_decades))
