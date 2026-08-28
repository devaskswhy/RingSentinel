# RingSentinel

Fraud-ring detection for the Razorpay buildathon (AI Risk Manager track).

> **Working on this repo?** Read [CLAUDE.md](CLAUDE.md) first — it holds the
> brief, the fixed tech stack, the schema, and the invariants.

This README covers setup only. Feature documentation comes in a later phase.

---

## Prerequisites

- Docker Desktop (Compose v2+)
- Optional, only for running services outside Docker: Python 3.11+, Node.js 20+

Nothing else needs to be installed — Postgres, the backend, and the frontend all
run in containers.

## Setup

**1. Clone and enter the repo**

```bash
git clone https://github.com/devaskswhy/RingSentinel.git
cd RingSentinel
```

**2. Create your env file**

```bash
cp .env.example .env
```

The defaults work as-is for local development. `.env.example` documents every
variable and where to obtain it. Razorpay and Claude credentials are not needed
until later phases.

**3. Start the stack**

```bash
docker compose up
```

This starts Postgres, applies the database migrations automatically, then starts
the backend and frontend. First run builds the images and takes a few minutes.

**4. Seed**

In a second terminal:

```bash
docker compose exec backend python -m scripts.seed
```

Phase 1 seeds no fraud data by design — this command verifies that every table,
view, enum, and constraint exists and that the audit log really is append-only.

**5. Seed the synthetic corpus (Phase 2)**

This creates real Razorpay **test-mode** orders and ingests them through the
webhook pipeline. It needs test credentials in `.env` first:

- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — Razorpay Dashboard → Test Mode →
  Account & Settings → API Keys. The key id must start with `rzp_test_`.
- `RAZORPAY_WEBHOOK_SECRET` — any value locally; the seed signs the events it
  replays with it. Generate one with:
  `python -c "import secrets; print('whsec_local_'+secrets.token_hex(16))"`

Then:

```bash
# See the plan without calling Razorpay or writing anything
docker compose exec backend python -m scripts.seed_rings --dry-run

# Smoke test: 20 real orders
docker compose exec backend python -m scripts.seed_rings --limit 20

# Full corpus (~1,500 orders; several minutes at the default 4 calls/sec)
docker compose exec backend python -m scripts.seed_rings --reset
```

Verify the ingest pipeline at any time (rolls back, writes nothing):

```bash
docker compose exec backend python -m scripts.verify_ingest
```

**6. Detect rings and review them (Phases 3-4)**

```bash
# Find coordinated clusters and write them to the review queue
docker compose exec backend python -m scripts.detect

# Write Claude's plain-language case file for each flagged cluster
docker compose exec backend python -m scripts.generate_case_files
```

Claude case files need a Claude subscription login, not an API key. Either set
`CLAUDE_CODE_OAUTH_TOKEN` in `.env` (run `claude setup-token` to get one), or
point `CLAUDE_CONFIG_HOST_DIR` at your `~/.claude` so the container reuses your
existing login. Check it with:

```bash
docker compose exec backend python -m scripts.verify_claude_auth
```

Then review through the API:

```bash
curl localhost:8000/clusters                       # the queue
curl localhost:8000/clusters/<id>                  # case file + evidence + graph

curl -X POST localhost:8000/clusters/<id>/approve      -H 'Content-Type: application/json'      -d '{"reason":"why you decided this","reviewer":"your name"}'
```

Approving or dismissing requires a written reason, and only a human review can
record a decision — a database trigger rejects any other attempt, and a recorded
decision can never be revised. Nothing in RingSentinel blocks, freezes, or
restricts a customer account.

**7. Score the detector honestly**

```bash
# Paste-ready evaluation summary; --store records the snapshot
docker compose exec backend python -m scripts.report --split holdout --store

# The same numbers as JSON, feeding the console scorecard
curl localhost:8000/metrics
```

Rings 9–12 were held out through all tuning and evaluated once. Re-running
reproduces; changing a threshold in response to what it shows would turn them
into a second tuning set, and there is no third.

**Verification scripts** — each proves an invariant rather than asserting it:

```bash
docker compose exec backend python -m scripts.verify_detector_isolation  # #4
docker compose exec backend python -m scripts.verify_human_gate          # #1 #2 #3
docker compose exec backend python -m scripts.verify_ingest              # idempotency
docker compose exec backend python -m scripts.verify_claude_auth         # auth path
```

## Verify it worked

| What | Where |
|---|---|
| Landing page | http://localhost:3000 |
| Review console | http://localhost:3000/console |
| API docs | http://localhost:8000/docs |
| Liveness | http://localhost:8000/health |
| Schema health | http://localhost:8000/health/db |
| Corpus summary (after seeding) | http://localhost:8000/eval/corpus |
| Review queue | http://localhost:8000/clusters |
| Held-out metrics | http://localhost:8000/metrics |

`/health/db` should report `"status": "ok"` with an empty `tables_missing`.

## Optional: check the Claude auth path

Needed from Phase 4 onward. Run `claude setup-token`, put the token in `.env` as
`CLAUDE_CODE_OAUTH_TOKEN`, then:

```bash
docker compose exec backend python -m scripts.verify_claude_auth
```

## Common commands

```bash
docker compose up --build      # rebuild after changing dependencies
docker compose down            # stop
docker compose down -v         # stop and delete the database volume
docker compose logs -f backend # tail backend logs

docker compose exec backend alembic upgrade head    # apply migrations manually
docker compose exec backend alembic downgrade -1    # roll back one migration
```

## Troubleshooting

**Port already in use** — change `POSTGRES_PORT`, `BACKEND_PORT`, or
`FRONTEND_PORT` in `.env`, then `docker compose up` again.

**Backend exits on start** — it applies migrations before serving. Check
`docker compose logs backend`; a failed migration stops the container by design.

**Schema looks stale after editing models** — models alone do not change the
database. Generate and apply a migration (see CLAUDE.md §6).
