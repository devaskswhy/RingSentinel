# Deploying RingSentinel

Two surfaces, deployed differently on purpose.

| | Where | Why |
|---|---|---|
| Frontend | Vercel (free) | Static Next.js. No cold start, so a judge clicking a link waits for nothing. |
| Backend | Render (free) | Needs a long-running process and a container runtime. |
| Postgres | **Neon** (free) | Render's free Postgres **expires after 30 days**. Neon's free tier is permanent, and a submission a judge opens six weeks later must still work. |

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

## 1. Database — Neon, not Render

Render's free Postgres is deleted after 30 days. That is fine for a sprint and
wrong for a submission someone may open weeks after it was made, so the
database lives on Neon instead: the free tier is permanent, 0.5 GB per project
against a 1.3 MB seed, and no card is required.

Neon scales compute to zero after five minutes idle and wakes on the next
connection. `pool_pre_ping` is already on in `app/db.py`, so a connection that
went away while idle is replaced rather than raising — the same mechanism
`scripts/verify_resilience.py` proves against a killed backend.

Create a project, copy the connection string, and load the seed:

```bash
# migrations first — the schema, triggers and the label-free view
docker compose exec backend alembic upgrade head          # locally, to check
psql "$NEON_DATABASE_URL" -f backend/deploy/seed-dump.sql
```

Paste Neon's URL exactly as given. It arrives as `postgresql://…?sslmode=require`,
which SQLAlchemy would read as psycopg2 — a driver this project does not install.
`app/config.py` rewrites the scheme to `postgresql+psycopg://` and leaves the
query string alone, verified against Neon's direct, pooled and `postgres://`
forms. There is nothing to edit by hand.

`backend/deploy/seed-dump.sql` is the seeded corpus: 1,499 transactions from
real Razorpay test-mode orders, 635 entities, 12 clusters and their case files.
It contains no secrets — every entity reference is a salted hash and no raw PAN
or address exists anywhere in the schema by construction.

The backend runs `alembic upgrade head` on start (`entrypoint.sh`), so the
schema is created before the seed is loaded.

### Set search_path on the role, once

After creating the database, run this once:

```sql
ALTER ROLE neondb_owner SET search_path = public;
```

`pg_dump` emits `set_config('search_path', '', false)` — session-wide, not
transaction-local — so a pooled session handed back after a restore resolves no
unqualified table name. Every data endpoint then returns 500 while `/health/db`
keeps working, because it queries `information_schema` explicitly, and the next
deploy dies in Alembic with *"no schema has been selected to create in"* while
trying to create a table that already exists.

The application and Alembic both issue `SET search_path TO public` on connect,
so they are covered either way. Setting it on the role covers everything else —
psql, a future restore, anything added later. It must be a statement, never a
connection option: Neon's pooler rejects `options=-c search_path` at startup.

## 2. Backend

Render web service, from `backend/`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string, pasted as-is |
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
