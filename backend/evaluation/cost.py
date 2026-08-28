"""What a false positive costs. EVERY NUMBER HERE IS AN ESTIMATE.

None of these figures were measured on this project. They are stated
assumptions with defensible reasoning, exposed in the API response and the
report so a reader can disagree with each one individually rather than having to
take a single opaque rupee figure on trust.

The model has two parts, and separating them matters:

  Review cost      Certain. Every false flag consumes analyst attention, whether
                   it is eventually approved or dismissed. This is real money
                   and it is incurred the moment a cluster enters the queue.

  Trust cost       CONTINGENT, and it is important to be precise about why.
                   RingSentinel never gates, blocks, or restricts an account -
                   there is no code path that can. So this cost cannot be
                   incurred by RingSentinel acting. It can only arise if a human
                   approves a false flag AND some downstream process then acts
                   on that approval. It is modelled here because "our tool
                   cannot cause harm" is not the same as "flagging carries no
                   risk", and pretending otherwise would make the scorecard
                   dishonest.

Reporting both separately means the certain cost is never inflated by the
speculative one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# ---------------------------------------------------------------------------
# Assumptions. Change these; do not bury them.
# ---------------------------------------------------------------------------

#: ESTIMATE. Time for an analyst to open a cluster, read the case file, look at
#: the graph, and reach a decision. Anchored on the case files actually produced
#: here: ~150 words plus an evidence table and a graph. Faster than a full
#: manual investigation, slower than a glance.
ANALYST_MINUTES_PER_REVIEW = 12

#: ESTIMATE. Fully-loaded hourly cost of a risk analyst in India - salary plus
#: employer overhead, tooling, and management load. Not a market survey.
ANALYST_COST_PER_HOUR_INR = 1_200

#: ESTIMATE. If a human approves a flag, how often a downstream process actually
#: restricts the account. Not 1.0, because approving a flag here means "this
#: looks coordinated", and a real operation would usually gather more before
#: acting.
P_APPROVED_FLAG_LEADS_TO_ACTION = 0.70

#: ESTIMATE. Probability a legitimate customer stops using the merchant after
#: being wrongly restricted once. Payments friction is a well-known churn driver,
#: but the specific figure is a modelling choice, not a measurement.
P_WRONGLY_GATED_CUSTOMER_CHURNS = 0.25

#: ESTIMATE. Average remaining lifetime value of a customer, in rupees. Wildly
#: merchant-dependent; a mid-size Indian e-commerce merchant is the mental model.
CUSTOMER_LIFETIME_VALUE_INR = 20_000


@dataclass(frozen=True)
class CostModel:
    """Per-false-positive cost, decomposed."""

    review_cost_per_fp_inr: float
    contingent_trust_cost_per_account_inr: float
    false_positives: int
    accounts_in_false_positives: int
    approved_false_positives: int

    @property
    def certain_review_cost_inr(self) -> float:
        """Analyst time. Incurred for every false flag, no contingency."""
        return self.false_positives * self.review_cost_per_fp_inr

    @property
    def contingent_trust_cost_inr(self) -> float:
        """Only accrues on false flags a human APPROVED.

        A false flag that a reviewer correctly dismissed cost time and nothing
        else - the human gate did its job.
        """
        if self.approved_false_positives == 0:
            return 0.0
        per_cluster_accounts = (
            self.accounts_in_false_positives / self.false_positives
            if self.false_positives
            else 0
        )
        return (
            self.approved_false_positives
            * per_cluster_accounts
            * self.contingent_trust_cost_per_account_inr
        )

    @property
    def total_inr(self) -> float:
        return self.certain_review_cost_inr + self.contingent_trust_cost_inr

    def to_dict(self) -> dict:
        return {
            "false_positives": self.false_positives,
            "certain_review_cost_inr": round(self.certain_review_cost_inr, 2),
            "contingent_trust_cost_inr": round(self.contingent_trust_cost_inr, 2),
            "total_inr": round(self.total_inr, 2),
            "review_cost_per_fp_inr": round(self.review_cost_per_fp_inr, 2),
            "contingent_trust_cost_per_account_inr": round(
                self.contingent_trust_cost_per_account_inr, 2
            ),
            "approved_false_positives": self.approved_false_positives,
            "note": (
                "Review cost is certain. Trust cost is contingent: RingSentinel "
                "never gates an account, so it can only arise if a human "
                "approves a false flag and a downstream process then acts."
            ),
        }


def assumptions() -> dict:
    """The inputs, surfaced so they can be argued with."""
    return {
        "analyst_minutes_per_review": ANALYST_MINUTES_PER_REVIEW,
        "analyst_cost_per_hour_inr": ANALYST_COST_PER_HOUR_INR,
        "p_approved_flag_leads_to_action": P_APPROVED_FLAG_LEADS_TO_ACTION,
        "p_wrongly_gated_customer_churns": P_WRONGLY_GATED_CUSTOMER_CHURNS,
        "customer_lifetime_value_inr": CUSTOMER_LIFETIME_VALUE_INR,
        "disclaimer": (
            "Every value above is an estimate chosen for this model, not a "
            "measurement taken from data. They are exposed so they can be "
            "replaced with a merchant's real figures."
        ),
    }


def build_cost_model(
    false_positives: int,
    accounts_in_false_positives: int,
    approved_false_positives: int = 0,
) -> CostModel:
    review_cost = (
        ANALYST_MINUTES_PER_REVIEW / 60.0
    ) * ANALYST_COST_PER_HOUR_INR

    trust_cost = (
        P_APPROVED_FLAG_LEADS_TO_ACTION
        * P_WRONGLY_GATED_CUSTOMER_CHURNS
        * CUSTOMER_LIFETIME_VALUE_INR
    )

    return CostModel(
        review_cost_per_fp_inr=review_cost,
        contingent_trust_cost_per_account_inr=trust_cost,
        false_positives=false_positives,
        accounts_in_false_positives=accounts_in_false_positives,
        approved_false_positives=approved_false_positives,
    )


def describe() -> dict:
    """Static description of the model, for /metrics and the report."""
    model = build_cost_model(1, 1, 0)
    return {
        "assumptions": assumptions(),
        "derived": {
            "review_cost_per_false_positive_inr": round(
                model.review_cost_per_fp_inr, 2
            ),
            "trust_cost_per_wrongly_gated_account_inr": round(
                model.contingent_trust_cost_per_account_inr, 2
            ),
        },
        "formula": {
            "review_cost": "(minutes / 60) x hourly_cost, per false positive",
            "trust_cost": (
                "p(action | approved) x p(churn | gated) x lifetime_value, "
                "per account, and only for false positives a human approved"
            ),
        },
    }


def _asdict(model: CostModel) -> dict:  # small helper kept for symmetry
    return asdict(model)
