"""The scoring arithmetic, and the three calibration findings that were bugs first.

§5b records three fixes, each of which was a real defect before it was a
design decision. A regression in any of them would still produce a plausible
score, so none of them would announce itself — which is exactly the kind of
thing a unit test is for.
"""

from __future__ import annotations

import uuid

import pytest

from detection.scoring import (
    SharedAttribute,
    _reuse_strength,
    attribute_reuse_signal,
)


def _attr(customer_count: int, kind: str, config) -> SharedAttribute:
    """A SharedAttribute built the way find_shared_attributes builds one."""
    strength = _reuse_strength(customer_count, config)
    weight = config.attribute_weights[kind]
    return SharedAttribute(
        entity_id=uuid.uuid4(),
        attribute_type=kind,
        external_ref="tok_" + kind,
        customer_count=customer_count,
        observations=customer_count * 2,
        reuse_strength=strength,
        type_weight=weight,
        contribution=strength * weight,
    )


class TestReuseSaturation:
    """f(k) = (k-1)/(k-1+K), and why it is not linear."""

    def test_matches_the_documented_formula(self, config):
        k_const = config.reuse_saturation_k
        for accounts in (1, 2, 3, 5, 9, 40):
            k = accounts - 1
            assert _reuse_strength(accounts, config) == pytest.approx(
                k / (k + k_const)
            )

    def test_one_account_sharing_with_itself_is_no_evidence(self, config):
        assert _reuse_strength(1, config) == 0.0

    def test_early_accounts_count_for_far_more_than_late_ones(self, config):
        """The whole reason for saturating.

        Going 2 -> 4 accounts on one card must move the score much more than
        20 -> 22 does. A linear function would let one enormous cluster
        dominate every score in the system, which is precisely what the IEEE
        run showed happening once real 1,568-account clusters appear (§5o).
        """
        early = _reuse_strength(4, config) - _reuse_strength(2, config)
        late = _reuse_strength(22, config) - _reuse_strength(20, config)
        assert early > late * 10

    def test_is_bounded_below_one(self, config):
        assert _reuse_strength(10_000, config) < 1.0


class TestAttributeTypeWeights:
    """instrument 1.00 > device 0.85 > address 0.40, and the gap is the point."""

    def test_ordering_holds(self, config):
        w = config.attribute_weights
        assert w["instrument"] > w["device"] > w["address"]

    def test_address_is_weighted_low_enough_to_protect_households(self, config):
        """§5b: 'a shared delivery address is a household far more often than a
        crew, so address overlap alone cannot flag a cluster.'

        This is the single weight that keeps a family from being treated as a
        ring, and it is asserted directly rather than trusted.
        """
        assert config.attribute_weights["address"] <= 0.40

        # A household of four on one address, and nothing else shared, must
        # land under the flag threshold on the reuse signal alone.
        household = [_attr(4, "address", config)]
        reuse = attribute_reuse_signal(household)
        assert reuse * config.weight_attribute_reuse < config.score_threshold


class TestSoftOr:
    """1 - prod(1 - c_i): evidence stacks, and stays in [0, 1]."""

    def test_independent_evidence_accumulates(self, config):
        card = _attr(4, "instrument", config)
        device = _attr(4, "device", config)
        both = attribute_reuse_signal([card, device])
        assert both > attribute_reuse_signal([card])
        assert both > attribute_reuse_signal([device])

    def test_never_exceeds_one(self, config):
        many = [_attr(40, "instrument", config) for _ in range(25)]
        assert attribute_reuse_signal(many) <= 1.0

    def test_no_evidence_scores_zero(self):
        assert attribute_reuse_signal([]) == 0.0

    def test_contributions_are_clamped_before_combining(self, config):
        """A contribution outside [0, 1] must not invert the product.

        Without the clamp a contribution of 1.5 contributes a factor of -0.5,
        which would make *more* evidence reduce the score.
        """
        rogue = _attr(4, "instrument", config)
        rogue.contribution = 1.5
        assert 0.0 <= attribute_reuse_signal([rogue]) <= 1.0


class TestEvidenceFloor:
    """'A pair is not a ring' — §5b, finding 3."""

    def test_floor_is_at_least_three(self, config):
        """With the floor at 2 the soft-OR let several unrelated *pairs*
        accumulate to reuse 0.85. Raising it to 3 was the fix; dropping it back
        would silently reintroduce that.
        """
        assert config.min_customers_per_shared_attribute >= 3


class TestHubFilter:
    """'The hub filter was deleting a real ring' — §5b, finding 1."""

    def test_absolute_floor_clears_plausible_ring_sizes(self, config):
        """A 5% hub rule on a 173-account graph gives a limit of 8, and ring_04
        is a genuine 9-account ring. The absolute floor exists so the
        percentage only takes over on a large graph.
        """
        assert config.hub_attribute_min_customers >= 25


class TestThresholdRelationship:
    def test_confidence_threshold_sits_above_the_flag_threshold(self, config):
        """The ambiguous band is [flag, confident). If these ever crossed, every
        flagged cluster would be 'confident' and the band would vanish without
        any error being raised.
        """
        assert config.score_threshold < config.confident_score_threshold

    def test_a_config_whose_weights_do_not_sum_to_one_is_rejected(self):
        """`__post_init__` already enforces this, so asserting the shipped
        weights sum to 1 would only re-test production code. What is worth
        testing is that the guard actually *fires* — a validator that silently
        accepts everything is the empty-set failure this project has hit three
        times (§5k).
        """
        from detection.config import DetectorConfig

        with pytest.raises(ValueError, match="must sum to 1.0"):
            DetectorConfig(weight_attribute_reuse=0.9)

    def test_linkage_ships_switched_off(self, config):
        """§5o: built, measured, and left off because it makes the false
        positives worse. A future edit that enables it by default should have
        to delete this test and read why.
        """
        assert config.weight_linkage == 0.0

    def test_population_relative_reuse_ships_switched_off(self, config):
        """§5o: hypothesis measured and refuted on IEEE-CIS."""
        assert config.population_relative_reuse is False
