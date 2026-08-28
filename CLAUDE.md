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
| 2 | Every flag is human-reviewed | `clusters.status` starts at `pending` and only a human action moves it to `cleared` / `dismissed` / `needs_review`. |
| 3 | Every decision is logged and never rewritten | `audit_log` is append-only, enforced by a Postgres trigger that raises on UPDATE / DELETE / TRUNCATE. |
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
│   ├── Dockerfile
│   ├── entrypoint.sh      <- runs `alembic upgrade head`, then uvicorn
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py         <- reads DATABASE_URL from the environment
│   │   └── versions/0001_initial_entity_graph_schema.py
│   ├── app/
│   │   ├── config.py          <- pydantic-settings
│   │   ├── db.py              <- engine + session
│   │   ├── models.py          <- the entity-graph schema
│   │   ├── main.py            <- health + /eval/corpus, mounts the webhook router
│   │   ├── razorpay_client.py <- test-mode-only client: pacing, 429 retry
│   │   ├── ingest.py          <- event -> entities/entity_links/transactions
│   │   └── webhooks.py        <- POST /webhooks/razorpay, HMAC verification
│   ├── generator/             <- Phase 2 synthetic corpus (pure, no network)
│   │   ├── config.py          <- seed, ring specs, held-out split, volumes
│   │   ├── identities.py      <- opaque token pools (no PII is ever created)
│   │   ├── cadence.py         <- human vs agent timing models
│   │   ├── archetypes.py      <- the six named archetype generators
│   │   ├── normal.py          <- uncorrelated background traffic
│   │   ├── planned.py         <- PlannedTransaction + Razorpay notes mapping
│   │   └── plan.py            <- assembles the whole corpus
│   └── scripts/
│       ├── seed.py                 <- Phase 1 schema verification
│       ├── seed_rings.py           <- Phase 2 end-to-end seed (the one command)
│       ├── verify_ingest.py        <- ingest self-test, rolls back
│       └── verify_claude_auth.py   <- Agent SDK auth check
└── frontend/
    ├── Dockerfile
    └── app/               <- App Router; placeholder page only in Phase 1
```

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
Three additions were made because the schema as literally specified could not
function. All three are called out above and are easy to remove if unwanted:
1. `entities.external_ref` — without it, shared-attribute detection is impossible.
2. `cluster_members` — without it, a cluster cannot name the entities it flags.
3. `transactions.currency` — Razorpay returns it; storing it avoids a silent INR assumption.

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

Measured on the current seed: median inter-order gap is **120s for human rings
vs 1.6s for agent rings**.

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
| **3** | NetworkX detection: build graph from `entity_links`, find dense components, score, write `clusters` + `cluster_members`. **Reads `v_transactions_detector`, never the base table.** | Not started |
| **4** | Claude Agent SDK case files for each cluster. Auth path already verified. | Not started |
| **5** | Review UI: cluster queue, case file display, approve/dismiss, audit trail view | Not started |

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
