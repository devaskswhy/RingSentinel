# How RingSentinel could make money

RingSentinel finds coordinated fraud rings by clustering an entity graph — which
accounts share a device, a shipping address, or a payment instrument — and has
Claude write a plain-language case file for each flagged cluster. A human
approves or dismisses every one. Nothing auto-blocks.

This document is about the commercial shape of that, and it is written to be
argued with. **Every figure below is either tagged `[MEASURED]` — observed on
this project — or `[ASSUMPTION]` / `[PRICING]`, meaning it is a stated guess or
a published rate card.** None of it is a market study, and I have not talked to
a merchant. Regenerate any of it with:

```bash
docker compose exec backend python -m scripts.monetization \
    --merchants 50 --transactions 2000
```

---

## The cost structure, and the thing it implies

Run at 50 merchants averaging 2,000 transactions a month — 100,000 transactions
scanned:

| | Value | Provenance |
|---|---|---|
| Assumed ring-fraud rate | 0.30% | `[ASSUMPTION]` — illustrative, chosen to make the arithmetic legible, **not researched** |
| Ring transactions surfaced | 300/month | derived |
| Fraud value exposed | **₹2,90,505/month** | derived, at a ₹968 mean ring ticket `[MEASURED]` on this project's synthetic corpus |
| Clusters a human must review | 6/month | derived, at 49.9 ring transactions per ring `[MEASURED]` on the same corpus |
| **Claude cost to scan it all** | **$0.07/month** warm, $0.25 cold | `[PRICING]` Sonnet $2/$10 per Mtok, applied to a `[MEASURED]` 12,730-in / 991-out token profile |
| Analyst cost to review those 6 | ₹1,442/month | `[MEASURED]` ₹240/cluster from `evaluation/cost.py`, itself an estimate |

Two things fall out of that table, and they are the whole commercial argument.

**The model bill is a rounding error, and that is structural rather than
clever.** Case files are written per *cluster*, not per transaction, and
detection itself makes no model calls at all — it is NetworkX and arithmetic,
and it is deterministic. The same 100,000 transactions scored one-model-call-per-
transaction would cost about **$160/month** (`[ASSUMPTION]`: 400 input / 80
output tokens per transaction), against $0.07. Roughly **2,100×**. That ratio is
a property of putting the model where language is needed and refusing to put it
where determinism is needed.

**Human attention costs ~219× what the tokens do** at this volume. So
RingSentinel cannot be priced cost-plus — a margin on $0.07 is not a business —
and it should not be sold as an inference-cost saving either. It has to be
priced against the analyst hours it removes and the fraud value it puts in front
of someone. It is also the reason precision is the product rather than a metric:
every false flag spends the expensive resource, not the cheap one.

One caveat that belongs next to the ₹2,90,505 and is easy to skip past.
**"Exposed" means surfaced to a human, not recovered, prevented, or saved.**
RingSentinel has no code path that can block, freeze, or decline anyone — that
is invariant #1 and a database trigger enforces it. Any figure framed as "fraud
stopped" would be false, and the distinction matters for the pricing shapes
below.

---

## Three pricing shapes

**Per-merchant SaaS.** A flat monthly fee per merchant scanned, tiered by
transaction volume. This is the easiest to sell and the easiest to forecast: the
cost base is ~$0.0015 per merchant per month in model spend (derived from the
table above), so gross margin is effectively 100% and the real cost is support
and the analyst tooling around it. It also fits how a merchant thinks about
risk tooling — a line item, not a variable. The weakness is that it prices the
scan rather than the outcome, so a merchant with no rings pays the same as one
with a crew working them over, and the first is the one who churns. It is the
right shape for getting to revenue, and the wrong shape for capturing what the
product is actually worth.

