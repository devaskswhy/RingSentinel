# CLAUDE.md — RingSentinel

> **Read this file first, before touching any code, in every session.**
> It is the single source of truth for what RingSentinel is, what the stack is
> fixed to, and which invariants must never be broken. If something here
> conflicts with an instinct or a convenient shortcut, this file wins. When a
> decision in here turns out to be wrong, update this file in the same commit
> that changes the behaviour.

---

## 1. What RingSentinel is

RingSentinel detects **coordinated fraud rings** — card-testing, promo-farming,
and return-abuse crews — for the **Razorpay buildathon, AI Risk Manager track**.

The core bet: fraud rings are invisible at the level of a single transaction and
obvious at the level of a graph. So RingSentinel does **not** score individual
transactions. It builds a graph of which accounts share a **device**, a
**shipping address**, or a **bank account / payment instrument**, and flags dense
clusters in that graph.

Every flagged cluster gets a **plain-language case file** written by Claude,
explaining in human terms why the cluster looks coordinated.

**Nothing auto-blocks. Ever.** A human approves or dismisses every single flag,
and every decision is written to an append-only audit log.

### Non-negotiable product invariants

| # | Invariant | How it is enforced |
|---|---|---|
| 1 | No automated blocking, freezing, or declining of any customer | No code path may call a block/decline action. Clusters only ever change `status`, and only from a human review action. |
| 2 | Every **decision** is human-made | The detector may triage between `pending` and `needs_review` — both mean "a human still has to look at this". Only a human review action may record a **decision** (`cleared` / `dismissed`), and once recorded it can never be revised. Enforced by `trg_clusters_status_human_only` (migration 0005). |
| 3 | Every decision is logged and never rewritten | `audit_log` is append-only (trigger raises on UPDATE / DELETE / TRUNCATE), and a decided cluster's status is itself immutable — otherwise the row could contradict the log. |
| 4 | The detector never sees ground truth | `transactions.is_synthetic_ring_id` is an evaluation label only. Detection code reads the `v_transactions_detector` view, which does not contain the column. |
| 5 | Razorpay is TEST MODE only | Keys must start with `rzp_test_`; `Settings.razorpay_is_test_mode` gates usage. A live key (`rzp_live_`) must never appear in this repo, in any env file, or in any log. |
| 6 | Claude explains, humans decide | Claude writes case files and reasoning. Claude never sets a final status. Its actions are logged with `actor = 'claude'`. |

---

## 2. Tech stack — FIXED, do not substitute

| Layer | Choice | Version pinned |
|---|---|---|
| Backend | Python + FastAPI | 3.11+, FastAPI 0.141.1 |
| Database | PostgreSQL (Docker Compose locally) | postgres:16-alpine |
| Migrations | Alembic | 1.19.1 |
| ORM / driver | SQLAlchemy 2.x + psycopg3 | 2.0.52 / 3.3.4 |
| Graph + detection | NetworkX | 3.6.1 |
| LLM layer | Claude Agent SDK (subscription OAuth) | claude-agent-sdk 0.2.144 |
| Frontend | Next.js App Router + TypeScript + Tailwind | Next 16.3.2, React 19.2.8, Tailwind 4.3.3 |
| Payments | Razorpay SDK, **test mode only** | razorpay 2.0.1 |

Do not swap any of these for an alternative (no Neo4j, no Prisma, no Drizzle, no
LangChain, no OpenAI). If a substitution seems necessary, raise it rather than
doing it silently.

Notes on the pins:
- **Tailwind v4** is configured through PostCSS (`@tailwindcss/postcss`). There is
  no `tailwind.config.js` — that is correct, not missing.
- **TypeScript is pinned to 5.9.3**, not 7.x, because the Next 16 toolchain has
  not been validated against the TS 7 native port here.

---

## 3. Repository layout

```
RingSentinel/
├── CLAUDE.md              <- this file; read first
├── README.md              <- setup steps only
├── .env.example           <- every required variable, with provenance comments
├── docker-compose.yml     <- db + backend + frontend
├── backend/
│   ├── entrypoint.sh          <- alembic upgrade head, then uvicorn
│   ├── alembic/versions/      <- 0001 schema · 0002 evidence · 0003 case files
│   │                             + status guard · 0004 fingerprint · 0005
│   │                             evaluation_runs + triage guard
│   ├── app/
│   │   ├── config.py          <- pydantic-settings
│   │   ├── db.py · models.py  <- engine/session · the ORM schema
│   │   ├── main.py            <- health, /eval/corpus, router mounting
│   │   ├── razorpay_client.py <- test-mode-only client: pacing, 429 retry
│   │   ├── ingest.py          <- event -> entities/entity_links/transactions
│   │   ├── webhooks.py        <- POST /webhooks/razorpay, HMAC verification
│   │   ├── prompts.py         <- the explain-only system prompt
│   │   ├── case_files.py      <- Claude Agent SDK integration
│   │   └── routers/
│   │       ├── clusters.py    <- THE HUMAN GATE. Only writer of a decision.
│   │       └── evaluation.py  <- /eval/scorecard and /metrics
│   ├── generator/             <- Phase 2 synthetic corpus (pure, no network)
│   │   ├── config.py          <- seed, ring specs, held-out split, volumes
│   │   ├── identities.py      <- opaque token pools (no PII is ever created)
│   │   ├── cadence.py         <- human vs agent timing models
│   │   ├── archetypes.py      <- the six named archetype generators
│   │   ├── normal.py          <- uncorrelated background traffic
│   │   ├── planned.py         <- PlannedTransaction + Razorpay notes mapping
│   │   └── plan.py            <- assembles the whole corpus
│   ├── detection/             <- MAY NOT READ LABELS. Enforced by AST check.
│   │   ├── config.py          <- every threshold and weight, in one place
│   │   ├── graph.py           <- entity_links -> NetworkX, hub filtering
│   │   ├── clustering.py      <- components + Louvain refinement
│   │   ├── baseline.py        <- label-free population timing baseline
│   │   ├── cadence.py         <- human / agent / inconclusive
│   │   ├── scoring.py         <- the four signals + evidence assembly
│   │   └── pipeline.py        <- orchestration, fingerprint upsert, triage
│   ├── evaluation/            <- MAY read labels. Never imported by detection/.
│   │   ├── splits.py          <- tuning vs held-out; opaque exclusion sets
│   │   ├── report.py          <- ring/cluster matching rules
│   │   ├── metrics.py         <- precision, recall, exceptions, storage
│   │   └── cost.py            <- false-positive cost model (all estimates)
│   └── scripts/
│       ├── seed.py · seed_rings.py        <- schema check · the corpus seed
│       ├── detect.py                      <- run the detector
│       ├── generate_case_files.py         <- Claude case files
│       ├── evaluate_detection.py          <- measure vs ground truth
│       ├── report.py                      <- paste-ready evaluation summary
│       ├── verify_ingest.py               <- ingest self-test, rolls back
│       ├── verify_detector_isolation.py   <- proves invariant #4 (AST walk)
│       ├── verify_human_gate.py           <- proves invariants #1/#2/#3
│       └── verify_claude_auth.py          <- Agent SDK auth check
└── frontend/
    ├── lib/
    │   ├── tokens.ts          <- design tokens, JS mirror of globals.css
    │   ├── api.ts             <- typed backend client
    │   └── smoothScroll.ts    <- Lenis + GSAP ScrollTrigger, wired as one
    ├── components/
    │   ├── landing/           <- Loader, RingGraph
    │   └── console/           <- ClusterDetail, GraphView, Scorecard,
    │                             AuditTrail, Bits
    └── app/
        ├── globals.css        <- design tokens live here
        ├── page.tsx           <- Surface A, the landing page
        └── console/page.tsx   <- Surface B, the review console
```

