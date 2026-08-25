"""RingSentinel seed / bootstrap verification.

Phase 1 deliberately seeds NO fraud data - the brief forbids fake or mock data
until the synthetic generator lands in Phase 2. What this command does instead
is prove the database is actually usable:

  1. every expected table, view, and enum type exists
  2. the audit_log append-only trigger really blocks UPDATE and DELETE
  3. the detector view does not expose the ground-truth label
  4. a single bootstrap row is written to audit_log (idempotent)

Run it with:  docker compose exec backend python -m scripts.seed
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.db import engine

EXPECTED_TABLES = [
    "entities",
    "entity_links",
    "transactions",
    "clusters",
    "cluster_members",
    "audit_log",
]
EXPECTED_ENUMS = ["entity_type", "link_type", "cluster_status", "audit_actor"]
GROUND_TRUTH_COLUMN = "is_synthetic_ring_id"

_ok = "[ok]"
_fail = "[FAIL]"


def check_tables(conn) -> list[str]:
    present = set(
        conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        ).scalars()
    )
    problems = []
    for table in EXPECTED_TABLES:
        if table in present:
            print(f"  {_ok} table {table}")
        else:
            print(f"  {_fail} table {table} MISSING")
            problems.append(f"missing table {table}")
    if "v_transactions_detector" in present:
        print(f"  {_ok} view v_transactions_detector")
    else:
        print(f"  {_fail} view v_transactions_detector MISSING")
        problems.append("missing view v_transactions_detector")
    return problems


def check_enums(conn) -> list[str]:
    present = set(conn.execute(text("SELECT typname FROM pg_type")).scalars())
    problems = []
    for enum_name in EXPECTED_ENUMS:
        if enum_name in present:
            print(f"  {_ok} enum {enum_name}")
        else:
            print(f"  {_fail} enum {enum_name} MISSING")
            problems.append(f"missing enum {enum_name}")
    return problems


def check_ground_truth_isolation(conn) -> list[str]:
    cols = set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'v_transactions_detector'"
            )
        ).scalars()
    )
    if GROUND_TRUTH_COLUMN in cols:
        print(f"  {_fail} detector view LEAKS {GROUND_TRUTH_COLUMN}")
        return [f"detector view exposes {GROUND_TRUTH_COLUMN}"]
    print(f"  {_ok} detector view hides {GROUND_TRUTH_COLUMN}")
    return []


def check_append_only(conn) -> list[str]:
    """Confirm UPDATE and DELETE against audit_log are both rejected.

    Reuses an existing probe row when present - the table is append-only, so a
    fresh probe row on every run would accumulate rows that can never be cleaned
    up.
    """
    problems = []
    probe_id = conn.execute(
        text(
            "SELECT id FROM audit_log WHERE action = 'append_only_probe' "
            "ORDER BY id DESC LIMIT 1"
        )
    ).scalar()

    if probe_id is None:
        conn.execute(
            text(
                "INSERT INTO audit_log "
                "(actor, action, target_type, target_id, detail_json) "
                "VALUES ('system', 'append_only_probe', 'system', 'seed', '{}'::jsonb)"
            )
        )
        probe_id = conn.execute(
            text(
                "SELECT id FROM audit_log WHERE action = 'append_only_probe' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()

    for op_name, statement in (
        ("UPDATE", "UPDATE audit_log SET action = 'tampered' WHERE id = :i"),
        ("DELETE", "DELETE FROM audit_log WHERE id = :i"),
    ):
        savepoint = conn.begin_nested()
        try:
            conn.execute(text(statement), {"i": probe_id})
            savepoint.rollback()
            print(f"  {_fail} audit_log {op_name} was ALLOWED - trigger not active")
            problems.append(f"audit_log {op_name} not blocked")
        except Exception:
            savepoint.rollback()
            print(f"  {_ok} audit_log {op_name} blocked")
    return problems


def write_bootstrap_row(conn) -> None:
    already = conn.execute(
        text("SELECT count(*) FROM audit_log WHERE action = 'schema_bootstrap'")
    ).scalar_one()
    if already:
        print(f"  {_ok} bootstrap audit row already present (skipped)")
        return
    # CAST(:detail AS jsonb), not :detail::jsonb - SQLAlchemy's text() bind
    # parser cannot disambiguate the "::" cast operator from a ":param" marker.
    conn.execute(
        text(
            "INSERT INTO audit_log (actor, action, target_type, target_id, detail_json) "
            "VALUES ('system', 'schema_bootstrap', 'database', 'ringsentinel', "
            "CAST(:detail AS jsonb))"
        ),
        {"detail": '{"phase": 1, "seeded_records": 0, "note": "schema only"}'},
    )
    print(f"  {_ok} wrote bootstrap audit row")


def main() -> int:
    print("RingSentinel seed - Phase 1 (schema verification, no fraud data)\n")
    problems: list[str] = []

    with engine.begin() as conn:
        print("Tables and views:")
        problems += check_tables(conn)
        print("\nEnum types:")
        problems += check_enums(conn)
        print("\nGround-truth isolation:")
        problems += check_ground_truth_isolation(conn)
        print("\nAudit log append-only guard:")
        problems += check_append_only(conn)
        print("\nBootstrap:")
        write_bootstrap_row(conn)

    print()
    if problems:
        print(f"{_fail} seed finished with {len(problems)} problem(s):")
        for p in problems:
            print(f"   - {p}")
        return 1

    print(f"{_ok} schema verified. 0 fraud records seeded (Phase 1 seeds none).")
    print("     Synthetic ring generation lands in Phase 2 - see CLAUDE.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
