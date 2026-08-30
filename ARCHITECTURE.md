# RingSentinel — architecture

Fraud rings are invisible at the level of a single transaction and obvious at
the level of a graph. RingSentinel does not score transactions. It builds a
graph of which accounts share a device, a shipping address, or a payment
instrument, flags the dense clusters, has Claude explain each one in plain
language, and puts a human in front of every decision.

Full design notes, invariants, and measured results live in
[CLAUDE.md](CLAUDE.md). This file covers the shape of the system and two
questions people ask about it.

---

## The pipeline

```
Razorpay test-mode orders
        │
        ▼
POST /webhooks/razorpay ──── HMAC-SHA256 over the raw body
        │
        ▼
app/ingest.py ──────────────  entities · entity_links · transactions
        │                     (idempotent: ON CONFLICT DO NOTHING)
        ▼
detection/ ─────────────────  NetworkX graph → clusters → four-signal score
        │                     deterministic; reads a label-free view only
        ▼
app/case_files.py ──────────  Claude writes the explanation
        │                     no tools, no ability to decide
        ▼
app/routers/clusters.py ────  THE HUMAN GATE
                              approve / dismiss, written reason required
                              enforced by a Postgres trigger
```

Two package boundaries carry real weight:

- **`detection/` may not read ground-truth labels** or import `evaluation.*`.
  `scripts/verify_detector_isolation.py` walks the AST and fails if it does.
- **`app/routers/clusters.py` is the only code that may record a decision.**
  `detection/pipeline.py` may triage between `pending` and `needs_review`;
  nothing else may touch status at all. `scripts/verify_human_gate.py` proves
  it statically and at runtime.

---

## Where Claude is used, and where it deliberately is not

RingSentinel runs on the **Claude Agent SDK** — the same SDK Razorpay used to
build its own Agent Studio, launched 12 March 2026 at FTX'26.

Claude is used for exactly one thing: writing the case file that explains a
flagged cluster to the analyst reviewing it. The detection itself is
deterministic graph and statistics work — NetworkX connected components, a
saturating attribute-reuse function, a coefficient of variation on
inter-transaction gaps. No model output influences whether a cluster is
flagged, what it scores, or what happens to it. Claude explains; it does not
detect and it does not decide, and it runs with `allowed_tools=[]` so there is
no function for it to call even if the prompt were subverted.

That split is the point. An LLM asked to score 1,499 transactions would be
slower, more expensive, non-reproducible, and impossible to audit — and it
would be worse at the task, because the signal lives in the graph structure
rather than in any individual transaction's text. Using a model for the part
that genuinely needs language, and refusing to use it for the part that needs
determinism, is what "AI applied appropriately rather than forced in" means
here. It is also why the same cluster scores identically on every run, and why
every score decomposes into named signals a reviewer can argue with.

For the same reason, this shape would sit naturally inside Agent Studio's
"Build Custom Agents" path: it is already an Agent SDK application with an
explicit guardrail model, where the agent's authority ends at explanation.

*Razorpay has not reviewed or endorsed this project. Agent Studio is referenced
only to note that it is built on the same SDK.*

---

## What happens when things fail

Every failure below is handled in code and demonstrated by
`scripts/verify_resilience.py`, which breaks each one for real and names the
mechanism that absorbs it. Database checks roll back.

| Failure | Fallback |
|---|---|
| Database connection dropped | `pool_pre_ping` replaces the dead connection transparently |
| Model returns malformed output | Tolerant parser; unknown action degrades to a labelled `review_closer`; truncated JSON raises before anything is written |
| Model call fails outright | `CaseFileError` before any write — the cluster keeps its previous case file |
| Payment API returns 429 | A `requests` response hook reads the real status the SDK discards, then backs off honouring `Retry-After` |
| Webhook delivered twice | Unique constraints plus `ON CONFLICT DO NOTHING` — the replay is a no-op |
| Forged signature / unusable payload | 401, and 400 respectively, so Razorpay stops retrying what can never succeed |

```bash
docker compose exec backend python -m scripts.verify_resilience
```

---

## Where it is weak