**Two package boundaries carry real weight:**

- `detection/` may not read ground-truth labels or import `evaluation.*`.
  `scripts/verify_detector_isolation.py` walks the AST and fails the build if it
  does.
- `app/routers/clusters.py` is the only code that may record a **decision**.
  `detection/pipeline.py` may triage between `pending` and `needs_review`, and
  nothing else may touch status at all. `scripts/verify_human_gate.py` proves it
  statically and at runtime.

---

## 4. Database schema

Six tables, four native Postgres enum types, one view, one trigger. The
migration `0001_initial_entity_graph_schema.py` is the authority; `app/models.py`
mirrors it for ORM use.

### `entities` — nodes in the graph
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `type` | enum `entity_type` | `customer` \| `device` \| `instrument` \| `address` |
| `external_ref` | text | **Addition beyond the original brief.** The natural key: device fingerprint, normalised address hash, or instrument token. Without it there is no way to know two transactions used the *same* device, which is the whole basis of the product. Unique per `(type, external_ref)`. Store hashes/tokens — never raw PAN or raw PII. |
| `first_seen_at` | timestamptz | defaults to `now()` |

### `entity_links` — undirected edges
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `entity_id_a` / `entity_id_b` | UUID FK → entities | CHECK `entity_id_a < entity_id_b` so each undirected edge is stored exactly one way |
| `link_type` | enum `link_type` | `shared_device` \| `shared_address` \| `shared_instrument` |
| `transaction_id` | UUID FK → transactions | the observation that produced this edge |
| `created_at` | timestamptz | |

One row per `(pair, link_type, transaction)` observation, so repeated
co-occurrence becomes edge weight naturally when the graph is built. Unique on
that 4-tuple, so re-ingesting a transaction is idempotent.

### `transactions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `razorpay_order_id` | varchar(64) UNIQUE | test-mode order id |
| `customer_entity_id` | UUID FK → entities | NOT NULL |
| `device_entity_id` | UUID FK → entities | nullable — not every order carries a fingerprint |
| `address_entity_id` | UUID FK → entities | nullable |
| `instrument_entity_id` | UUID FK → entities | nullable |
| `amount` | bigint | **minor units (paise)**, matching the Razorpay API. Never a float. CHECK `>= 0` |
| `currency` | char(3) | defaults `INR` |
| `created_at` | timestamptz | |
| `is_synthetic_ring_id` | text NULL | **GROUND TRUTH. Never read by the detector.** |

### `clusters`
`id` UUID PK · `status` enum `cluster_status` (`pending` \| `cleared` \|
`dismissed` \| `needs_review`, defaults `pending`) · `score` float ·
`created_at` timestamptz.

### `cluster_members`
`(cluster_id, entity_id)` composite PK. **Addition beyond the original brief** —
`clusters` on its own has no way to reference the entities it flags, so a cluster
could not actually be reviewed.

### `audit_log` — append-only
`id` bigserial PK · `actor` enum `audit_actor` (`system` \| `claude` \| `human`) ·
`action` text · `target_type` text · `target_id` text · `detail_json` jsonb ·
`created_at` timestamptz.

Append-only is enforced by the trigger `trg_audit_log_no_update_delete` (and
`trg_audit_log_no_truncate`), which calls
`ringsentinel_audit_log_append_only()` and raises. Do not remove these to make a
test pass — fix the test.

### `v_transactions_detector` — ground-truth-free view
Selects every `transactions` column **except** `is_synthetic_ring_id`.
**All Phase 3 detection code must read this view, not the base table.** This
makes invariant #4 a property of the database rather than a matter of
discipline.

### Deviations from the brief, in one place
Additions made because the schema as literally specified could not function.
All are called out above and are easy to remove if unwanted:
1. `entities.external_ref` — without it, shared-attribute detection is impossible.
2. `cluster_members` — without it, a cluster cannot name the entities it flags.
3. `transactions.currency` — Razorpay returns it; storing it avoids a silent INR assumption.
4. `clusters.evidence_json` / `.cadence` / `.detector_version` (migration 0002) —
   Phase 3 requires every score to be explainable, and `(id, status, score,
   created_at)` has nowhere to record which attributes drove the score.
5. `case_files` table (migration 0003) — case files must be cached rather than
   regenerated per page view, which needs somewhere to store them.
6. `trg_clusters_status_human_only` (migration 0003) — makes "no auto-execution"
   a property the database enforces rather than a convention code review has to
   catch.
7. `clusters.fingerprint` (migration 0004) — without a stable identity across
   runs, `detect` destroyed every pending cluster's case files and duplicated
   already-reviewed groups.
8. `evaluation_runs` table (migration 0005) — a reported metric must not change
   because a threshold was edited afterwards, so snapshots are stored.

