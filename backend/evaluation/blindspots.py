"""Measure the detector against the robustness cases. Diagnostic only.

The cases are inserted through the real ingest path, scored by the real
detector, measured, and then **rolled back**. Nothing persists. That keeps two
properties intact that would otherwise be quietly damaged:

  - every stored transaction still traces to a real Razorpay order
  - the held-out numbers are not disturbed by diagnostic data

The measurement is deliberately harsher than the Phase 6 held-out evaluation.
Held-out rings were drawn from the same generator as the tuning rings; these
were built specifically to sit where the scoring is weakest. A drop is the
expected result and is the useful part - a diagnostic that flatters the thing it
measures is not worth running.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from detection.config import DetectorConfig
from detection.pipeline import run_detection
from generator.robustness_cases import RobustnessCase, build_all


@dataclass
class CaseOutcome:
    case: RobustnessCase
    flagged: bool
    score: float | None
    status: str | None
    cadence: str | None
    accounts_in_cluster: int
    accounts_total: int
    correct: bool
    reading: str = ""

    @property
    def recall(self) -> float:
        return (
            self.accounts_in_cluster / self.accounts_total
            if self.accounts_total
            else 0.0
        )


@dataclass
class BlindspotReport:
    outcomes: list[CaseOutcome] = field(default_factory=list)
    threshold: float = 0.0
    confident_threshold: float = 0.0
    detector_version: str = ""
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def rings(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.case.should_be_flagged]

    @property
    def benign(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if not o.case.should_be_flagged]

    @property
    def rings_detected(self) -> int:
        return sum(1 for o in self.rings if o.flagged)

    @property
    def false_flags(self) -> int:
        return sum(1 for o in self.benign if o.flagged)

    @property
    def recall(self) -> float:
        return self.rings_detected / len(self.rings) if self.rings else 0.0

    @property
    def precision(self) -> float:
        flagged = self.rings_detected + self.false_flags
        return self.rings_detected / flagged if flagged else 0.0


def _event(row, order_id: str) -> dict:
    """Wrap one robustness transaction in the event shape ingest expects."""
    notes = {
        "rs_customer_ref": row.customer_ref,
        "rs_occurred_at": row.occurred_at.isoformat(),
        "rs_archetype": f"robustness:{row.case}",
        "rs_split": "robustness",
    }
    if row.device_ref:
        notes["rs_device_ref"] = row.device_ref
    if row.address_ref:
        notes["rs_address_ref"] = row.address_ref
    if row.instrument_ref:
        notes["rs_instrument_ref"] = row.instrument_ref

    return {
        "entity": "event",
        "event": "order.paid",
        "contains": ["order"],
        "payload": {
            "order": {
                "entity": {
                    "id": order_id,
                    "amount": row.amount_paise,
                    "currency": "INR",
                    "notes": notes,
                    "created_at": int(row.occurred_at.timestamp()),
                }
            }
        },
        "created_at": int(row.occurred_at.timestamp()),
    }


def measure(
    db: Session,
    config: DetectorConfig | None = None,
    cases: list[RobustnessCase] | None = None,
) -> BlindspotReport:
    """Insert the cases, run the detector, measure, and roll back.

    The caller keeps the session; this never commits. A rollback in `finally`
    guarantees the diagnostic leaves no trace even if scoring raises.

    `cases` defaults to the three hand-written diagnostics. Passing a list runs
    the same harness over cases from anywhere else - `scripts/adversarial_cases`
    supplies ones designed by a model that never saw the detector's source.
    """
    from app.ingest import ingest_event

    config = config or DetectorConfig()
    cases = cases if cases is not None else build_all()
    report = BlindspotReport(
        threshold=config.score_threshold,
        confident_threshold=config.confident_score_threshold,
        detector_version=config.version,
    )

    try:
        for case in cases:
            for index, row in enumerate(case.transactions):
                order_id = f"order_ROBUST{case.key[:6].upper()}{index:04d}"
                ingest_event(db, _event(row, order_id))
        db.flush()

        run = run_detection(
            db, config=config, persist=False, scope_label="robustness"
        )

        # Map each case's accounts to the cluster that captured most of them.
        #
        # Looked up BY REFERENCE, not by a naming pattern. This was a
        # LIKE '%_robust_%' filter, which silently matched nothing the moment
        # cases came from anywhere else — `scripts/adversarial_cases` names its
        # entities `_adv_`. Every case then reported "not flagged" with 0 of 0
        # accounts matched, so a lookup failure was indistinguishable from a
        # detector failure, and the run appeared to find three blind spots that
        # had never been tested. A matcher that cannot find its own subjects
        # must not be allowed to report a result, so it now raises instead.
        wanted_refs = sorted({r for case in cases for r in case.customer_refs})
        ref_to_id = {
            row.external_ref: row.id
            for row in db.execute(
                text(
                    "SELECT id, external_ref FROM entities "
                    "WHERE external_ref = ANY(:refs)"
                ),
                {"refs": wanted_refs},
            )
        }
        if wanted_refs and not ref_to_id:
            raise RuntimeError(
                f"none of the {len(wanted_refs)} case accounts were found after "
                "ingest — refusing to report outcomes from an empty match"
            )

        for case in cases:
            wanted = {
                ref_to_id[r] for r in case.customer_refs if r in ref_to_id
            }
            best, overlap = None, 0
            for scored in run.flagged:
                hit = len(wanted & set(scored.candidate.customers))
                if hit > overlap:
                    best, overlap = scored, hit

            # A cluster only counts as capturing the case if it holds at least
            # half its accounts - the same rule the Phase 6 matcher uses.
            flagged = best is not None and overlap >= max(1, len(wanted) // 2)
            status = None
            if flagged and best is not None:
                status = (
                    "pending"
                    if best.score >= config.confident_score_threshold
                    else "needs_review"
                )

            correct = flagged == case.should_be_flagged
            report.outcomes.append(
                CaseOutcome(
                    case=case,
                    flagged=flagged,
                    score=round(best.score, 4) if (flagged and best) else None,
                    status=status,
                    cadence=best.cadence.classification if (flagged and best) else None,
                    accounts_in_cluster=overlap if flagged else 0,
                    accounts_total=len(wanted),
                    correct=correct,
                    reading=_reading(case, flagged, best, config),
                )
            )
    finally:
        db.rollback()

    return report


def _reading(case: RobustnessCase, flagged: bool, scored, config) -> str:
    """One sentence on what this outcome reveals."""
    if case.key == "irregular_timing":
        if flagged and scored is not None:
            band = (
                "confidently"
                if scored.score >= config.confident_score_threshold
                else "but only into the ambiguous band"
            )
            return (
                f"Attribute reuse carries a ring on its own: with the timing "
                f"signal contributing {scored.timing_regularity:.2f}, the "
                f"cluster still scored {scored.score:.3f} and was flagged {band}."
            )
        return (
            "A ring paced like people was missed entirely. Detection here leans "
            "harder on cadence than the weighting suggests."
        )

    if case.key == "innocent_coincidence":
        if flagged and scored is not None:
            return (
                f"A household sharing one address was flagged at "
                f"{scored.score:.3f}. The 0.40 address weight is not low enough "
                "on its own, and this is a real false-positive shape."
            )
        return (
            "A household sharing one delivery address was left alone, which is "
            "what the 0.40 address weight exists to achieve."
        )

    if flagged and scored is not None:
        return (
            f"A ring spread thinly over two months still scored "
            f"{scored.score:.3f}, so detection does not depend on a burst - "
            "attribute convergence is what carries it, not volume."
        )
    return (
        "A slow, low-volume ring was missed. Detection depends more on "
        "transaction density in a short window than intended."
    )
