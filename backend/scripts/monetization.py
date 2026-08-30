"""Project what RingSentinel would cost and expose at merchant scale.

    docker compose exec backend python -m scripts.monetization
    docker compose exec backend python -m scripts.monetization \
        --merchants 50 --transactions 2000 --ring-rate 0.003

EVERY OUTPUT LINE IS A PROJECTION, and every input to it is tagged with where
it came from:

    [INPUT]       you passed it on the command line
    [MEASURED]    observed on this project - the corpus, or real Claude calls
    [PRICING]     published rate card, cited in the source below
    [ASSUMPTION]  illustrative. Not researched, not a market figure.

The tags are not decoration. The headline number is only as good as the
assumption it rests on, and a reader who cannot see which is which has no way
to disagree with the parts they doubt. `scripts/report.py` takes the same line
with the false-positive cost model, and `evaluation/cost.py` says why.

What this deliberately does NOT claim
-------------------------------------
"Fraud value exposed" is the rupee volume flowing through transactions that
these assumptions place inside rings. It is value **put in front of a human**,
not value recovered, prevented, or saved. RingSentinel cannot block anything -
no code path in this repository can restrict an account - so any figure framed
as "fraud stopped" would be false on its face. See invariant #1 in CLAUDE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

# ---------------------------------------------------------------------------
# [MEASURED] - observed on this project. Real, but narrow: a synthetic corpus
# this project generated, with an archetype mix we chose. See CLAUDE.md 5b-eval
# for why these numbers do not generalise to a real merchant.
# ---------------------------------------------------------------------------

#: Corpus shape, from the seeded run: 599 ring transactions across 12 rings.
CORPUS_RING_TRANSACTIONS = 599
CORPUS_RINGS = 12

#: Ring transactions per ring. Card-testing rings run long and cheap, so this
#: is pulled down hard by the archetype mix rather than being a natural
#: constant. It is the lever the estimate is most sensitive to.
CORPUS_TRANSACTIONS_PER_RING = CORPUS_RING_TRANSACTIONS / CORPUS_RINGS  # 49.9

#: Mean ring transaction value, in paise, across the seeded corpus. Far below
#: the normal-traffic mean (Rs 3,368) because card-testing probes with Rs 1-49
#: orders. A merchant whose ring exposure is return-abuse rather than
#: card-testing would see a much larger figure.
CORPUS_AVG_RING_TICKET_PAISE = 96_835

#: Token profile of one case file, averaged over the 15 generations stored in
#: `case_files`. Input is dominated by the system prompt and the cluster
#: context; output is the JSON case file itself.
CASE_FILE_INPUT_TOKENS = 12_730
CASE_FILE_OUTPUT_TOKENS = 991

#: What those 15 generations actually cost, on claude-opus-5. Reported for
#: comparison only - the projection below prices Sonnet, per the rate card.
MEASURED_OPUS_MEAN_USD = 0.0880
MEASURED_OPUS_RANGE_USD = (0.0623, 0.1471)

# ---------------------------------------------------------------------------
# [PRICING] - published rate card, verified 2026-08-30.
#   https://platform.claude.com/docs/en/about-claude/pricing
#   https://platform.claude.com/docs/en/build-with-claude/prompt-caching
# Re-check before quoting; rate cards move.
# ---------------------------------------------------------------------------

SONNET_INPUT_USD_PER_MTOK = 2.00
SONNET_OUTPUT_USD_PER_MTOK = 10.00

#: Prompt-caching multipliers on the base input rate. A 5-minute cache write
#: costs 1.25x, a cache read 0.1x. Batch API would halve these again; it is not
#: applied below, so the estimate errs high.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

#: [MEASURED] Analyst review cost, from `evaluation/cost.py`: 12 minutes at a
#: fully-loaded Rs 1,200/hour. Itself an estimate there, and flagged as one.
ANALYST_COST_PER_CLUSTER_PAISE = 240 * 100

# ---------------------------------------------------------------------------
# [ASSUMPTION] - illustrative only. Change them; do not bury them.
# ---------------------------------------------------------------------------

#: Share of transactions belonging to a coordinated ring. NOT a researched
#: figure and not defensible as one - it is a round number chosen to make the
#: arithmetic legible. Published card-testing and promo-abuse rates vary by
#: orders of magnitude across merchant categories.
DEFAULT_RING_RATE = 0.003

#: What it would cost to send every transaction to a model instead of scoring
#: the graph - the design RingSentinel exists to avoid. Tokens per transaction
#: are a guess at a minimal scoring prompt plus a one-line verdict.
PER_TRANSACTION_INPUT_TOKENS = 400
PER_TRANSACTION_OUTPUT_TOKENS = 80


#: One crore, in rupees. Above this, digit grouping stops being readable and
#: the column overflows, so large figures switch to crore notation.
ONE_CRORE_RUPEES = 10_000_000


def rupees(paise: int | float) -> str:
    """Format paise as rupees, Indian digit grouping, crores above a crore."""
    whole = int(round(paise / 100))
    if abs(whole) >= ONE_CRORE_RUPEES:
        return f"Rs {whole / ONE_CRORE_RUPEES:,.2f} Cr"
    text = str(abs(whole))
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        text = ",".join(groups + [tail])
    return f"Rs {'-' if whole < 0 else ''}{text}"


@dataclass(frozen=True)
class Scenario:
    merchants: int
    transactions_per_merchant: int
    ring_rate: float
    avg_ring_ticket_paise: int
    transactions_per_ring: float

    @property
    def transactions_per_month(self) -> int:
        return self.merchants * self.transactions_per_merchant

    @property
    def ring_transactions_per_month(self) -> float:
        return self.transactions_per_month * self.ring_rate

    @property
    def fraud_value_exposed_paise(self) -> int:
        return int(round(self.ring_transactions_per_month * self.avg_ring_ticket_paise))

    @property
    def clusters_per_month(self) -> float:
        """Case files are written per cluster, so this - not transaction
        volume - is what the model bill actually scales with."""
        return self.ring_transactions_per_month / self.transactions_per_ring


def case_file_usd(warm: bool) -> float:
    """Cost of one case file at Sonnet rates, cached or not."""
    multiplier = CACHE_READ_MULTIPLIER if warm else CACHE_WRITE_MULTIPLIER
    inputs = CASE_FILE_INPUT_TOKENS * SONNET_INPUT_USD_PER_MTOK * multiplier / 1e6
    outputs = CASE_FILE_OUTPUT_TOKENS * SONNET_OUTPUT_USD_PER_MTOK / 1e6
    return inputs + outputs


def per_transaction_usd(transactions: int) -> float:
    """The counterfactual: one model call per transaction, no caching."""
    inputs = transactions * PER_TRANSACTION_INPUT_TOKENS * SONNET_INPUT_USD_PER_MTOK / 1e6
    outputs = (
        transactions * PER_TRANSACTION_OUTPUT_TOKENS * SONNET_OUTPUT_USD_PER_MTOK / 1e6
    )
    return inputs + outputs


def estimate(scenario: Scenario) -> dict:
    clusters = scenario.clusters_per_month
    warm = clusters * case_file_usd(warm=True)
    cold = clusters * case_file_usd(warm=False)
    analyst_paise = clusters * ANALYST_COST_PER_CLUSTER_PAISE
    return {
        "transactions_per_month": scenario.transactions_per_month,
        "ring_transactions_per_month": scenario.ring_transactions_per_month,
        "fraud_value_exposed_paise": scenario.fraud_value_exposed_paise,
        "clusters_per_month": clusters,
        "claude_cost_usd_warm": warm,
        "claude_cost_usd_cold": cold,
        "claude_cost_per_merchant_usd_warm": (
            warm / scenario.merchants if scenario.merchants else 0.0
        ),
        "analyst_review_cost_paise": analyst_paise,
        "per_transaction_design_usd": per_transaction_usd(
            scenario.transactions_per_month
        ),
    }


def usd(amount: float, places: int = 2) -> str:
    """Right-aligned dollars with the sign next to the digits, not the margin."""
    return f"${amount:,.{places}f}".rjust(12)


def render(scenario: Scenario, result: dict, usd_inr: float) -> str:
    out: list[str] = []
    a = out.append
    rule = "=" * 74

    a(rule)
    a("  RingSentinel - what scanning this volume would cost, and expose")
    a("  EVERY FIGURE IS A PROJECTION. Provenance is tagged on every input.")
    a(rule)
    a("")
    a("  SCOPE")
    a(f"    merchants scanned                 {scenario.merchants:>12,}   [INPUT]")
    a(f"    transactions / merchant / month   "
      f"{scenario.transactions_per_merchant:>12,}   [INPUT]")
    a(f"    transactions / month              "
      f"{result['transactions_per_month']:>12,}   = derived")
    a("")
    a("  RING EXPOSURE")
    a(f"    assumed ring-fraud rate           "
      f"{scenario.ring_rate:>12.2%}   [ASSUMPTION - illustrative, not researched]")
    a(f"    ring transactions / month         "
      f"{result['ring_transactions_per_month']:>12,.0f}   = derived")
    a(f"    mean ring transaction value       "
      f"{rupees(scenario.avg_ring_ticket_paise):>12}   [MEASURED - this corpus only]")
    a(f"    fraud value exposed / month       "
      f"{rupees(result['fraud_value_exposed_paise']):>12}   = derived")
    a("")
    a("      \"Exposed\" means surfaced to a human reviewer. Not recovered, not")
    a("      prevented, not saved - RingSentinel cannot block anything.")
    a("")
    a("  REVIEW LOAD")
    a(f"    ring transactions per ring        "
      f"{scenario.transactions_per_ring:>12.1f}   [MEASURED - this corpus only]")
    a(f"    clusters surfaced / month         "
      f"{result['clusters_per_month']:>12,.0f}   = derived")
    a(f"    analyst cost to review them       "
      f"{rupees(result['analyst_review_cost_paise']):>12}   [MEASURED - Rs 240/cluster, "
      f"evaluation/cost.py]")
    a("")
    a("  CLAUDE COST TO SCAN THAT VOLUME")
    a(f"    per case file, cache warm         "
      f"{usd(case_file_usd(warm=True), 4)}   [PRICING - Sonnet $2/$10 per Mtok]")
    a(f"    per case file, cache cold         "
      f"{usd(case_file_usd(warm=False), 4)}   [PRICING - 1.25x cache write]")
    a(f"    monthly, cache warm               "
      f"{usd(result['claude_cost_usd_warm'])}   = derived")
    a(f"    monthly, cache cold               "
      f"{usd(result['claude_cost_usd_cold'])}   = derived")
    a(f"    per merchant / month              "
      f"{usd(result['claude_cost_per_merchant_usd_warm'], 4)}   = derived")
    a("")
    a(f"      Token profile is [MEASURED]: {CASE_FILE_INPUT_TOKENS:,} in / "
      f"{CASE_FILE_OUTPUT_TOKENS:,} out, averaged over 15")
    a(f"      real generations. Those ran on claude-opus-5 and cost "
      f"${MEASURED_OPUS_MEAN_USD:.4f} each")
    a(f"      (range ${MEASURED_OPUS_RANGE_USD[0]:.4f}-"
      f"${MEASURED_OPUS_RANGE_USD[1]:.4f}). The dollar figures above re-price")
    a("      those same token counts at Sonnet rates; they are not a Sonnet")
    a("      measurement. Batch API would halve them again and is not applied.")
    a("")
    a("  WHY THE GRAPH APPROACH IS THE COST STORY")
    a(f"    one model call per transaction    "
      f"{usd(result['per_transaction_design_usd'])}   [ASSUMPTION - "
      f"{PER_TRANSACTION_INPUT_TOKENS}/{PER_TRANSACTION_OUTPUT_TOKENS} tok/txn]")
    a(f"    RingSentinel, same volume         "
      f"{usd(result['claude_cost_usd_warm'])}   = derived")
    if result["claude_cost_usd_warm"] > 0:
        ratio = result["per_transaction_design_usd"] / result["claude_cost_usd_warm"]
        a(f"    ratio                             {ratio:>11,.0f}x   = derived")
    a("")
    a("      Detection itself makes no model calls at all - it is NetworkX and")
    a("      arithmetic, and it is deterministic. Claude is invoked once per")
    a("      flagged cluster to explain it. That is why the bill tracks rings")
    a("      found rather than transactions scanned.")
    a("")
    a(rule)
    a("  THE NUMBER THAT ACTUALLY MATTERS")
    a(rule)
    analyst_usd = result["analyst_review_cost_paise"] / 100 / usd_inr
    a("")
    a(wrap_line(
        f"At this volume the model bill is ${result['claude_cost_usd_warm']:.2f}/month "
        f"and the analyst bill is {rupees(result['analyst_review_cost_paise'])}/month "
        f"(~${analyst_usd:.2f} at an assumed Rs {usd_inr:.0f}/USD). Human attention "
        f"costs roughly "
        f"{analyst_usd / result['claude_cost_usd_warm']:,.0f}x what the tokens do."
    ))
    a("")
    a(wrap_line(
        "So this cannot be priced cost-plus - the cost is a rounding error, and "
        "a margin on a rounding error is not a business. It has to be priced "
        "against the analyst hours it removes and the fraud value it surfaces. "
        "It is also why precision is the product: every false flag spends the "
        "expensive resource, not the cheap one."
    ))
    a("")
    a(rule)
    return "\n".join(out)


def wrap_line(body: str, width: int = 70, indent: str = "  ") -> str:
    import textwrap

    return textwrap.fill(
        " ".join(body.split()), width=width, initial_indent=indent,
        subsequent_indent=indent,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project RingSentinel's cost and exposure at merchant scale.",
        epilog="Every output line is a projection, not a measurement.",
    )
    parser.add_argument("--merchants", type=int, default=50,
                        help="Merchants scanned (default: 50)")
    parser.add_argument("--transactions", type=int, default=2_000,
                        help="Avg monthly transactions per merchant (default: 2000)")
    parser.add_argument("--ring-rate", type=float, default=DEFAULT_RING_RATE,
                        help="Assumed share of transactions in a ring "
                             "(default: 0.003 = 0.3%%, illustrative only)")
    parser.add_argument("--avg-ring-ticket", type=float, default=None,
                        help="Mean ring transaction value in RUPEES "
                             "(default: measured on this corpus)")
    parser.add_argument("--transactions-per-ring", type=float,
                        default=CORPUS_TRANSACTIONS_PER_RING,
                        help="Ring transactions per ring (default: measured here)")
    parser.add_argument("--usd-inr", type=float, default=88.0,
                        help="ASSUMPTION. Rate used only to compare the two "
                             "bills (default: 88)")
    parser.add_argument("--json", action="store_true",
                        help="Emit the estimate as JSON instead")
    args = parser.parse_args()

    if args.merchants < 1 or args.transactions < 1:
        print("merchants and transactions must both be at least 1", file=sys.stderr)
        return 2
    if not 0 < args.ring_rate < 1:
        print("--ring-rate is a fraction: 0.003 means 0.3%", file=sys.stderr)
        return 2

    ticket_paise = (
        int(round(args.avg_ring_ticket * 100))
        if args.avg_ring_ticket is not None
        else CORPUS_AVG_RING_TICKET_PAISE
    )
    scenario = Scenario(
        merchants=args.merchants,
        transactions_per_merchant=args.transactions,
        ring_rate=args.ring_rate,
        avg_ring_ticket_paise=ticket_paise,
        transactions_per_ring=args.transactions_per_ring,
    )
    result = estimate(scenario)

    if args.json:
        print(json.dumps(
            {
                "scenario": asdict(scenario),
                "estimate": result,
                "disclaimer": (
                    "Every figure is a projection. The ring-fraud rate is an "
                    "illustrative assumption, not a researched figure. Corpus "
                    "figures are measured on a synthetic corpus this project "
                    "generated and do not generalise to a real merchant."
                ),
            },
            indent=2,
        ))
        return 0

    print(render(scenario, result, args.usd_inr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
