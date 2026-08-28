"""Timing models: how a ring spaces its orders out over time.

Cadence is the axis that separates the two variants of every archetype, and it
is the part a graph alone cannot see - two rings with identical shared-attribute
structure can still be told apart by *when* they act.

human cadence
    Irregular. Inter-order gaps are heavy-tailed (lognormal): mostly minutes,
    occasionally hours. Activity follows a diurnal curve, so orders cluster in
    waking hours and thin out overnight. No gap is shorter than a plausible
    human reaction time.

agent cadence
    Near-uniform. Gaps sit tight around a small mean with very little variance,
    frequently *below* human reaction time. No diurnal structure at all - an
    agent is as happy working at 04:00 as at 14:00. Promo exploration walks a
    code list systematically instead of picking at random.

Both return plain second offsets so callers can anchor them wherever they like.
"""

from __future__ import annotations

import math
from random import Random

#: Fastest plausible human turnaround between two deliberate orders. Anything
#: below this is a machine, and the agent variants deliberately go under it.
HUMAN_REACTION_FLOOR_SECONDS = 4.0

#: Agent inter-order gaps centre here - comfortably sub-human and very regular.
AGENT_MEAN_GAP_SECONDS = 1.6
AGENT_JITTER_FRACTION = 0.06


def _diurnal_weight(hour: float) -> float:
    """Relative likelihood of a human acting at a given hour of the day.

    A smooth curve peaking early evening and bottoming out around 04:00. Used to
    reject-sample human timestamps so overnight activity is sparse but not zero.
    """
    # Peak ~19:00, trough ~04:00.
    phase = (hour - 19.0) / 24.0 * 2.0 * math.pi
    return 0.15 + 0.85 * (0.5 * (1.0 + math.cos(phase)))


def human_gap_seconds(rng: Random) -> float:
    """One heavy-tailed, human-plausible gap between consecutive orders."""
    # Lognormal: median ~e^5.4 ≈ 220s, with a long right tail into hours.
    gap = rng.lognormvariate(5.4, 1.25)
    return max(HUMAN_REACTION_FLOOR_SECONDS, gap)


def agent_gap_seconds(rng: Random) -> float:
    """One near-uniform, sub-human gap between consecutive orders."""
    jitter = rng.uniform(-AGENT_JITTER_FRACTION, AGENT_JITTER_FRACTION)
    return max(0.25, AGENT_MEAN_GAP_SECONDS * (1.0 + jitter))


def gap_seconds(cadence: str, rng: Random) -> float:
    if cadence == "agent":
        return agent_gap_seconds(rng)
    if cadence == "human":
        return human_gap_seconds(rng)
    raise ValueError(f"unknown cadence: {cadence!r}")


def human_offsets(rng: Random, count: int, window_seconds: float) -> list[float]:
    """Offsets for a human-cadence burst, biased toward waking hours.

    Walks forward with heavy-tailed gaps, then nudges each timestamp toward a
    plausible hour of day by rejection sampling against the diurnal curve.
    """
    offsets: list[float] = []
    cursor = rng.uniform(0.0, max(1.0, window_seconds * 0.35))

    for _ in range(count):
        # Rejection-sample a gap whose landing hour is diurnally plausible.
        for _attempt in range(8):
            candidate = cursor + human_gap_seconds(rng)
            hour = (candidate / 3600.0) % 24.0
            if rng.random() <= _diurnal_weight(hour):
                cursor = candidate
                break
        else:
            cursor = cursor + human_gap_seconds(rng)

        offsets.append(cursor)

    return offsets


def agent_offsets(rng: Random, count: int, window_seconds: float) -> list[float]:
    """Offsets for an agent-cadence burst: a tight, regular machine-gun run.

    Starts at an arbitrary point in the window - including the middle of the
    night, which is part of the signal.
    """
    start = rng.uniform(0.0, max(1.0, window_seconds * 0.9))
    offsets: list[float] = []
    cursor = start
    for _ in range(count):
        cursor += agent_gap_seconds(rng)
        offsets.append(cursor)
    return offsets


def offsets_for(
    cadence: str, rng: Random, count: int, window_seconds: float
) -> list[float]:
    if cadence == "agent":
        return agent_offsets(rng, count, window_seconds)
    if cadence == "human":
        return human_offsets(rng, count, window_seconds)
    raise ValueError(f"unknown cadence: {cadence!r}")


# ---------------------------------------------------------------------------
# Promo code exploration - the other place cadence shows itself
# ---------------------------------------------------------------------------

PROMO_CODES: tuple[str, ...] = tuple(
    f"WELCOME{n}" for n in (5, 10, 15, 20, 25, 30, 40, 50)
) + ("FIRSTORDER", "NEWUSER100", "TRYUS200", "SAVEBIG")


def promo_sequence(cadence: str, rng: Random, count: int) -> list[str]:
    """Which promo codes get tried, in which order.

    A human picks whatever code they saw advertised - effectively random, with
    repeats. An agent enumerates the space systematically, walking the list in
    order from a starting offset and rarely repeating until it wraps.
    """
    if cadence == "agent":
        start = rng.randrange(len(PROMO_CODES))
        return [PROMO_CODES[(start + i) % len(PROMO_CODES)] for i in range(count)]
    return [rng.choice(PROMO_CODES) for _ in range(count)]
