"""The cost model and the selection rule.

Both are small pieces of arithmetic that carry a claim: the cost model backs
every rupee figure in the report and on `/metrics`, and the selection rule is
the thing the IEEE run showed does not transfer (§5o).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from detection.config import DetectorConfig
from detection.thresholds import select_flagged
from evaluation.cost import build_cost_model


@dataclass
class _Scored:
    """Stands in for `ScoredCluster`.

    `select_flagged` reads `.score` and nothing else, and building a real
    ScoredCluster would need a graph, a subgraph and an evidence bundle to test
    a comparison. The stub is honest about the coupling: if the selector ever
    starts reading another field, these tests fail loudly rather than quietly
    testing the wrong thing.
    """

    score: float


class TestFalsePositiveCost:
    """§5e: two parts that are never merged.

    Review cost is certain — a human really does spend the time. Trust cost is
    *contingent*, because RingSentinel never gates an account; it can only be
    incurred if a human APPROVES a false flag and a downstream process then
    acts. Merging them would inflate the headline figure.
    """

    def test_zero_false_positives_costs_nothing(self):
        model = build_cost_model(false_positives=0, accounts_in_false_positives=0)
        assert model.certain_review_cost_inr == 0
        assert model.total_inr == 0

    def test_review_cost_is_linear_in_false_positives(self):
        one = build_cost_model(false_positives=1, accounts_in_false_positives=4)
        ten = build_cost_model(false_positives=10, accounts_in_false_positives=40)
        assert ten.certain_review_cost_inr == pytest.approx(
            one.certain_review_cost_inr * 10
        )

    def test_a_dismissed_false_flag_costs_time_and_nothing_else(self):
        """The human gate doing its job is the whole reason the trust cost is
        contingent. A false flag a reviewer correctly dismissed must carry no
        trust cost at all.
        """
        model = build_cost_model(
            false_positives=3, accounts_in_false_positives=12, approved_false_positives=0
        )
        assert model.contingent_trust_cost_inr == 0.0
        assert model.certain_review_cost_inr > 0
        assert model.total_inr == model.certain_review_cost_inr

    def test_trust_cost_accrues_only_on_approved_false_flags(self):
        dismissed = build_cost_model(3, 12, approved_false_positives=0)
        approved = build_cost_model(3, 12, approved_false_positives=3)
        assert approved.contingent_trust_cost_inr > 0
        assert approved.total_inr > dismissed.total_inr

    def test_the_two_halves_stay_separable(self):
        """A reader must be able to disagree with the contingent half alone.
        If they were ever summed into one field this would fail.
        """
        model = build_cost_model(2, 8, approved_false_positives=1)
        assert model.total_inr == pytest.approx(
            model.certain_review_cost_inr + model.contingent_trust_cost_inr
        )


class TestSelectionRule:
    """§5o: absolute is shipped; percentile and budget exist because the
    absolute cut does not transfer to real payment data."""

    SCORES = [0.91, 0.72, 0.55, 0.44, 0.38, 0.31, 0.29, 0.12]

    def _clusters(self):
        return [_Scored(s) for s in self.SCORES]

    def test_absolute_mode_flags_at_or_above_the_threshold(self, config):
        picked = select_flagged(self._clusters(), config)
        assert all(c.score >= config.score_threshold for c in picked)
        assert 0.29 not in [c.score for c in picked]

    def test_absolute_is_the_shipped_default(self, config):
        """Every reported number in §5b through §5e is on this mode. A silent
        switch would make them incomparable to each other.
        """
        assert config.threshold_mode == "absolute"

    def test_ordering_of_the_input_does_not_change_the_output(self, config):
        """The selector explicitly does not rely on the caller's ordering. A
        rule that silently depended on it would be a hard bug to see.
        """
        forward = {c.score for c in select_flagged(self._clusters(), config)}
        shuffled = list(reversed(self._clusters()))
        assert {c.score for c in select_flagged(shuffled, config)} == forward

    def test_budget_mode_respects_its_capacity(self, config):
        cfg = replace(config, threshold_mode="budget", review_budget=3)
        picked = select_flagged(self._clusters(), cfg)
        assert len(picked) == 3
        assert [c.score for c in picked] == [0.91, 0.72, 0.55]

    def test_a_budget_never_flags_below_the_floor(self, config):
        """Spare reviewer capacity must produce an empty queue, not noise.
        An empty queue is a truthful answer.
        """
        cfg = replace(config, threshold_mode="budget", review_budget=50)
        picked = select_flagged(self._clusters(), cfg)
        assert all(c.score >= cfg.score_floor for c in picked)
        assert len(picked) < 50

    def test_budget_mode_is_what_generalises(self, config):
        """On IEEE-CIS the absolute cut admitted 2,002 of 2,006 candidates
        because real payment data compresses the score range. A capacity rule
        cannot do that however compressed the scores are — which is the whole
        reason the mode exists.
        """
        compressed = [_Scored(0.31 + i * 0.0001) for i in range(2000)]
        absolute = select_flagged(compressed, config)
        budgeted = select_flagged(
            compressed, replace(config, threshold_mode="budget", review_budget=20)
        )
        assert len(absolute) == 2000
        assert len(budgeted) == 20

    def test_percentile_mode_takes_a_share_not_a_count(self, config):
        cfg = replace(config, threshold_mode="percentile", score_percentile=0.25)
        picked = select_flagged(self._clusters(), cfg)
        assert len(picked) == 2  # round(8 * 0.25)

    def test_an_empty_input_selects_nothing_rather_than_everything(self, config):
        """The empty-set guard. A rule that returns all of an empty list looks
        identical to one that works — this project has been caught by that
        shape three times (§5k).
        """
        for mode in ("absolute", "percentile", "budget"):
            assert select_flagged([], replace(config, threshold_mode=mode)) == []


class TestConfigIsTheOnlyPlaceThresholdsLive:
    def test_no_threshold_literal_is_hardcoded_in_scoring(self):
        """§5b: 'Tunables all live in detection/config.py. Nothing numeric is
        buried in the scoring code.'
        """
        import pathlib
        import re

        import detection.scoring as scoring

        text = pathlib.Path(scoring.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        restated = re.findall(r"^\s*[A-Z_]{3,}\s*=\s*0?\.\d+", code, re.MULTILINE)
        assert not restated, f"scoring.py restates thresholds: {restated}"
