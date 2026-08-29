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