Plus two enforcement mechanisms not requested but consistent with the brief: the
append-only trigger, and the `v_transactions_detector` view.

---

## 5. Claude Agent SDK authentication

**Status: verified working on this machine.** See §7 for how it was checked.

The Agent SDK does **not** take an API key as a parameter. It spawns a bundled
Claude Code binary as a subprocess, and that subprocess resolves credentials in
this order:

1. `ANTHROPIC_API_KEY` — pay-as-you-go API billing. **Not what this project uses.**
2. `CLAUDE_CODE_OAUTH_TOKEN` — long-lived subscription token from
   `claude setup-token`. Works headless, so this is the path for Docker.
3. `~/.claude/.credentials.json` — the interactive `claude` login. This is what
   works on the host machine today (`subscriptionType: pro`).

Because the pip wheel **bundles the Claude Code binary**, the backend image needs
no Node.js and no separate Claude Code install.

Re-check the auth path at any time with:

```bash
docker compose exec backend python -m scripts.verify_claude_auth
# or on the host:  cd backend && python -m scripts.verify_claude_auth
```

### ⚠️ Licensing constraint — know this before shipping

The Agent SDK docs state:

> *Unless previously approved, Anthropic does not allow third party developers to
> offer claude.ai login or rate limits for their products, including agents built
> on the Claude Agent SDK. Please use the API key authentication methods
> described in this document instead.*

Reading: running the SDK **locally, under your own subscription, for your own
development and demo** is ordinary Claude Code usage and is fine. **Shipping
RingSentinel as a product that serves other users on your subscription is not.**

Practical consequence for this project: subscription OAuth is the local/demo
default, and a deployed multi-user RingSentinel would need `ANTHROPIC_API_KEY`.
Write the Phase 4 LLM layer so the credential source is a config concern, not
something hardcoded — both paths must work without code changes.

---

## 5a. Phase 2 — synthetic corpus and ingest

### The one rule about how data gets in

**The generator never writes to Postgres.** It creates real Razorpay test-mode
records, and the resulting events are delivered to `POST /webhooks/razorpay`,
which is the only code path that writes `entities` / `entity_links` /
`transactions`. Seeding and production therefore exercise identical code.

### ⚠️ What Razorpay test mode can and cannot do

This constrained the design and will constrain yours:

| Thing | Possible via API? |
|---|---|
| Create an **order** | **Yes.** Every transaction in the corpus has a genuine `order_...` id, fetchable from Razorpay. |
| Create a **payment link** | **Yes.** Used where an archetype calls for it. |
| Create a **payment** | **No.** The docs are explicit: the Payments API exists *"only to retrieve payment details or change the status from authorized to captured and **not** to collect payments"*. Real payments come from Checkout in a browser, or from S2S endpoints requiring per-account enablement. |
| Create a **refund** | **No** — a refund needs a real payment to refund. |
| **Payouts** (RazorpayX) | Not attempted: separate product, separate account and credentials. |

Consequences, stated plainly so nobody later assumes otherwise:
- Orders are **real**. Payment entities attached to emitted `order.paid` events
  are **synthesized locally** and carry `"synthesized": true`. Nothing in the
  graph depends on them — ingest keys off the real order.
- Return-abuse is modelled as a shared **refund instrument** plus a
  `return_requested` flag, not as real refund objects.
- Razorpay cannot deliver webhooks to `localhost`, so `scripts/seed_rings.py`
  signs each event with `RAZORPAY_WEBHOOK_SECRET` and posts it to your own
  receiver. The signature path, verification, and ingest are all real; only the
  transport hop is local.

### The six archetypes

3 fraud patterns × 2 cadence variants, one named function each in
`generator/archetypes.py`, registered in `ARCHETYPE_GENERATORS`:

| Pattern | Pivot attribute | Signature |
|---|---|---|
| `card_testing` | 1–2 shared **instruments** | many tiny orders (₹1–₹49) probing validity |
| `promo_farming` | one shared **address** / device | many accounts, 1–3 orders each, discount codes |
| `return_abuse` | shared **instrument** (refund destination) | fewer, larger orders, very high return rate |

| Cadence | Timing | Other tells |
|---|---|---|
| `human` | heavy-tailed lognormal gaps, diurnal, floor of 4s | picks promo codes at random |
| `agent` | near-uniform ~1.6s gaps, **below human reaction time**, no diurnal shape | walks the promo list systematically, amount ladders |

Measured in Postgres after the live seed: median inter-order gap is
**120.44s for human rings vs 1.60s for agent rings**. (The per-ring *minimum*
gap can dip below the 4s floor because several accounts in one ring act in
parallel; the floor applies per account, and the median is the discriminating
signal.)

### Razorpay test-mode rate limits — measured, not documented

Razorpay does not publish a hard number for standard API limits. Observed on
this account: **429s begin around 3-4 requests/sec**. The full 1,499-order seed
at `--rate 3` took **498s (~3.0/s sustained)** and hit only **3** rate-limits,
all recovered automatically. `--rate 4` produced roughly 9% 429s. Start at 3.

Note the SDK gives no help here: it discards HTTP status codes and only retries
`ConnectionError`, so `app/razorpay_client.py` attaches a `requests` response
hook to read the real status and `Retry-After` before the SDK maps the error to
a generic `ServerError`.

### Corpus as actually seeded

| Metric | Value |
|---|---|
| Razorpay API calls | 1,502 (1,499 orders + 3 retries) |
| Transactions | 1,499 — all with a real `order_...` id |
| Entities | 635 (173 customer, 164 device, 163 instrument, 135 address) |
| Entity links | 4,089 |
| Failures | 0 |
| Ring transactions | 599 across 12 rings; 900 normal |

Separation check: ring accounts converge **3-9 per shared attribute**, while the
densest cluster in background traffic is **3 accounts** (a benign second-device
case). That gap is what makes a precision number meaningful.

### Ground truth and the held-out split

`transactions.is_synthetic_ring_id` holds a pipe-delimited label:

```
ring_09|promo_farming|agent|holdout
```

Normal background traffic has `NULL`. **Rings 1–8 are the tuning set; rings
9–12 are HELD OUT** (`generator/config.py: HOLDOUT_RING_NUMBERS`). Do not look
at or tune against 9–12 until Phase 6 evaluation.

