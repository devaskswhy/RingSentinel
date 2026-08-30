"""What the four-signal scorer is actually worth, against rules that are free.

The repo could show 100% precision and recall without ever answering the
question an ML-literate reviewer asks first: **how do I know your scorer beats
a one-line heuristic?** Four hand-weighted signals are only justified if they
outperform "flag any attribute shared by three or more accounts", and until
this module existed nothing here checked.

The experiment holds everything constant except the selection rule. The same
graph, the same clustering, the same candidate clusters — only the decision of
which candidates to flag changes. So any difference in precision or recall is
attributable to the scorer and to nothing else.

Where the baselines need a budget, they are given exactly as many flags as
RingSentinel raised. A rule that flags everything would score perfect recall
and useless precision; matching k makes the comparison fair in the direction
that matters.

This lives in `evaluation/` because it reads ground truth. `detection/` must
never import it.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from detection.config import DetectorConfig
from detection.scoring import ScoredCluster
from evaluation.report import EvaluationReport, evaluate
from evaluation.splits import RingTruth

#: Fixed so the random baseline is the same every run. A baseline that moves
#: between runs cannot be argued with.
RANDOM_SEED = 20260901

#: The obvious heuristic a reviewer would reach for first.
NAIVE_ACCOUNT_FLOOR = 3


@dataclass
class BaselineResult:
    name: str
    description: str
    flagged: int
    report: EvaluationReport

    @property
    def recall(self) -> float:
        return self.report.ring_recall

    @property
    def precision(self) -> float:
        return self.report.precision

    @property
    def false_flags(self) -> int:
        return self.report.false_flags


def _max_attribute_accounts(s: ScoredCluster) -> int:
    """How many accounts sit on this cluster's busiest shared attribute."""
    if not s.shared_attributes:
        return 0
    return max(a.customer_count for a in s.shared_attributes)


def run_baselines(
    scored: list[ScoredCluster],
    rings: list[RingTruth],
    normals: set[uuid.UUID],
    config: DetectorConfig | None = None,
) -> list[BaselineResult]:
    """Score the same candidates five different ways."""
    config = config or DetectorConfig()

    ring_flagged = [s for s in scored if s.score >= config.score_threshold]
    k = len(ring_flagged)

    rng = random.Random(RANDOM_SEED)
    shuffled = list(scored)
    rng.shuffle(shuffled)

    by_size = sorted(scored, key=lambda s: len(s.candidate.customers), reverse=True)
    by_reuse = sorted(scored, key=lambda s: s.attribute_reuse, reverse=True)

    rules: list[tuple[str, str, list[ScoredCluster]]] = [
        (
            "RingSentinel",
            f"four weighted signals, score >= {config.score_threshold}",
            ring_flagged,
        ),
        (
            "Naive attribute count",
            f"any attribute shared by >= {NAIVE_ACCOUNT_FLOOR} accounts",
            [s for s in scored if _max_attribute_accounts(s) >= NAIVE_ACCOUNT_FLOOR],
        ),
        (
            "Attribute reuse only",
            f"the reuse signal alone, top {k}",
            by_reuse[:k],
        ),
        (
            "Largest clusters",
            f"the {k} clusters with the most accounts",
            by_size[:k],
        ),
        (
            "Random",
            f"{k} candidates at random, seed {RANDOM_SEED}",
            shuffled[:k],
        ),
    ]

    return [
        BaselineResult(
            name=name,
            description=desc,
            flagged=len(flagged),
            report=evaluate(flagged, rings, normals),
        )
        for name, desc, flagged in rules
    ]


def render(results: list[BaselineResult], candidates: int) -> str:
    """A table, plus the one sentence the table is there to support."""
    out: list[str] = []
    a = out.append
    a("=" * 78)
    a("  Does the scorer beat a free heuristic?")
    a(f"  Same graph, same clustering, same {candidates} candidate clusters —")
    a("  only the rule deciding which to flag changes.")
    a("=" * 78)
    a("")
    a(f"  {'rule':<24}{'flags':>6}{'recall':>9}{'precision':>11}{'false':>7}")
    a(f"  {'-' * 70}")
    for r in results:
        a(
            f"  {r.name:<24}{r.flagged:>6}{r.recall:>8.0%}{r.precision:>11.0%}"
            f"{r.false_flags:>7}"
        )
    a("")
    for r in results:
        a(f"    {r.name:<24}{r.description}")
    a("")

    ours = next((r for r in results if r.name == "RingSentinel"), None)
    others = [r for r in results if r is not ours]
    if ours and others:
        best_other = max(others, key=lambda r: (r.recall, r.precision))
        if ours.recall > best_other.recall or ours.precision > best_other.precision:
            a(
                f"  The scorer earns its complexity: the best free rule is "
                f"'{best_other.name}' at\n"
                f"  {best_other.recall:.0%} recall and {best_other.precision:.0%} "
                f"precision, against {ours.recall:.0%} and {ours.precision:.0%}."
            )
        else:
            a(
                f"  ⚠ The scorer does NOT beat '{best_other.name}' on this split. "
                f"Four weighted\n  signals are not justified by this evidence, and "
                f"that is worth saying plainly."
            )
    a("=" * 78)
    return "\n".join(out)
