"""What is the smallest change that would move this cluster across a boundary?

A sensitivity read on the Phase 3 score, not new detection logic. It answers a
question a reviewer actually asks - "how close was this?" - and it is only
answerable because the score is a composition of named signals rather than a
model output. A cluster scoring 0.386 is not simply "below the line"; it is one
more account on the shared card away from being above it, and that is a more
useful thing to put in front of a human.

Everything here recomputes from `clusters.evidence_json`, which already holds
each shared attribute's account count, type weight, and contribution. No
re-detection, no database beyond the row itself.

The arithmetic mirrors `detection/scoring.py` exactly. If the scoring changes
and this does not, the two will disagree - which is why the weights and the
saturation constant are imported from config rather than restated.
"""

from __future__ import annotations

from typing import Any

from detection.config import DetectorConfig


def _reuse_strength(customer_count: int, config: DetectorConfig) -> float:
    """f(k) = (k-1)/(k-1+K). Same function `scoring.py` uses."""
    k = max(0, customer_count - 1)
    return k / (k + config.reuse_saturation_k)


def _soft_or(contributions: list[float]) -> float:
    """1 - prod(1 - c). Same combination `scoring.py` uses."""
    remaining = 1.0
    for value in contributions:
        remaining *= 1.0 - min(1.0, max(0.0, value))
    return 1.0 - remaining


def _score_from(reuse: float, signals: dict[str, Any], config: DetectorConfig) -> float:
    """Recompose the total score with a substituted reuse value."""
    def value(name: str) -> float:
        node = signals.get(name) or {}
        return float(node.get("value", 0.0)) if isinstance(node, dict) else 0.0

    total = (
        config.weight_attribute_reuse * reuse
        + config.weight_timing_regularity * value("timing_regularity")
        + config.weight_concentration * value("concentration")
        + config.weight_account_shallowness * value("account_shallowness")
    )
    return max(0.0, min(1.0, total))


def counterfactual(
    evidence: dict[str, Any], score: float, config: DetectorConfig | None = None
) -> dict[str, Any] | None:
    """The nearest boundary, and the smallest change that would cross it.

    Returns None when there is nothing meaningful to say - no shared attributes
    to vary, or a score already at the top of the range.
    """
    config = config or DetectorConfig()
    signals = evidence.get("signals") or {}
    shared = list(evidence.get("shared_attributes") or [])

    if not shared:
        return None

    # Which line is this cluster nearest to, and in which direction?
    if score < config.score_threshold:
        boundary, boundary_name = config.score_threshold, "the flag threshold"
    elif score < config.confident_score_threshold:
        boundary, boundary_name = (
            config.confident_score_threshold,
            "the confidence threshold",
        )
    else:
        # Already confident. The useful counterfactual runs the other way: how
        # much would have to be removed before it stopped being confident.
        return _margin_below(evidence, score, config)

    contributions = [float(a.get("contribution", 0.0)) for a in shared]

    # The cheapest realistic change: one more account touching the attribute
    # that already contributes most. Each shared attribute is tried so the
    # answer names the one that actually moves the number furthest.
    best: dict[str, Any] | None = None
    for index, attribute in enumerate(shared):
        count = int(attribute.get("customer_count", 0))
        weight = float(attribute.get("type_weight", 0.0))
        if count <= 0 or weight <= 0:
            continue

        hypothetical = list(contributions)
        hypothetical[index] = _reuse_strength(count + 1, config) * weight
        new_score = _score_from(_soft_or(hypothetical), signals, config)
        delta = new_score - score

        if best is None or new_score > best["score_would_become"]:
            best = {
                "change": (
                    f"one more account sharing the same "
                    f"{attribute.get('attribute_type')}"
                ),
                "attribute_type": attribute.get("attribute_type"),
                "external_ref": attribute.get("external_ref"),
                "accounts_now": count,
                "accounts_after": count + 1,
                "score_would_become": round(new_score, 4),
                "delta": round(delta, 4),
                "would_cross": new_score >= boundary,
            }

    if best is None:
        return None

    return {
        "current_score": round(score, 4),
        "nearest_boundary": round(boundary, 2),
        "boundary_name": boundary_name,
        "gap": round(boundary - score, 4),
        "smallest_change": best,
        "reading": (
            f"{best['change']} would take this to {best['score_would_become']:.3f}, "
            f"{'crossing' if best['would_cross'] else 'still short of'} "
            f"{boundary_name} at {boundary:.2f}."
        ),
        "note": (
            "A sensitivity read on the existing score, not a second model. It is "
            "answerable only because the score is a sum of named signals."
        ),
    }


def _margin_below(
    evidence: dict[str, Any], score: float, config: DetectorConfig
) -> dict[str, Any] | None:
    """For a confident cluster: how much evidence would have to vanish."""
    signals = evidence.get("signals") or {}
    shared = list(evidence.get("shared_attributes") or [])
    if not shared:
        return None

    contributions = [float(a.get("contribution", 0.0)) for a in shared]
    strongest = max(range(len(shared)), key=lambda i: contributions[i])
    attribute = shared[strongest]

    without = list(contributions)
    without[strongest] = 0.0
    new_score = _score_from(_soft_or(without), signals, config)

    return {
        "current_score": round(score, 4),
        "nearest_boundary": round(config.confident_score_threshold, 2),
        "boundary_name": "the confidence threshold",
        "gap": round(score - config.confident_score_threshold, 4),
        "smallest_change": {
            "change": (
                f"discounting the shared {attribute.get('attribute_type')} entirely"
            ),
            "attribute_type": attribute.get("attribute_type"),
            "external_ref": attribute.get("external_ref"),
            "accounts_now": int(attribute.get("customer_count", 0)),
            "score_would_become": round(new_score, 4),
            "delta": round(new_score - score, 4),
            "would_cross": new_score < config.confident_score_threshold,
        },
        "reading": (
            f"Even discounting the shared {attribute.get('attribute_type')} "
            f"entirely, this would still score {new_score:.3f}."
            if new_score >= config.confident_score_threshold
            else f"This rests on the shared {attribute.get('attribute_type')}: "
            f"without it the score falls to {new_score:.3f}, below "
            f"{config.confident_score_threshold:.2f}."
        ),
        "note": (
            "A sensitivity read on the existing score, not a second model. It is "
            "answerable only because the score is a sum of named signals."
        ),
    }
