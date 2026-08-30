"""Does each signal earn its weight?

Four signals were chosen and hand-weighted, and until now nothing in the repo
showed what any of them contributes. The baseline comparison already raised the
question uncomfortably: on the held-out split, `scripts/compare_baselines.py`
found that ranking by the reuse signal ALONE matches the full scorer exactly —
100% recall, 100% precision, same clusters. If three of the four signals can be
deleted with no measurable cost, the weighting is decoration and should be
described as such.

This measures it directly. For each signal, two runs:

  WITHOUT   the signal's weight set to zero and the remaining three
            renormalised to sum to one
  ALONE     that signal carrying the entire score

Renormalising matters. Zeroing a 0.45 weight without it drops every score by up
to 0.45, so a fixed 0.30 threshold flags far less and the run looks worse for a
reason that has nothing to do with information — it would measure the shift in
scale rather than the loss of signal. Renormalised, the score stays on the same
scale and the threshold keeps its meaning, so any change is attributable to the
signal itself.

⚠ On the seeded corpus this can only show what the signals contribute THERE,
and that corpus is separable by construction. A signal that looks like dead
weight on easy data may be the one that carries a hard case. The IEEE lift
figures are the check on that, and both are reported.

Reads ground truth, so it lives in `evaluation/` and `detection/` never imports
it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from detection.config import DetectorConfig
from detection.graph import GraphBundle
from detection.baseline import TimingBaseline
from detection.clustering import CandidateCluster
from detection.scoring import score_cluster
from evaluation.report import evaluate
from evaluation.splits import RingTruth

#: (config field, human name) for each weighted signal.
SIGNALS = (
    ("weight_attribute_reuse", "attribute reuse"),
    ("weight_timing_regularity", "timing regularity"),
    ("weight_concentration", "concentration"),
    ("weight_account_shallowness", "account shallowness"),
)


def _renormalised(config: DetectorConfig, **overrides: float) -> DetectorConfig:
    """A config with some weights overridden and the total scaled back to 1.0."""
    fields = {name: getattr(config, name) for name, _ in SIGNALS}
    fields.update(overrides)
    total = sum(fields.values())
    if total <= 0:
        return replace(config, **fields)
    scaled = {k: v / total for k, v in fields.items()}
    return replace(config, **scaled)


@dataclass
class AblationRow:
    label: str
    kind: str  # "full" | "without" | "alone"
    flagged: int
    recall: float
    precision: float
    false_flags: int

    def delta_recall(self, full: "AblationRow") -> float:
        return self.recall - full.recall

    def delta_precision(self, full: "AblationRow") -> float:
        return self.precision - full.precision


def _measure(
    label: str,
    kind: str,
    config: DetectorConfig,
    candidates: list[CandidateCluster],
    bundle: GraphBundle,
    baseline: TimingBaseline,
    rings: list[RingTruth],
    normals: set[uuid.UUID],
) -> AblationRow:
    """Rescore the SAME candidates under a different weighting.

    Clustering is untouched: the graph and the candidate set do not depend on
    the weights, so rebuilding them would add noise without adding information.
    """
    scored = [score_cluster(c, bundle, baseline, config) for c in candidates]
    flagged = [s for s in scored if s.score >= config.score_threshold]
    report = evaluate(flagged, rings, normals)
    return AblationRow(
        label=label,
        kind=kind,
        flagged=len(flagged),
        recall=report.ring_recall,
        precision=report.precision,
        false_flags=report.false_flags,
    )


def run_ablation(
    candidates: list[CandidateCluster],
    bundle: GraphBundle,
    baseline: TimingBaseline,
    rings: list[RingTruth],
    normals: set[uuid.UUID],
    config: DetectorConfig | None = None,
) -> list[AblationRow]:
    config = config or DetectorConfig()
    rows = [
        _measure("all four signals", "full", config, candidates, bundle,
                 baseline, rings, normals)
    ]

    for field, name in SIGNALS:
        rows.append(
            _measure(
                f"without {name}", "without",
                _renormalised(config, **{field: 0.0}),
                candidates, bundle, baseline, rings, normals,
            )
        )

    for field, name in SIGNALS:
        alone = {f: 0.0 for f, _ in SIGNALS}
        alone[field] = 1.0
        rows.append(
            _measure(
                f"{name} alone", "alone",
                _renormalised(config, **alone),
                candidates, bundle, baseline, rings, normals,
            )
        )
    return rows


def ablate_lift(
    candidates: list[CandidateCluster],
    bundle: GraphBundle,
    baseline: TimingBaseline,
    lift_of,
    config: DetectorConfig | None = None,
) -> list[tuple[str, float]]:
    """Same ablation, scored by ranking lift instead of flag-set precision.

    This is the check the seeded corpus cannot perform. `lift_of` takes the
    scored clusters and returns a lift figure; the caller owns the labels, so
    this module never touches them.
    """
    config = config or DetectorConfig()
    out: list[tuple[str, float]] = []

    def scored_for(conf: DetectorConfig):
        return [score_cluster(c, bundle, baseline, conf) for c in candidates]

    out.append(("all four signals", lift_of(scored_for(config))))
    for field, name in SIGNALS:
        conf = _renormalised(config, **{field: 0.0})
        out.append((f"without {name}", lift_of(scored_for(conf))))
    return out


def render(rows: list[AblationRow], split: str, candidates: int) -> str:
    out: list[str] = []
    a = out.append
    full = rows[0]

    a("=" * 78)
    a("  Does each signal earn its weight?")
    a(f"  Split: {split} · the same {candidates} candidate clusters rescored under")
    a("  each weighting. Remaining weights renormalised to sum to 1.")
    a("=" * 78)
    a("")
    a(f"  {'weighting':<28}{'flags':>6}{'recall':>9}{'precision':>11}"
      f"{'d recall':>10}{'d prec':>9}")
    a(f"  {'-' * 74}")

    for row in rows:
        if row.kind == "alone" and rows[rows.index(row) - 1].kind == "without":
            a("")
        dr = "" if row.kind == "full" else f"{row.delta_recall(full):+.0%}"
        dp = "" if row.kind == "full" else f"{row.delta_precision(full):+.0%}"
        a(
            f"  {row.label:<28}{row.flagged:>6}{row.recall:>8.0%}"
            f"{row.precision:>11.0%}{dr:>10}{dp:>9}"
        )

    a("")
    dead = [
        r for r in rows
        if r.kind == "without"
        and r.recall >= full.recall
        and r.precision >= full.precision
    ]
    if dead:
        a("  ⚠ Removing these costs nothing measurable on this split:")
        for r in dead:
            a(f"      {r.label}")
        a("    On a corpus this separable that is weak evidence for deleting a")
        a("    signal — but it is strong evidence against claiming all four are")
        a("    doing work here, which is what the weighting implies.")
    else:
        a("  Every signal carries measurable weight: removing any one costs")
        a("  recall, precision, or both.")
    a("=" * 78)
    return "\n".join(out)