**Revenue-share on fraud prevented.** Superficially the most attractive — align
the price with the value, take a percentage of losses avoided. I do not think
this one survives contact with how RingSentinel is built, and the reason is
worth stating rather than hiding. RingSentinel does not prevent anything. It
surfaces clusters and a human decides; whatever happens next happens in a
system this codebase cannot reach. So "fraud prevented" is not measurable and
not attributable, and any number attached to it would be a negotiation rather
than a measurement. Making it work would mean agreeing a counterfactual with the
merchant in advance — a baseline chargeback rate, say — which is a pricing
argument every quarter and an incentive to flag aggressively. Given that
precision is the entire quality claim, a pricing model that rewards more flags
is the wrong one to build.

**Embedded in the PSP.** The aggregator pays, not the merchant — RingSentinel
becomes a platform capability rather than a product a merchant buys. This is the
only one of the three that captures the thing that is genuinely defensible.
Rings cross merchant boundaries, and a single merchant only ever sees its own
slice; the crew testing cards on one storefront is farming promos on another.
Because `entities.external_ref` stores salted opaque tokens and never raw PII,
two merchants can be compared on hashed device and instrument references
without either learning who the other's customers are — so an aggregator sitting
across many merchants can assemble a cross-merchant graph that none of them
could build alone, and that no merchant-side vendor can replicate. That is a
network effect rather than a feature, it gets stronger with every merchant
added, and it argues for the PSP as the buyer. The trade-off is honest: it is
one long enterprise sale instead of many small ones, and the roadmap belongs to
someone else afterwards.

If I had to choose: **per-merchant SaaS to prove it works, embedded-in-PSP as
the actual business.** Revenue-share reads well on a slide and I would avoid it.

---

## Where this fits in Agent Studio

Razorpay's [Agent Studio](https://razorpay.com/agent-studio/) — launched
12 March 2026 and, in Razorpay's own words, *"Built on Anthropic's Claude Agent
SDK"* — offers three routes on its page: *"Customize a Prebuilt Agent"*, *"Build
your agent from scratch"* (beta), and *"Onboard as an AI partner"*. RingSentinel
is already an Agent SDK application with an explicit guardrail model, so the
third is the honest fit: it is not a workflow assembled from prebuilt pieces,
it is a detector with its own graph model, its own evidence schema, and an
authority boundary where the agent explains and never decides. Razorpay's launch
post says Agent Studio *"will also evolve into an open ecosystem for developers
and fintech partners"* where *"third-party builders will be able to create and
publish specialized agents"* — and names the example range as *"industry-specific
fraud detection systems to automated tax reconciliation tools"*
([blog](https://razorpay.com/blog/agent-studio-ai-agents-by-razorpay/),
12 March 2026). That first example is precisely this. The commercial read is
that the partner route and the embedded-in-PSP shape above are the same path
described from two sides: the aggregator gets a capability none of its merchants
could build alone, and the cross-merchant graph only exists at that layer.

*Razorpay has not reviewed or endorsed this project. Agent Studio is referenced
because it is built on the same SDK and because its partner pathway is the
public, documented route for exactly this kind of integration.*

---

## What I am not claiming

- **The 0.3% ring-fraud rate is illustrative.** It is not researched and should
  not be quoted. Published card-testing and promo-abuse rates vary by orders of
  magnitude across merchant categories; pass `--ring-rate` and see how hard the
  output moves.
- **The corpus figures do not generalise.** ₹968 per ring transaction and 49.9
  transactions per ring are `[MEASURED]`, but measured on a synthetic corpus
  this project generated, with an archetype mix I chose. Card-testing rings drag
  the mean ticket down hard; a merchant whose exposure is return-abuse would see
  a very different number. See §5b-eval in [CLAUDE.md](CLAUDE.md) for why the
  detection results carry the same caveat.
- **The dollar costs are a re-pricing, not a measurement.** The token profile is
  real — 15 case files, stored in `case_files` with their usage. Those calls ran
  on `claude-opus-5` and cost $0.0880 each on average (range $0.0623–$0.1471).
  The figures above apply the published Sonnet rate card to those same token
  counts. Batch API would halve them again and is not applied, so the estimate
  errs high.
- **₹88/USD** is an `[ASSUMPTION]`, used only to compare the model bill against
  the analyst bill.
- **No customer has been asked what they would pay.** Everything here is a shape
  and an arithmetic sanity check, not validation.