Reproducibility: the *plan* is fully deterministic in `RANDOM_SEED`. The
Razorpay order ids are not — they are assigned per run.

### Why background traffic pools are sized the way they are

Each normal account gets its **own** device, address, and instrument. The pools
are sized to exactly `normal_customer_count` on purpose: a smaller pool would
make `index % pool_size` wrap and manufacture systematic accidental sharing,
which would look like rings and make any precision number meaningless. Benign
sharing (households, second devices) is injected explicitly and in small doses
by `generator/normal.py`.

---

## 5b. Phase 3 — detection

### How ground-truth isolation survives "run against the tuning split only"

These two requirements pull against each other: you cannot select the tuning
split without reading `is_synthetic_ring_id`, which the detector must never see.

The resolution is a package boundary:

| Package | May read labels? | Role |
|---|---|---|
| `detection/` | **No** | Builds the graph, clusters, scores. Reads `v_transactions_detector` only. |
| `evaluation/` | Yes | Selects splits, measures recall/precision against ground truth. |

`evaluation/splits.py` reads the labels, works out which transaction ids are out
of scope, and passes the detector an **opaque set of ids to exclude**. The
detector is never told what a split is.

`scripts/verify_detector_isolation.py` enforces this mechanically. It walks the
AST of every module under `detection/` — deliberately not a grep, because
`graph.py` legitimately *mentions* the column in a docstring — and fails if any
executable string literal names `is_synthetic_ring_id` or queries the base
`transactions` table, or if any module imports `evaluation.*`.

### The four signals

Tunables all live in `detection/config.py`. Nothing numeric is buried in the
scoring code.

| Signal | Weight | What it measures |
|---|---|---|
| Attribute reuse | 0.45 | How many distinct accounts funnel through one device / instrument / address, weighted by type |
| Timing regularity | 0.25 | How metronomic and how fast, versus the population baseline |
| Concentration | 0.15 | Share of the cluster's volume flowing through the shared attributes |
| Account shallowness | 0.15 | Fraction of accounts with almost no transaction history |

**Attribute type weights are the point**: instrument 1.00, device 0.85, address
**0.40**. A shared delivery address is a household far more often than a crew, so
address overlap alone cannot flag a cluster.

Reuse saturates as `f(k) = (k-1)/(k-1+2)`, so the jump from 2 to 4 accounts on
one card counts for far more than 20 to 22. Per-attribute contributions combine
with a probabilistic soft-OR, so independent evidence stacks without exceeding 1.

### Three findings from calibration, each of which was a bug first

1. **The hub filter was deleting a real ring.** Dropping attributes touched by
   >5% of accounts meant a limit of 8 on a 173-account graph — and ring_04 is a
   genuine 9-account ring. Fixed with `HUB_ATTRIBUTE_MIN_CUSTOMERS = 25`, an
   absolute floor well clear of plausible ring sizes; the percentage only takes
   over on a large graph.

2. **Velocity swamped regularity.** The baseline median gap is ~32 hours (normal
   shoppers buy every few days), so *any* burst saturated the velocity signal at
   1.0 and timing stopped discriminating — human-cadence clusters were scoring
   1.00 on it. Regularity now carries 0.80 of the timing signal: measured on this
   corpus, agent rings sit at CV 0.04, human rings 0.96, baseline 0.76.

3. **A pair is not a ring.** With the shared-attribute floor at 2 accounts, the
   soft-OR let several unrelated *pairs* accumulate to reuse 0.85. Floor raised
   to 3. Pairs still appear in the evidence, they just do not drive the score.

### Why account shallowness exists

After the first three fixes, the weakest genuine ring (ring_08, promo farming on
a shared address, 0.270) and the strongest benign cluster (a household trio on
one device, 0.250) sat **0.02 apart**. No threshold survives a gap that narrow —
it would be fitting noise, not signal.

Shallowness separates them structurally instead. Promo-farming sock puppets exist
to place one discounted order, so they have 1–3 transactions each; people who
genuinely share a device have real histories. That is a standard promo-abuse
signal, not a corpus artefact. It is weak on its own by design — at 0.15 it can
tip an already-suspicious cluster over the line but can never flag one alone.

Margin after adding it: weakest true ring **0.371**, strongest benign cluster
below 0.25.

### The threshold was measured, not guessed

`SCORE_THRESHOLD = 0.30`, chosen from the sweep on the tuning split:

| Threshold | Rings found | False flags |
|---|---|---|
| 0.20 | 8/8 | 1 |
| **0.25 – 0.35** | **8/8** | **0** |
| 0.40+ | 6/8 | 0 |

0.30 is the centre of the stable plateau, so it has the most room on both sides
before behaviour changes — which is what should survive the held-out rings.

### Results on the tuning split (rings 1–8)

| Metric | Result |
|---|---|
| Rings detected | **8/8 (100%)** |
| Cadence classified correctly | **8/8** |
| False flags | **0 (100% precision)** |
| Normal accounts swept in | **0 of 105 (0.0%)** |
| Runtime | 0.04s, deterministic across runs |

Rings 9-12 were untouched at this point. They were opened once, later, under
§5b-eval - and the detector scored 4/4 on them with zero false flags.

### Persistence