[BLINDSPOTS.md](BLINDSPOTS.md) is generated from a live measurement, not
written by hand. It runs three cases built to sit exactly where the scoring is
weakest — a ring paced like people, a household that genuinely shares one
address, and a ring spread thinly over two months — and grades 15 generated
case files for fabricated evidence and overclaiming. The cases go in through
the real ingest path and are rolled back, so nothing persists.

The honest headline is that it came out better than predicted, which is
reported with its limits attached: three cases cannot carry a percentage, and
the cases share an author with the detector, so they probe the weaknesses we
already knew about. The one real finding is that a ring paced like people
clears the flag threshold but not the confidence threshold — found, but found
weakly.

Case files are graded mechanically rather than by a model, because a model
auditing its own output shares its own blind spots. That grader is itself
tested: `scripts/verify_explanation_grader.py` feeds it four known-bad case
files and requires each to be caught by the criterion meant to catch it. That
check earned its place — the tokeniser once shipped with its word boundaries
corrupted into control characters, matched no digits at all, and passed a case
file claiming 9,471 transactions while reporting a perfect score.

---

## The evidence pack

`GET /clusters/{id}/evidence-pack` returns one self-contained bundle for a
decided cluster: the evidence and its per-signal breakdown, Claude's
explanation, the human's written reason, and the slice of the audit chain that
proves those rows have not been altered since.

Every `audit_log` row stores `sha256(previous row's hash || this row)`. The
append-only trigger *blocks* tampering; the chain makes it *detectable* — even
against someone who drops the trigger first, because they cannot make every
subsequent hash still add up.

`scripts/verify_human_gate.py` is the thing to hand someone who wants to check
rather than be told. It inspects the schema directly — every guarding trigger,
the label-free detector view, the chain end to end — and exits non-zero the
moment one is broken. Both failure modes were tested by actually breaking them:
rewriting an audit row was caught as *"the row's contents no longer hash to its
recorded hash"*, and dropping the guard trigger was caught as a missing trigger.

A note on wording: the bundle carries a `bundle_digest`, which is a **checksum,
not a signature**. It detects corruption in transit and proves nothing about
origin, because there is no key. The chain is the integrity guarantee.

This maps onto what RBI's 2026 draft *Guidance on Regulatory Principles for
Model Risk Management* asks for — human oversight of automated decisions,
reviewers able to genuinely challenge rather than rubber-stamp, and disclosed
reasoning for models that would otherwise be black boxes. That guidance is a
**draft**, **non-binding**, and its scope covers banks, NBFCs and payments banks
rather than payment aggregators, so it does not bind Razorpay. Many of
Razorpay's own merchants would be directly on the hook for it, and this is
plainly the direction the regulation is heading.

---

## How it could make money

Case files are generated per **cluster**, not per transaction. The seeded corpus
is 1,499 transactions and 12 clusters, so the model bill is roughly three orders
of magnitude smaller than a per-transaction design — a property of the graph
approach rather than an optimisation. Measured cost per case file is **$0.028
warm / $0.147 cold** (the difference is entirely prompt caching), which makes
per-merchant pricing straightforward to reason about.

The larger opportunity is structural rather than per-seat: rings cross merchant
boundaries, and a single merchant only ever sees its own slice. Because
`entities.external_ref` stores salted, opaque tokens and never raw PII, two
merchants could compare hashed device and instrument references and discover
shared infrastructure without either learning who the other's customers are.
That is a network only an aggregator sitting across many merchants could
assemble — which is a different and more defensible product than a tool sold one
merchant at a time.

[MONETIZATION.md](MONETIZATION.md) works that through: three pricing shapes,
where the Agent Studio partner pathway fits, and an arithmetic sanity check with
every input tagged as measured, priced, or assumed.

```bash
docker compose exec backend python -m scripts.monetization --merchants 50 --transactions 2000
```

The number that shapes the argument: at 100,000 transactions a month the model
bill is **$0.07** and the analyst bill for the clusters it surfaces is
**₹1,442** — human attention costs ~219× what the tokens do. So this cannot be
priced cost-plus, and precision is the product rather than a metric, because
every false flag spends the expensive resource rather than the cheap one.
