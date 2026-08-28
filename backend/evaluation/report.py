"""Score the detector against ground truth. READS LABELS - evaluation only.

Matching rule
-------------
A seeded ring counts as *detected* when some flagged cluster contains at least
`MIN_ACCOUNT_RECALL` of its accounts. Partial credit is deliberate: a cluster
that catches 5 of a 6-account ring is a successful detection that a human
reviewer would act on, not a miss. Requiring an exact set match would punish the
detector for the one ring member who happened to use a private device.

A flagged cluster is a *false flag* when fewer than `MIN_RING_PURITY` of its
accounts belong to any seeded ring - i.e. it is mostly background traffic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from detection.scoring import ScoredCluster
from evaluation.splits import RingTruth

#: Fraction of a ring's accounts a cluster must contain to count as detecting it.
MIN_ACCOUNT_RECALL = 0.50

#: Fraction of a cluster's accounts that must belong to some ring for the
#: cluster to count as a true positive rather than a false flag.
MIN_RING_PURITY = 0.50


@dataclass
class RingOutcome:
    truth: RingTruth
    detected: bool
    best_cluster_index: int | None
    accounts_found: int
    accounts_total: int
    score: float
    cadence: str

    @property
    def recall(self) -> float:
        return self.accounts_found / self.accounts_total if self.accounts_total else 0.0


@dataclass
class ClusterOutcome:
    index: int
    size: int
    score: float
    cadence: str
    ring_accounts: int
    matched_rings: list[str]
    headline: str

    @property
    def purity(self) -> float:
        return self.ring_accounts / self.size if self.size else 0.0

    @property
    def is_false_flag(self) -> bool:
        return self.purity < MIN_RING_PURITY


@dataclass
class EvaluationReport:
    rings: list[RingOutcome] = field(default_factory=list)
    clusters: list[ClusterOutcome] = field(default_factory=list)
    normal_accounts_total: int = 0
    normal_accounts_flagged: int = 0

    @property
    def detected(self) -> int:
        return sum(1 for r in self.rings if r.detected)

    @property
    def ring_recall(self) -> float:
        return self.detected / len(self.rings) if self.rings else 0.0

    @property
    def false_flags(self) -> int:
        return sum(1 for c in self.clusters if c.is_false_flag)

    @property
    def precision(self) -> float:
        if not self.clusters:
            return 0.0
        return (len(self.clusters) - self.false_flags) / len(self.clusters)

    @property
    def normal_flag_rate(self) -> float:
        if not self.normal_accounts_total:
            return 0.0
        return self.normal_accounts_flagged / self.normal_accounts_total


def evaluate(
    flagged: list[ScoredCluster],
    rings: list[RingTruth],
    normal_customers: set[uuid.UUID],
) -> EvaluationReport:
    """Compare flagged clusters against the seeded rings."""
    report = EvaluationReport(normal_accounts_total=len(normal_customers))

    cluster_accounts = [set(c.candidate.customers) for c in flagged]
    ring_account_union: set[uuid.UUID] = set()
    for ring in rings:
        ring_account_union |= set(ring.customer_entity_ids)

    # ---- per ring -------------------------------------------------------
    for ring in rings:
        truth_accounts = set(ring.customer_entity_ids)
        best_index: int | None = None
        best_overlap = 0

        for index, accounts in enumerate(cluster_accounts):
            overlap = len(truth_accounts & accounts)
            if overlap > best_overlap:
                best_overlap, best_index = overlap, index

        recall = best_overlap / len(truth_accounts) if truth_accounts else 0.0
        detected = recall >= MIN_ACCOUNT_RECALL

        report.rings.append(
            RingOutcome(
                truth=ring,
                detected=detected,
                best_cluster_index=best_index if detected else None,
                accounts_found=best_overlap,
                accounts_total=len(truth_accounts),
                score=flagged[best_index].score if (detected and best_index is not None) else 0.0,
                cadence=(
                    flagged[best_index].cadence.classification
                    if (detected and best_index is not None)
                    else "-"
                ),
            )
        )

    # ---- per flagged cluster --------------------------------------------
    flagged_normal: set[uuid.UUID] = set()
    for index, item in enumerate(flagged):
        accounts = cluster_accounts[index]
        ring_hits = accounts & ring_account_union
        matched = sorted(
            {
                ring.ring
                for ring in rings
                if set(ring.customer_entity_ids) & accounts
            }
        )
        flagged_normal |= accounts & normal_customers

        report.clusters.append(
            ClusterOutcome(
                index=index,
                size=len(accounts),
                score=item.score,
                cadence=item.cadence.classification,
                ring_accounts=len(ring_hits),
                matched_rings=matched,
                headline=item.headline(),
            )
        )

    report.normal_accounts_flagged = len(flagged_normal)
    return report
