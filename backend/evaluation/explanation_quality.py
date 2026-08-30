"""Score generated case files against a rubric.

Three criteria, and the grading method differs by criterion on purpose.

  grounding      Does the case file cite only things that are actually true of
                 the cluster? Checked MECHANICALLY. Every entity reference and
                 every count it mentions is matched against the cluster's
                 evidence. This is the hallucination check and it needs no model
                 to make it: "zero fabricated attributes across N case files,
                 verified by string match" is a stronger claim than any grader's
                 opinion, and it cannot be accused of marking its own homework.

  calibration    Does it avoid overclaiming? Checked mechanically for the
                 specific failure that matters: asserting certainty about a
                 cluster the detector itself is unsure of.

  action fit     Is the suggested action consistent with the score? Checked
                 mechanically against the same bands the detector uses.

Nothing here asks Claude to grade Claude. That would be cheap to build and weak
as evidence - a model evaluating its own output shares its blind spots, and a
judge would rightly discount it.

The trade-off, stated plainly: mechanical checks catch fabrication and
miscalibration but cannot judge whether an explanation is *insightful*. This
measures honesty, not quality.

Two limits worth knowing before quoting a pass rate from this module:

  - Integers below FREE_NUMBER_CEILING are treated as ordinary English rather
    than as claims, so the grounding check does not constrain them. The report
    states how many assertions fell either side of that line.
  - A checker that matches nothing also reports 100%. That is not hypothetical
    here: this tokeniser once shipped with its word boundaries corrupted into
    backspace bytes, matched no digits at all, and passed a case file claiming
    9,471 transactions. `scripts/verify_explanation_grader.py` exists because
    of it, and feeds the grader four known-bad case files that it must catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from detection.config import DetectorConfig

#: Phrases that assert certainty. Fine on a strong cluster, a problem on one the
#: detector has filed as ambiguous.
CERTAINTY_PHRASES = (
    "definitely", "certainly", "without a doubt", "no doubt",
    "conclusively", "proves", "proven", "unquestionably", "clearly fraud",
    "beyond doubt", "guaranteed",
)

#: Integers below this are ordinary English ("one card", "two of the four") and
#: are not treated as claims. It is the honest limit of the grounding check:
#: a small number is not really constrained, so the check bites on the larger
#: ones - counts, amounts, gaps - where fabrication would actually mislead.
#: `QualityReport` reports how many assertions fell either side of it.
FREE_NUMBER_CEILING = 32


@dataclass
class CaseFileScore:
    cluster_id: str
    score: float
    suggested_action: str
    grounded: bool
    calibrated: bool
    action_fits: bool
    findings: list[str] = field(default_factory=list)
    #: How much the grounding check actually bit on this case file.
    numbers_asserted: int = 0
    numbers_constrained: int = 0

    @property
    def passed(self) -> bool:
        return self.grounded and self.calibrated and self.action_fits


@dataclass
class QualityReport:
    scored: list[CaseFileScore] = field(default_factory=list)
    requested_sample: int = 15

    @property
    def total(self) -> int:
        return len(self.scored)

    @property
    def passes(self) -> int:
        return sum(1 for s in self.scored if s.passed)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.total if self.total else 0.0

    def failing(self, attribute: str) -> int:
        return sum(1 for s in self.scored if not getattr(s, attribute))

    @property
    def numbers_asserted(self) -> int:
        return sum(s.numbers_asserted for s in self.scored)

    @property
    def numbers_constrained(self) -> int:
        """Assertions the grounding check genuinely tested.

        Reported alongside the pass rate on purpose. A checker that examines
        almost nothing also reports 100%, so the reader needs both numbers to
        judge what the pass rate is worth.
        """
        return sum(s.numbers_constrained for s in self.scored)


def _numbers_in(body: str) -> set[int]:
    """Integers a case file asserts structurally, ignoring money and dates.

    Comma grouping has to be handled before tokenising. A naive \b\d{1,4}\b
    scan reads "3,328-8,608 INR, median 6,128" as the numbers 3, 328, 8, 608
    and 128 - none of which appear anywhere in the evidence - and duly reports
    three fabrications in a sentence that was entirely accurate. Currency also
    appears on both sides ("INR 4,500" and "4,500 INR"), so both forms are
    stripped.
    """
    # Join comma-grouped digits so they tokenise as one number.
    cleaned = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", body)
    # Currency, prefix and suffix forms.
    cleaned = re.sub(r"(?:INR|Rs\.?|₹)\s*[\d,]+(?:\.\d+)?", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[\d,]+(?:\.\d+)?\s*(?:INR|Rs\.?|₹)", " ", cleaned, flags=re.I)
    # Ranges of amounts: "3328-8608"
    cleaned = re.sub(r"\b\d{4,}\s*[-–]\s*\d{4,}\b", " ", cleaned)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", " ", cleaned)
    cleaned = re.sub(r"\d+\.\d+", " ", cleaned)              # scores, gaps
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)  # ISO dates
    return {int(n) for n in re.findall(r"\b\d{1,6}\b", cleaned)}


def _truthful_numbers(evidence: dict[str, Any], context: dict[str, Any]) -> set[int]:
    """Every number the case file could legitimately cite.

    Built from the SAME context the prompt was assembled from, not just the
    evidence blob. An earlier version allowed only the attribute counts, and
    consequently flagged every case file as fabricating - the amounts, dates and
    transaction totals it cited had all come from the prompt, and the grader
    simply did not know about them. A grounding check whose notion of "true" is
    narrower than what the model was told will report fabrication that is not
    there, which is worse than not checking at all.
    """
    allowed: set[int] = set()

    size = evidence.get("size")
    if isinstance(size, int):
        allowed.add(size)

    total_observations = 0
    for attribute in evidence.get("shared_attributes") or []:
        for key in ("customer_count", "observations"):
            value = attribute.get(key)
            if isinstance(value, int):
                allowed.add(value)
        total_observations += int(attribute.get("observations") or 0)
    allowed.add(total_observations)

    for value in (evidence.get("timing") or {}).values():
        if isinstance(value, (int, float)):
            allowed.add(int(value))
            allowed.add(round(value))

    # Everything the prompt actually put in front of the model.
    summary = context.get("amount_summary") or {}
    for key, value in summary.items():
        if not isinstance(value, (int, float)):
            continue
        allowed.add(int(value))
        if key.endswith("_paise"):
            allowed.add(int(value) // 100)          # the rupee figure
            allowed.add(round(int(value) / 100))
            allowed.add(int(value) // 100000)       # "1.5 lakh" style rounding

    for row in context.get("timeline") or []:
        for key in ("transactions", "accounts"):
            value = row.get(key)
            if isinstance(value, int):
                allowed.add(value)
        # Dates appear as prose: "28 August", "2026-08-28".
        when = str(row.get("when", ""))
        for part in when.split("-"):
            if part.isdigit():
                allowed.add(int(part))

    # Small integers are ordinary English ("one card", "two of the four").
    allowed.update(range(0, FREE_NUMBER_CEILING))
    return allowed


def grade_case_file(
    row: dict[str, Any], config: DetectorConfig, context: dict[str, Any] | None = None
) -> CaseFileScore:
    evidence = row["evidence_json"] or {}
    body = " ".join(
        [
            row["summary"] or "",
            row["confidence_note"] or "",
            " ".join(row["key_signals"] or []),
            " ".join(row["caveats"] or []),
        ]
    )
    findings: list[str] = []

    # ---- grounding -------------------------------------------------------
    known_refs = {
        str(a.get("external_ref", ""))
        for a in (evidence.get("shared_attributes") or [])
        if a.get("external_ref")
    }
    cited_refs = set(re.findall(r"\b(?:inst|dev|addr|cust)_[A-Za-z0-9_]{6,}", body))
    invented_refs = {
        ref
        for ref in cited_refs
        if not any(known.startswith(ref) or ref.startswith(known[:18])
                   for known in known_refs)
    }

    allowed_numbers = _truthful_numbers(evidence, context or {})
    asserted_numbers = _numbers_in(body)
    invented_numbers = asserted_numbers - allowed_numbers

    grounded = not invented_refs and not invented_numbers
    if invented_refs:
        findings.append(f"cites entity refs absent from the evidence: {sorted(invented_refs)[:2]}")
    if invented_numbers:
        findings.append(f"cites counts absent from the evidence: {sorted(invented_numbers)[:4]}")

    # ---- calibration -----------------------------------------------------
    lowered = body.lower()
    asserted = [p for p in CERTAINTY_PHRASES if p in lowered]
    ambiguous = float(row["score"]) < config.confident_score_threshold
    calibrated = not (asserted and ambiguous)
    if not calibrated:
        findings.append(
            f"asserts certainty ({asserted[0]!r}) on a cluster scoring "
            f"{row['score']:.3f}, inside the ambiguous band"
        )

    # ---- action fit ------------------------------------------------------
    action = row["suggested_action"]
    score = float(row["score"])
    action_fits = True
    if action == "likely_ring" and score < config.score_threshold:
        action_fits = False
        findings.append("calls it a likely ring on a cluster below the flag threshold")
    if action == "likely_false_positive" and score >= config.confident_score_threshold:
        action_fits = False
        findings.append(
            f"calls it a likely false positive at {score:.3f}, above the "
            f"confidence threshold"
        )

    return CaseFileScore(
        cluster_id=str(row["cluster_id"]),
        score=score,
        suggested_action=action,
        grounded=grounded,
        calibrated=calibrated,
        action_fits=action_fits,
        findings=findings,
        numbers_asserted=len(asserted_numbers),
        numbers_constrained=sum(
            1 for n in asserted_numbers if n >= FREE_NUMBER_CEILING
        ),
    )


def grade_all(
    db: Session, limit: int = 15, config: DetectorConfig | None = None
) -> QualityReport:
    config = config or DetectorConfig()
    rows = db.execute(
        text(
            """
            SELECT cf.cluster_id, cf.summary, cf.confidence_note,
                   cf.suggested_action::text AS suggested_action,
                   cf.key_signals, cf.caveats,
                   c.score, c.evidence_json
            FROM case_files cf
            JOIN clusters c ON c.id = cf.cluster_id
            ORDER BY cf.generated_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()

    from app.case_files import CaseFileError, gather_cluster_context

    report = QualityReport(requested_sample=limit)
    for row in rows:
        # Rebuild the same context the prompt was assembled from, so the
        # grader's notion of "true" matches what the model was actually told.
        try:
            context = gather_cluster_context(db, row["cluster_id"])
        except CaseFileError:
            context = {}
        report.scored.append(grade_case_file(dict(row), config, context))
    return report
