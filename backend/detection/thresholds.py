"""Deciding which candidates to flag, when you do not know the distribution.

An absolute threshold is the right instrument only where it has been
calibrated. `SCORE_THRESHOLD = 0.30` was measured on the seeded corpus, where
the score sweep has a flat plateau between 0.25 and 0.35 and 0.30 sits in its
centre. That number is honest there and it does not travel:
`scripts/evaluate_ieee.py` shows real payment data compressing the score range
to 0.10–0.88, where 0.30 admits 99% of candidates and lift collapses to 1.02x.

The obvious repair — flag the top N% instead — does not work either, and the
reason is worth stating because it is the interesting part. Prevalence differs
by a factor of thirty between the two corpora: 12 of 20 candidates are real
rings in the seeded data, against roughly 7 of 376 in IEEE-CIS. A percentile
that is right for one is badly wrong for the other, so replacing one blind
constant with a different blind constant buys nothing.

What does generalise is **capacity**. A reviewer can work through so many cases
in a day, and that number is known even when the score distribution is not. So
the third mode selects the top K candidates by score: it makes no assumption
about prevalence, it degrades honestly (a budget of 20 finds fewer rings than a
budget of 50, and says so), and it matches how a risk team is actually staffed.
On IEEE-CIS a budget in the tens lands on the 1.5x-lift region of the ranking
curve, which is where the score has been shown to carry signal.

⚠ Absolute remains the DEFAULT. Every published result in this repository was
measured with it, and switching the default would silently invalidate them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from detection.config import DetectorConfig
    from detection.scoring import ScoredCluster


def select_flagged(
    scored: list["ScoredCluster"], config: "DetectorConfig"
) -> list["ScoredCluster"]:
    """Apply the configured selection rule to the scored candidates.

    `scored` is not assumed to be sorted; the caller's ordering is not relied
    upon, because a selection rule that silently depended on it would be a
    difficult bug to see.
    """
    mode = getattr(config, "threshold_mode", "absolute")

    if mode == "percentile":
        ranked = sorted(scored, key=lambda s: s.score, reverse=True)
        k = max(1, round(len(ranked) * config.score_percentile)) if ranked else 0
        return ranked[:k]

    if mode == "budget":
        ranked = sorted(scored, key=lambda s: s.score, reverse=True)
        # A budget never flags something the absolute floor would reject: a
        # reviewer with spare capacity should be given nothing rather than
        # noise, and an empty queue is a truthful answer.
        return [s for s in ranked[: config.review_budget] if s.score >= config.score_floor]

    return [s for s in scored if s.score >= config.score_threshold]


def describe_selection(config: "DetectorConfig") -> str:
    """One line naming the rule in force, for reports and audit detail."""
    mode = getattr(config, "threshold_mode", "absolute")
    if mode == "percentile":
        return f"top {config.score_percentile:.1%} of candidates by score"
    if mode == "budget":
        return (
            f"top {config.review_budget} candidates by score, "
            f"floor {config.score_floor}"
        )
    return f"score >= {config.score_threshold} (calibrated on the seeded corpus)"
