"""Cadence classification: is this cluster being driven by a person or a script?

Two numbers decide it, both derived from inter-transaction gaps:

  coefficient of variation   how *regular* the rhythm is
  median gap                 how *fast* it is

A script is both regular and fast. A person is irregular, slow, or both. Demanding
both conditions for `agent_like` avoids two obvious mistakes: a nightly cron job
that fires once a day is regular but not fast, and a person on a shopping spree
is fast but not regular.

Anything that fails to clear either bar - or that has too little data - comes back
`inconclusive` rather than being forced into a guess. An honest "don't know" is
more useful to a human reviewer than a confident coin flip.
"""

from __future__ import annotations

from dataclasses import dataclass

from detection.baseline import ClusterTiming
from detection.config import DetectorConfig

HUMAN_LIKE = "human_like"
AGENT_LIKE = "agent_like"
INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class CadenceCall:
    """A cadence verdict plus the reasoning that produced it."""

    classification: str
    confidence: float
    reason: str
    median_gap_seconds: float
    coefficient_of_variation: float
    customers_measured: int

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "median_gap_seconds": round(self.median_gap_seconds, 2),
            "coefficient_of_variation": round(self.coefficient_of_variation, 3),
            "customers_measured": self.customers_measured,
        }


def classify_cadence(timing: ClusterTiming, config: DetectorConfig) -> CadenceCall:
    """Decide whether a cluster's rhythm looks automated, human, or unclear."""
    if (
        not timing.usable
        or timing.customers_measured < config.min_customers_for_cadence
    ):
        return CadenceCall(
            classification=INCONCLUSIVE,
            confidence=0.0,
            reason=(
                f"only {timing.customers_measured} account(s) had enough "
                f"transactions to measure timing; need "
                f"{config.min_customers_for_cadence}"
            ),
            median_gap_seconds=timing.median_gap_seconds,
            coefficient_of_variation=timing.median_coefficient_of_variation,
            customers_measured=timing.customers_measured,
        )

    cv = timing.median_coefficient_of_variation
    gap = timing.median_gap_seconds

    is_regular = cv <= config.agent_cv_max
    is_fast = gap <= config.agent_median_gap_max_seconds

    if is_regular and is_fast:
        # Confidence grows as the cluster sits further inside both bounds.
        regularity_margin = 1.0 - (cv / config.agent_cv_max)
        speed_margin = 1.0 - (gap / config.agent_median_gap_max_seconds)
        confidence = max(0.0, min(1.0, 0.5 * (regularity_margin + speed_margin)))
        return CadenceCall(
            classification=AGENT_LIKE,
            confidence=confidence,
            reason=(
                f"gaps are both regular (CV {cv:.2f} <= {config.agent_cv_max}) "
                f"and fast (median {gap:.1f}s <= "
                f"{config.agent_median_gap_max_seconds:.0f}s) across "
                f"{timing.customers_measured} accounts - consistent with scripted "
                "activity"
            ),
            median_gap_seconds=gap,
            coefficient_of_variation=cv,
            customers_measured=timing.customers_measured,
        )

    if cv >= config.human_cv_min or gap >= config.human_median_gap_min_seconds:
        drivers = []
        if cv >= config.human_cv_min:
            drivers.append(f"irregular gaps (CV {cv:.2f} >= {config.human_cv_min})")
        if gap >= config.human_median_gap_min_seconds:
            drivers.append(
                f"unhurried pace (median {gap:.1f}s >= "
                f"{config.human_median_gap_min_seconds:.0f}s)"
            )
        return CadenceCall(
            classification=HUMAN_LIKE,
            confidence=min(1.0, cv / max(config.human_cv_min, 1e-9)) * 0.5 + 0.25,
            reason=" and ".join(drivers) + " - consistent with people acting manually",
            median_gap_seconds=gap,
            coefficient_of_variation=cv,
            customers_measured=timing.customers_measured,
        )

    return CadenceCall(
        classification=INCONCLUSIVE,
        confidence=0.0,
        reason=(
            f"rhythm sits between the thresholds (CV {cv:.2f}, median {gap:.1f}s) - "
            "neither clearly scripted nor clearly manual"
        ),
        median_gap_seconds=gap,
        coefficient_of_variation=cv,
        customers_measured=timing.customers_measured,
    )
