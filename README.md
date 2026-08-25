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

## Verify it worked

| What | Where |
|---|---|
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Liveness | http://localhost:8000/health |
| Schema health | http://localhost:8000/health/db |

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
