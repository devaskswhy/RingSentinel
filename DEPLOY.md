# Deploying RingSentinel

Two surfaces, deployed differently on purpose.

| | Where | Why |
|---|---|---|
| Frontend | Vercel (free) | Static Next.js. No cold start, so a judge clicking a link waits for nothing. |
| Backend + Postgres | Render (free) | Needs a database and a long-running process. |

The landing page is deliberately **not dependent on the backend** — it renders
the real corpus figures, all twelve cluster scores and the real-data section
from measured fallbacks. Verified by stopping the backend and reloading: every
figure still renders. So even if the API is asleep or the free tier has
expired, the first thing anyone sees is intact.

---

## ⚠️ The deployed instance must not call Claude

This is a licensing boundary, not a preference. The Agent SDK's terms:

> *Unless previously approved, Anthropic does not allow third party developers
> to offer claude.ai login or rate limits for their products, including agents
> built on the Claude Agent SDK.*

Running the SDK locally under your own subscription is ordinary Claude Code
usage. A hosted RingSentinel generating case files for judges on that same
subscription is not. So the deployment sets:

```
CLAUDE_GENERATION_ENABLED=false
```

and **does not carry a Claude credential at all**. The 15 case files in the
seed are real, unedited Claude output written locally, and they are served in
full. Only new generation is refused, with an HTTP 503 that explains why rather
than failing silently.

The alternative is `ANTHROPIC_API_KEY`, which is permitted and costs money.
Both paths work without code changes; the credential source was always a config
concern.

---

## 1. Database

Create a free Postgres on Render. Then, from this repo:

```bash
# migrations first — the schema, triggers and the label-free view
docker compose exec backend alembic upgrade head          # locally, to check
psql "$RENDER_DATABASE_URL" -f backend/deploy/seed-dump.sql
```

`backend/deploy/seed-dump.sql` is the seeded corpus: 1,499 transactions from
real Razorpay test-mode orders, 635 entities, 12 clusters and their case files.
It contains no secrets — every entity reference is a salted hash and no raw PAN
or address exists anywhere in the schema by construction.

The backend runs `alembic upgrade head` on start (`entrypoint.sh`), so the
schema is created before the seed is loaded.

## 2. Backend

Render web service, from `backend/`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Render Postgres internal URL |
| `CLAUDE_GENERATION_ENABLED` | `false` |
| `APP_ENV` | `production` |
| `RAZORPAY_KEY_ID` / `_SECRET` | **omit** — nothing on the deployed path creates orders |

Do not set `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`. The absence is the
guarantee.

## 3. Frontend

Vercel, root `frontend/`:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | the Render backend URL |

## 4. After deploying, check these

```bash
curl $BACKEND/health/db                       # tables present
curl $BACKEND/clusters | head -c 200          # 12 clusters
curl -X POST $BACKEND/clusters/<id>/case-file # expect 503 with the reason
```

Load the landing page first — it should be instant. Then the console; on the
free tier the first request may take up to a minute while the service wakes.

---

## What is deliberately not deployed

**The Razorpay seeding path.** `scripts/seed_rings.py` creates real test-mode
orders and is a local tool. The deployed instance reads a corpus that was
already created that way.

**Case-file generation, the live cadence simulation, and the adversarial case
designer.** All three call out — to Razorpay or to Claude — and all three are
local. The evidence they produced is committed; the buttons are not live.

**The IEEE-CIS evaluation.** It needs a 683 MB dataset that is licensed on
download and not redistributed here. `scripts/evaluate_ieee.py` runs locally
against `backend/data/ieee/`.