Clusters are written with `status = 'pending'` — nothing here ever sets a
terminal status or restricts an account (invariants #1, #2). Re-running replaces
only *pending* clusters and preserves anything a human has already actioned;
verified by clearing a cluster, re-running, and confirming 7 replaced / 1
preserved.

Migration `0002` adds three columns to `clusters`, because `(id, status, score,
created_at)` had nowhere to record *why* a cluster was flagged:

- `evidence_json` — per-signal values, weights, weighted contributions, and the
  specific shared-attribute entity ids and external refs that drove them
- `cadence` — enum `human_like | agent_like | inconclusive`
- `detector_version` — so results stay traceable across threshold changes

---

## 5b-eval. Held-out evaluation — RUN ONCE, 2026-08-28

Rings 9-12 were sealed from the moment the corpus was generated and were never
looked at during Phase 3 tuning. This is the one unbiased estimate of whether
the detector generalises or was fitted to the tuning split.

Run with the **exact config committed in Phase 3** — `detection/` was verified
byte-identical to commit `0762abe` before the run, detector `0.4.0`, threshold
`0.30`. Nothing was changed afterwards.

### Result

| Metric | Held-out (rings 9-12) | Tuning (rings 1-8) |
|---|---|---|
| Rings detected | **4/4 (100%)** | 8/8 (100%) |
| Cadence correct | **4/4** | 8/8 |
| False flags | **0 (100% precision)** | 0 (100%) |
| Normal accounts swept in | **0 of 105** | 0 of 105 |

Every ring was recovered **completely** — 6/6, 8/8, 4/4, 5/5 accounts, not merely
the 50% the matching rule requires.

| Ring | Pattern | Cadence | Accounts | Score |
|---|---|---|---|---|
| ring_09 | card_testing | human | 6/6 | 0.578 |
| ring_10 | promo_farming | agent | 8/8 | 0.846 |
| ring_11 | return_abuse | human | 4/4 | 0.427 |
| ring_12 | return_abuse | agent | 5/5 | 0.707 |

### Did the threshold generalise?

Post-hoc diagnostic only — **the config was not changed based on it.**

| Threshold | Tuning plateau | Held-out plateau |
|---|---|---|
| 0.20 | 8/8, 1 false flag | 4/4, 1 false flag |
| **0.25 – 0.35** | **8/8, 0 false** | **4/4, 0 false** |
| 0.40 | 6/8, 0 false | 4/4, 0 false |

The stable band on held-out data is *wider* than on tuning data, and 0.30 sits
inside both. The weakest held-out ring scored 0.427 against a 0.30 threshold — a
0.127 margin, healthier than the weakest tuning ring at 0.371.

### Full corpus, all 12 rings

**12/12 detected, 12/12 cadence correct, 0 false flags, every cluster 100% pure.**

### ⚠️ What this number does and does not mean

This is a **synthetic corpus that this project generated**, and it is separable
by construction: ring identities are salted per ring, so no two seeded rings
share an entity, and background accounts each get their own device, address, and
instrument. Real merchant data is far messier — real rings bridge into one
another, benign sharing is dense and irregular, and attribute hygiene is poor.

So 100% here means **the detector does what it was designed to do on data of this
shape, and did not overfit the tuning split**. It is not a claim about production
accuracy. Anyone presenting this number should say so.

---

## 5c. Phase 4 — case files and the human gate

### How the Agent SDK is authenticated (verified 2026-08-28)

| Where | Credential | Billing |
|---|---|---|
| Host | `~/.claude/.credentials.json`, `subscriptionType: pro` | **Subscription** |
| Container | same file, bind-mounted to `/root/.claude` | **Subscription** |

`ANTHROPIC_API_KEY` is **not set anywhere** — not in `.env`, not in the shell,
not in the container — and `docker-compose.yml` does not pass it through at all,
so it cannot be picked up accidentally. There is no path by which this phase
bills against pay-as-you-go API credit.

The container originally had *no* credentials and every SDK call failed. Fixed
with a bind mount driven by `CLAUDE_CONFIG_HOST_DIR` in `.env`. The cleaner
long-term option is `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`, which is
headless and needs no mount; both work, and nothing in the code hardcodes a
credential source.

```bash
docker compose exec backend python -m scripts.verify_claude_auth
```

### Claude explains, humans decide — enforced three ways

A prompt is not an access control, so the boundary is enforced at three
independent layers. Layer 1 can be argued with; layers 2 and 3 cannot.

| # | Layer | Mechanism |
|---|---|---|
| 1 | Prompt | `app/prompts.py` states the explain-only role |
| 2 | SDK | `allowed_tools=[]`, no MCP servers — **no function exists for Claude to call** |
| 3 | Database | trigger `trg_clusters_status_human_only` rejects any `clusters.status` change outside a human review transaction |

**Claude does not see ground truth either.** `case_files.py` assembles its
context from `v_transactions_detector`, the same label-free view the detector
uses. If Claude could read `is_synthetic_ring_id` the case files would be
trivially correct and the demo worthless — invariant #4 covers the LLM layer.

### The human gate

`app/routers/clusters.py` is the only module in the project that writes
`clusters.status`, and the only one that sets `ringsentinel.human_review`, the
transaction-local flag the trigger demands. Everything else — the detector, the
case-file writer, a script, a psql prompt — gets an exception:

```
ERROR: clusters.status may only be changed by a human review action
       (RingSentinel invariants #1 and #2). Attempted pending -> cleared
       without ringsentinel.human_review set.
```

`scripts/verify_human_gate.py` proves all of this mechanically: who writes
status, who sets the guard, that no block/freeze/decline call exists anywhere,
and at runtime that the database refuses an unguarded update.

### ⚠️ A naming decision worth confirming

The Phase 1 enum offers `cleared` / `dismissed` / `needs_review`. The two
endpoints map as:

- **approve** → `cleared` — "cleared out of the review queue as a confirmed
  case", *not* "the accounts are cleared of suspicion"
- **dismiss** → `dismissed` — false positive

With only these statuses and two endpoints this is the only mapping that leaves
every status reachable, but `cleared` reads ambiguously. Worth renaming if the
review UI in Phase 5 makes it confusing.

**Approving does not block anyone.** It records a human's judgement and moves the
cluster out of the pending queue. No customer-facing action exists in this
codebase.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/clusters` | queue, filter by `status` / `min_score` |
| GET | `/clusters/{id}` | case file + evidence + graph + full audit trail. **Never generates** — that would mean an LLM call per page view |
| POST | `/clusters/{id}/case-file` | generate or reuse; `?force=true` to regenerate |
| POST | `/clusters/{id}/approve` | human confirms — `reason` required (min 5 chars) |
| POST | `/clusters/{id}/dismiss` | human rejects — `reason` required |

Deciding an already-decided cluster returns **409**: a decision is recorded once,
and re-deciding would overwrite an audit fact.

### Caching

A case file is reused when its `prompt_version` **and** the cluster's score both
match. Retuning the detector changes the score, which correctly invalidates an
explanation of the old number. Measured: 19.6s to generate, **0.109s** cached.

### Audit trail

Four event types, every one carrying its actor:

| Action | Actor | Written by |
|---|---|---|
| `cluster_flagged` | `system` | detector, per cluster |
| `case_file_generated` | `claude` | case-file writer |
| `cluster_approved` | `human` | approve endpoint |
| `cluster_dismissed` | `human` | dismiss endpoint |

Audit action names are spelled out in `ACTION_TO_AUDIT_NAME` rather than built
from the verb — `f"cluster_{action}d"` produced `cluster_dismissd`, and an audit
trail with a typo in the action name is one nobody can reliably query.

Because `audit_log` is append-only, deleting and re-running the detector
destroys the derived clusters but **not** the record of what was decided about
them. That is the point of the table.

---

## 5d. Phase 5 — the frontend

Two surfaces, deliberately built to different standards. They share tokens so
they read as one product, and share almost nothing else.

### Shared tokens

`app/globals.css` holds the CSS custom properties; `lib/tokens.ts` mirrors the
numeric half for GSAP, which needs real values rather than `var()` strings.

| Token | Value |
|---|---|
| Accent | **`#2dd4bf`** — one accent, no second one |
| Ink | `#08090a`, warmed slightly off pure black |
| Easing | `power3.inOut` (CSS mirror: `cubic-bezier(.65,0,.35,1)`) |
| Durations | `fast 0.25s` for UI, `slow 1.0s` for section transitions. Two speeds, not a spectrum |
| Display face | Space Grotesk |
| Body face | Inter |
| Type scale | 1.25 ratio, `--step--1` … `--step-7` |

Both faces are self-hosted through `next/font` — 20 woff2 files emitted, no
runtime request to Google, no swap-in shift.

### Surface A — `/`

Lenis and GSAP wired as **one** scroll system, which is the part that usually
goes wrong:

```ts
gsap.registerPlugin(ScrollTrigger);
lenis.on("scroll", ScrollTrigger.update);      // ST recalculates when Lenis moves
gsap.ticker.add((t) => lenis.raf(t * 1000));   // one RAF loop; GSAP gives seconds
gsap.ticker.lagSmoothing(0);                   // don't rewrite elapsed time
```

Without those, Lenis interpolates on its own loop while ScrollTrigger samples
`window.scrollY` on GSAP's — two clocks, and pinned sections lag or overshoot.

Four beats: the problem → the mechanism → the gate → the way in. Only the first
two are pinned and scrubbed, because that is where the argument is.

The animation is **one set of eighteen dots throughout**. Scattered, they are
eighteen individually-unremarkable transactions — exactly what a per-transaction
model sees. On scroll, seven migrate into a ring around two shared attributes and
the edges draw in. Nothing is added; the data was always that shape. That *is*
the product thesis, so it seemed worth making the animation say it literally.

Responsive behaviour uses `gsap.matchMedia()`, not a width check at mount, so
toggling device emulation in devtools tears the pinned timeline down and
re-runs the static path **without a reload**. Under `prefers-reduced-motion` or
below 768px, the resolved state renders directly — no pinning, no scrub.

Loader: a 0–100 counter held to ~1.9s, under the 2.5s ceiling, skipped entirely
under reduced motion.

### Surface B — `/console`

No loader, no pinning, no scroll-driven anything. A reviewer opens this many
times a day and wants the queue immediately. GSAP appears only for list
entrances and panel swaps.

- Dense sortable table: score bar, account count, cadence pill, status pill, evidence headline
- Detail pane: case file, per-signal score breakdown, entity graph, audit trail
- Approve / Dismiss, both refusing to submit without a reason
- Live scorecard

The graph is a **hand-rolled force layout** — repulsion, edge springs, weak
centring — run to convergence once on mount rather than on a RAF loop. A console
tab left open should not hold a CPU core, and a settled diagram is easier to
point at during a review. No dependency, no WebGL.

### The scorecard's two halves

`GET /eval/scorecard` returns `detector_benchmark` and `review_operations`
separately, and the UI keeps them visually apart. The benchmark half needs
ground-truth labels and therefore **only exists on the synthetic corpus**;
presenting it beside the operational numbers without that distinction would let
a demo figure pass for a production one.

### Performance rule, enforced everywhere

Only `transform`, `opacity`, and `stroke-dashoffset` are animated. Never `top`,
`left`, `width`, or `height`. This matters most on the console, which re-renders
on every decision — animating geometry there would cost a reflow each time.

### Cluster identity (migration 0004)

Fixing this was a prerequisite, not a nicety. `_persist` used to delete every
pending cluster and insert fresh rows, so **case files cascade-deleted with
them** — a routine `detect` run silently threw away minutes of Claude output,
and any group a human had already approved came back as a new pending duplicate.

Clusters now carry a `fingerprint`: a hash of their customer accounts.
Attribute nodes are excluded deliberately — a reviewer decides about accounts,
and including whichever device the crew happened to use would break the match
every time the cluster picked up one more shared attribute. A re-run updates the
matching row in place and leaves status, case files, and audit history intact.

**One limit worth knowing:** a cluster that is no longer flagged at all is still
retired, and its case files cascade with it. That is correct for production — a
group that stopped looking suspicious should leave the queue — but it bites when
*switching evaluation splits*, because clusters outside the new scope simply
vanish from the detector's view. The detector cannot tell "no longer suspicious"
from "out of scope", and it must not be told, since scope is deliberately opaque
to it (invariant #4). Practical consequence: pick a scope for the demo
(`--split all` shows all twelve rings) and stay on it, rather than switching back
and forth and paying for case-file regeneration each time.

---

## 5e. Phase 6 — honest scoring

### ⚠️ The held-out set had already been opened

The Phase 6 brief asked to run the held-out split "for the first time". It had
already been run, at the user's instruction, at commit `8ee5955`. This run is a
**reproduction**, and it reproduced exactly: 4/4 rings, 0 false flags, identical
scores.

What makes the numbers still trustworthy is that nothing was tuned in between.
`detection/config.py`, `scoring.py`, `baseline.py`, `cadence.py`, `clustering.py`
and `graph.py` were verified **byte-identical to commit `0762abe`** before the
re-run. Only `pipeline.py` changed, and only in how clusters are persisted.

### Held-out result

| Metric | Value | Unit |
|---|---|---|
| Precision | **100%** | clusters — 4 of 4 flagged were real |
| Recall | **100%** | rings — 4 of 4 seeded rings found |
| False-positive cost | **₹0** | 0 false positives |
| Exceptions | **1** | scored inside the ambiguous band |
| Cadence correct | 4/4 | |
| Clean accounts swept in | 0 of 105 | |

**Precision and recall are counted in different units on purpose.** Precision is
per *cluster*, because analyst time is spent per cluster. Recall is per *ring*,
because the question is how many real rings exist that we found. A single
blended F1 would be tidier and would mean less.

### The ambiguous band

`CONFIDENT_SCORE_THRESHOLD = 0.45`. Clusters scoring in **[0.30, 0.45)** are
flagged but land in `needs_review` rather than `pending`, and are reported as
exceptions rather than findings.

Justified from the **tuning** sweep, run long before the held-out set was
opened: at 0.35 recall was 8/8, at 0.40 it was 6/8. Two tuning rings sit below
0.40, so whether they are found depends on where the threshold is placed rather
than on the strength of the evidence. That is the working definition of
ambiguous. 0.45 sits just clear of that transition.

**This does not change what gets flagged.** `SCORE_THRESHOLD` is untouched at
0.30, so precision and recall are exactly what they were. The band only splits
already-flagged clusters into confident and ambiguous.

### `needs_review` versus invariant #2

The brief asked the detector to assign `needs_review`, which the Phase 4 trigger
forbade. The resolution is that `needs_review` is **triage, not a decision**:

| Status | Meaning | Who may set it |
|---|---|---|
| `pending` | flagged, detector confident | detector |
| `needs_review` | flagged, detector unsure | detector |
| `cleared` / `dismissed` | **a decision** | humans only, once, forever |

Migration `0005` rewrites the guard accordingly, and it is strictly **stronger**
than before: it still refuses any automated move into a terminal state, and it
now also refuses to move a cluster *out* of one — a recorded decision cannot be
revised even inside a human review transaction, because the audit log would then
disagree with the row. `scripts/verify_human_gate.py` check 4b proves it.

### False-positive cost model — all estimates

In `evaluation/cost.py`, decomposed into two parts that are never merged:

| Part | Certain? | Value |
|---|---|---|
| Review cost | **Yes** | ₹240 per false positive (12 min × ₹1,200/hr) |
| Trust cost | **Contingent** | ₹3,500 per wrongly-gated account |

The trust cost is contingent for a specific reason: **RingSentinel never gates
an account**. It can only be incurred if a human approves a false flag *and* a
downstream process then acts. Modelling it anyway is the honest choice — "our
tool cannot cause harm" is not the same as "flagging carries no risk" — but
merging it into the certain cost would inflate the headline figure.

Every input is an estimate, exposed through `/metrics` and the report so a reader
can disagree with each one individually.

### Where the detector is weakest

Derived from the numbers by `scripts/report.py`, not written by hand:

- **Human-cadence rings score materially lower than agent-cadence ones** (0.503
  vs 0.776 on held-out). The timing signal contributes almost nothing when a ring
  is operated by people, so those rings rest on attribute reuse alone and sit
  closer to the threshold.
- **Address-only rings are the hardest class.** Address is weighted 0.40
  precisely because households share addresses; that is deliberate, and it means
  such rings are the hardest to justify flagging.

### Commands

```bash
docker compose exec backend python -m scripts.report                   # print
docker compose exec backend python -m scripts.report --store           # and record
curl localhost:8000/metrics                    # stored snapshot
curl 'localhost:8000/metrics?recompute=true'   # fresh, unstored
```

Snapshots are stored in `evaluation_runs` so a reported number cannot silently
change because someone edited a threshold afterwards.

---

## 5f. Measured facts for later phases

Two things were researched and measured rather than assumed, so later phases can
cite them without re-deriving. Both are recorded with their limits.

### Case-file cost — measured, not estimated

The Agent SDK reports `total_cost_usd` and full token usage on every call.
Migration 0006 stores them on `case_files`, so cost per cluster is an
observation multiplied by a volume assumption, rather than two assumptions
multiplied together.

| Condition | Cost | Input tokens | Output |
|---|---|---|---|
| Cold prompt cache | **$0.1468** | 12,785 written | 691 |
| Warm prompt cache | **$0.0282** | 12,785 read | 806 |

Same model (`claude-opus-5`), same prompt. The 5.2x gap is entirely prompt
caching: a cold call pays to *write* the cache, a warm one pays to *read* it.

Two consequences worth knowing before quoting a number:
- **Quote a range, not a point.** Batch generation runs warm and lands near
  $0.03; a single cluster reviewed hours later runs cold at ~$0.15.
- **Cost scales with flagged clusters, not transactions.** The corpus is 1,499
  transactions and 12 clusters. Case files are generated per *cluster*, so the
  LLM bill is roughly three orders of magnitude smaller than a
  per-transaction design would be. That is a property of the graph approach,
  not an optimisation.

Token counts are informational only. Fresh input, cache writes, and cache reads
are billed at different rates, so `cost_usd` is the number to trust —
`app/case_files.py` says so at the point of capture.

`Settings.claude_case_file_model` makes the model an explicit choice. Left
unset, the SDK picks; set it to pin one. Every generation records which model
ran, so a change is visible in the data.

### RBI draft Model Risk Management guidance — verified 2026-08-29

Verified against reporting on the RBI draft, *Guidance on Regulatory Principles
for Model Risk Management, 2026*. Public comments closed **24 July 2026**. It is
a **draft** and **non-binding**.

What it asks for, and where RingSentinel already stands:

| Draft asks for | RingSentinel |
|---|---|
| Kill-switch: every AI system can be overridden, suspended, deactivated | Nothing to switch off — no code path can act on an account at all |
| Human oversight of automated decisions | A Postgres trigger refuses any decision outside a human review action |
| Reviewers able to genuinely challenge, not rubber-stamp | Written reason mandatory; full per-signal evidence shown; decision immutable once recorded |
| Concern about automation bias and decision fatigue | Claude's recommendation is advisory and labelled as such; the ambiguous band says "unsure" instead of forcing a binary |
| Black-box models need disclosed reasoning or stricter controls | Every score decomposes into named signals with the entities that drove them |

### ⚠️ Scope — do not overstate this

The stated scope is commercial banks, small finance banks, **payments banks**,
local area banks, co-operative banks, regional rural banks, NBFCs, all-India
financial institutions, asset reconstruction companies, and credit information
companies.

**Payment aggregators are not in that list.** Razorpay is a payment aggregator,
not a payments bank. Do not claim Razorpay is bound by this draft, and do not
call it a regulation — it is a draft out for comment.

The honest and still-strong claim: this is the direction Indian financial AI
regulation is moving, many of Razorpay's own merchants (banks and NBFCs) would
be directly on the hook, and RingSentinel already meets the bar the draft
describes.

---

## 5g. Demo reset

`scripts/demo_reset.py` puts the console into a curated three-cluster state for
recording, and is re-runnable between takes. **~18s warm, ~30s on the first cold
run** (the difference is entirely the prompt cache).

Two departures from how the brief described it, both deliberate:

**It does not wipe `audit_log`.** That table is append-only by trigger, and the
trigger is one of the things the demo exists to show — dropping it for
convenience would disarm the strongest claim in the project. It is also
unnecessary: the console renders a cluster's trail by `target_id`, and the reset
deletes and recreates clusters, so each gets a fresh id and a visibly clean
history. Old rows point at dead cluster ids and never render.

**It curates by scope, not by fabrication.** It hands the detector an opaque
exclusion set — the same mechanism the evaluation splits use — so only three
seeded rings are in view while all 900 background transactions stay. Every
cluster on screen is a real detection over real Razorpay test-mode data.

### ⚠️ There is no true false positive to demo

The brief asked for a "clean false-positive-shaped case". **One does not exist**
— the detector has never produced a false positive on this corpus, so the third
cluster is a genuine ring that merely *looks* innocent (address-only sharing,
human cadence, score 0.386).

The script prints ground truth for each cluster before you record, plus the
honest narration: if you dismiss it on camera, say that the detector flagged it,
said it was unsure, Claude leaned false-positive, and a human still got it wrong
— which is precisely why the audit log records who decided and why. That lands
better than implying a false positive the system never made.

### A bug this phase found

`needs_review` clusters could not be approved or dismissed — `_record_review`
only accepted `pending`, so the Phase 6 triage band stranded exactly the
clusters that most needed human judgement. Fixed: both pre-decision states are
decidable, and only an already-recorded decision blocks a second one.

---

## 6. Commands

```bash
cp .env.example .env          # once
docker compose up             # Postgres + migrated backend + frontend

# Phase 1 - schema verification (seeds no data)
docker compose exec backend python -m scripts.seed

# Phase 2 - the full synthetic corpus, via real Razorpay test-mode orders
docker compose exec backend python -m scripts.seed_rings --dry-run   # plan only
docker compose exec backend python -m scripts.seed_rings --limit 20  # smoke test
docker compose exec backend python -m scripts.seed_rings --reset     # full corpus

# Ingest pipeline self-test (rolls back; safe against a populated database)
docker compose exec backend python -m scripts.verify_ingest

# Phase 3 - detection
docker compose exec backend python -m scripts.detect                      # tuning split
docker compose exec backend python -m scripts.detect --no-persist         # dry run
docker compose exec backend python -m scripts.detect --explain 1          # full evidence
docker compose exec backend python -m scripts.detect --show-below         # near misses

# Measure against ground truth (evaluation only - reads labels)
docker compose exec backend python -m scripts.evaluate_detection --sweep

# Prove the detector cannot see ground truth (invariant #4)
docker compose exec backend python -m scripts.verify_detector_isolation

# Demo reset - curated 3-cluster state for recording (~18s warm)
docker compose exec backend python -m scripts.demo_reset

# Phase 4 - case files and review
docker compose exec backend python -m scripts.verify_claude_auth
docker compose exec backend python -m scripts.generate_case_files --limit 3
docker compose exec backend python -m scripts.verify_human_gate

curl localhost:8000/clusters
curl -X POST localhost:8000/clusters/<id>/case-file
curl -X POST localhost:8000/clusters/<id>/approve      -H 'Content-Type: application/json'      -d '{"reason":"why you decided this","reviewer":"your name"}'
```

- Frontend → http://localhost:3000
- API docs → http://localhost:8000/docs
- Schema health → http://localhost:8000/health/db

Migrations run automatically from `entrypoint.sh` on every backend start, so a
bare `docker compose up` always yields a migrated database.

```bash
# New migration after editing app/models.py:
docker compose exec backend alembic revision --autogenerate -m "description"
docker compose exec backend alembic upgrade head
```

---

## 7. Phases

| Phase | Scope | Status |
|---|---|---|
| **1** | Monorepo scaffold, Docker Compose, entity-graph schema + migration, env template, README | **Done** |
| **2** | Razorpay test-mode ingest + synthetic ring generator: 6 archetypes, 12 rings, webhook ingestion path | **Done** |
| **3** | NetworkX detection: graph build, clustering, 4-signal scoring, cadence classification. 8/8 tuning rings, 0 false flags. | **Done** |
| **4** | Claude Agent SDK case files + human-gated approve/dismiss API, with a DB trigger enforcing the gate. | **Done** |
| **eval** | Held-out evaluation on rings 9-12, run once with the Phase 3 config: 4/4 rings, 0 false flags | **Done** |
| **5** | Frontend: landing page (Lenis + GSAP scroll sequence) and review console (queue, case files, graph, scorecard, audit) | **Done** |
| **6** | Honest scoring: held-out precision/recall, FP cost model, ambiguous band as `needs_review`, `/metrics`, `scripts/report.py` | **Done** |

**Phase 1 constraints that were deliberately honoured:** no fake/mock data, no
UI beyond a placeholder page, no detection logic. Do not "helpfully" add these
early — later phases depend on doing them properly.

---

## 8. Conventions

- **Money is integer paise.** Never float, never rupees, at any layer.
- **PII**: store hashes and opaque tokens in `entities.external_ref`. Never raw
  card numbers, never raw addresses.
- **Audit everything** that changes a cluster's state, with the correct `actor`.
- **Idempotent ingest**: re-ingesting a Razorpay order must not duplicate edges
  (the unique constraint on `entity_links` enforces this).
- **Secrets** live in `.env` only, which is gitignored. `.env.example` documents
  every variable and where to obtain it.
