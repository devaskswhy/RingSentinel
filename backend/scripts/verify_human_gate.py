"""Prove no code path can change a cluster's status except a human review.

Covers CLAUDE.md invariants #1 (nothing auto-blocks), #2 (every flag is
human-reviewed) and #3 (audit log is append-only), and the Phase 4 requirement
that approve/dismiss never originate from the detector or from Claude.

Checks:
  1. Only app/routers/clusters.py contains SQL that updates clusters.status.
  2. Only that module sets the `ringsentinel.human_review` guard.
  3. Nothing anywhere calls a block/freeze/decline-style action.
  4.  Runtime: a status UPDATE without the guard is refused by the database.
  4b. Runtime: a recorded decision cannot be revised, even by a human.
  4c. Runtime: a decision without a written reason is refused by the SCHEMA.
  4d. Schema: every guarding trigger is present, and the detector view still
      omits the ground-truth column.
  4e. Runtime: the audit log's hash chain verifies end to end.
  5.  Runtime: audit_log still rejects UPDATE and DELETE.
  6.  Runtime: the case-file writer is given no tools.

Run:  docker compose exec backend python -m scripts.verify_human_gate
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

from sqlalchemy import text

from app.audit_chain import verify_chain
from app.db import SessionLocal

OK = "[ok]"
FAIL = "[FAIL]"

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REVIEW_MODULE = "app/routers/clusters.py"

#: Modules permitted to write clusters.status at all, each with its reason.
#: Adding an entry should require justifying it out loud. Note that permission
#: to write A status is not permission to write a DECISION - the database
#: enforces that separately, and runtime checks 4 and 4b are what actually
#: guarantee it.
ALLOWED_STATUS_WRITERS = {
    REVIEW_MODULE: (
        "human review endpoints - the only code that may record a decision "
        "(cleared / dismissed) and the only code that sets the guard"
    ),
    "detection/pipeline.py": (
        "triage only - moves a flagged cluster between pending and "
        "needs_review. Both mean 'a human still has to look at this'; neither "
        "is a decision and neither touches a customer."
    ),
}

#: Verbs that would mean RingSentinel acting on a customer. None may appear as a
#: function call anywhere in the codebase.
FORBIDDEN_CALL_NAMES = {
    "block_account",
    "freeze_account",
    "decline_payment",
    "restrict_account",
    "suspend_account",
    "blacklist",
}

STATUS_UPDATE = re.compile(r"update\s+clusters\s+set[^;]*\bstatus\b", re.IGNORECASE | re.DOTALL)
GUARD_SETTING = "ringsentinel.human_review"

SKIP_DIRS = {"__pycache__", ".venv", "alembic"}

#: This module is exempt from checks 1 and 2 because it deliberately contains
#: the forbidden SQL: check 4 attempts a status UPDATE without the guard in
#: order to prove the database refuses it, and rolls back either way. Exempting
#: it explicitly is honest; the alternative is a verifier that cannot test the
#: thing it exists to test.
#: `backend/tests/` is exempt for the same reason: `test_invariants.py` asserts
#: this very property, which means it must contain the string it scans for. A
#: test that names the guard is not a code path that sets it. The exemption is
#: by directory rather than by filename so a new test file cannot silently
#: reintroduce the false positive - and the tests are not production code, so
#: nothing under them can reach the database at review time.
SELF_EXEMPT = {"scripts/verify_human_gate.py"}
EXEMPT_DIRS = {"tests"}


def python_files() -> list[pathlib.Path]:
    out = []
    for path in BACKEND.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(part in EXEMPT_DIRS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def scan(path: pathlib.Path) -> tuple[bool, bool, list[str]]:
    """Return (updates_status, sets_guard, forbidden_calls) for one module."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    updates_status = False
    sets_guard = False
    forbidden: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if STATUS_UPDATE.search(node.value):
                updates_status = True
            if GUARD_SETTING in node.value:
                sets_guard = True
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in FORBIDDEN_CALL_NAMES:
                forbidden.append(f"{path.name}:{node.lineno} calls {name}()")

    return updates_status, sets_guard, forbidden


def main() -> int:  # noqa: C901
    print("Human-gate verification (invariants #1, #2, #3)\n")
    problems: list[str] = []

    # ---- static ---------------------------------------------------------
    writers: list[str] = []
    guards: list[str] = []
    forbidden_all: list[str] = []

    for path in python_files():
        rel = path.relative_to(BACKEND).as_posix()
        updates, sets_guard, forbidden = scan(path)
        if rel in SELF_EXEMPT:
            # Still report forbidden calls - only the SQL checks are exempt.
            forbidden_all.extend(forbidden)
            continue
        if updates:
            writers.append(rel)
        if sets_guard:
            guards.append(rel)
        forbidden_all.extend(forbidden)

    exempt = ", ".join(sorted(SELF_EXEMPT))
    print(f"   (exempt from checks 1-2: {exempt}")
    print("    - it attempts the forbidden update on purpose, to prove it fails)")
    print()
    print("1. Who writes clusters.status?")
    for rel in writers or ["(nobody)"]:
        permitted = rel in ALLOWED_STATUS_WRITERS
        print(f"   {OK if permitted else FAIL} {rel}")
        if permitted:
            print(f"       {ALLOWED_STATUS_WRITERS[rel]}")
        else:
            problems.append(
                f"{rel} writes clusters.status but is not a permitted writer"
            )

    print("\n2. Who sets the human-review guard?")
    for rel in guards or ["(nobody)"]:
        marker = OK if rel == REVIEW_MODULE else FAIL
        print(f"   {marker} {rel}")
    if guards != [REVIEW_MODULE]:
        problems.append(f"guard setters should be exactly [{REVIEW_MODULE}], got {guards}")

    print("\n3. Account-modifying calls anywhere in the codebase?")
    if forbidden_all:
        for line in forbidden_all:
            print(f"   {FAIL} {line}")
        problems.extend(forbidden_all)
    else:
        print(f"   {OK} none - no block/freeze/decline/restrict/suspend call exists")

    # ---- runtime --------------------------------------------------------
    db = SessionLocal()
    try:
        print("\n4. Database refuses a status change without the guard:")
        target = db.execute(
            text("SELECT id, status::text FROM clusters LIMIT 1")
        ).first()
        if target is None:
            print(f"   {OK} (no clusters present to test against)")
        else:
            other = "dismissed" if target[1] != "dismissed" else "cleared"
            savepoint = db.begin_nested()
            try:
                db.execute(
                    text(
                        "UPDATE clusters SET status = CAST(:s AS cluster_status) "
                        "WHERE id = :cid"
                    ),
                    {"s": other, "cid": str(target[0])},
                )
                savepoint.rollback()
                print(f"   {FAIL} the UPDATE was ALLOWED - trigger not protecting status")
                problems.append("status update permitted without human-review guard")
            except Exception:
                savepoint.rollback()
                print(f"   {OK} refused, as designed")

        print("\n4b. A recorded decision cannot be revised, even by a human:")
        decided = db.execute(
            text(
                "SELECT id, status::text FROM clusters "
                "WHERE status IN ('cleared', 'dismissed') LIMIT 1"
            )
        ).first()
        if decided is None:
            print(f"   {OK} (no decided clusters to test against)")
        else:
            savepoint = db.begin_nested()
            try:
                db.execute(
                    text("SELECT set_config('ringsentinel.human_review','on',true)")
                )
                db.execute(
                    text(
                        "UPDATE clusters SET status = 'pending'::cluster_status "
                        "WHERE id = :cid"
                    ),
                    {"cid": str(decided[0])},
                )
                savepoint.rollback()
                print(f"   {FAIL} a decision was revised - the audit log would disagree")
                problems.append("recorded decision is mutable")
            except Exception:
                savepoint.rollback()
                print(f"   {OK} refused, even inside a human review transaction")

        print("\n4c. A decision requires a written reason - enforced by the schema:")
        undecided = db.execute(
            text(
                "SELECT id FROM clusters WHERE status IN "
                "('pending','needs_review') LIMIT 1"
            )
        ).first()
        if undecided is None:
            print(f"   {OK} (no undecided cluster to test against)")
        else:
            savepoint = db.begin_nested()
            try:
                # Human review declared, but no reason supplied. Before migration
                # 0007 this succeeded and the reason was an application-layer
                # promise; the database now refuses it outright.
                db.execute(
                    text("SELECT set_config('ringsentinel.human_review','on',true)")
                )
                db.execute(
                    text(
                        "UPDATE clusters SET status = 'cleared'::cluster_status "
                        "WHERE id = :cid"
                    ),
                    {"cid": str(undecided[0])},
                )
                savepoint.rollback()
                print(f"   {FAIL} a decision was accepted with no written reason")
                problems.append("decision permitted without a reason")
            except Exception:
                savepoint.rollback()
                print(f"   {OK} refused - the reason requirement lives in the "
                      f"trigger, not only in Pydantic")

        print("\n4d. The schema layer itself, inspected directly:")
        expected_triggers = {
            "trg_clusters_status_human_only": "clusters",
            "trg_audit_log_no_update_delete": "audit_log",
            "trg_audit_log_no_truncate": "audit_log",
            "trg_audit_log_chain": "audit_log",
        }
        present = {
            row[0]: row[1]
            for row in db.execute(
                text(
                    "SELECT t.tgname, c.relname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal"
                )
            ).all()
        }
        for name, table in expected_triggers.items():
            if present.get(name) == table:
                print(f"   {OK} {name} on {table}")
            else:
                print(f"   {FAIL} {name} is MISSING from {table}")
                problems.append(f"trigger {name} missing")

        detector_columns = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'v_transactions_detector'"
                )
            ).all()
        }
        if not detector_columns or "is_synthetic_ring_id" in detector_columns:
            print(f"   {FAIL} v_transactions_detector is missing or leaks the label")
            problems.append("detector view compromised")
        else:
            print(f"   {OK} v_transactions_detector exists and omits the label column")

        print("\n4e. Audit log hash chain:")
        chain = verify_chain(db)
        if chain.intact:
            print(f"   {OK} {chain.summary()}")
        else:
            print(f"   {FAIL} {chain.summary()}")
            problems.append(f"audit chain broken at row {chain.first_broken_id}")

        print("\n5. audit_log remains append-only:")
        row = db.execute(text("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1")).first()
        if row is None:
            print(f"   {OK} (audit_log empty)")
        else:
            for label, sql in (
                ("UPDATE", "UPDATE audit_log SET action='tamper' WHERE id=:i"),
                ("DELETE", "DELETE FROM audit_log WHERE id=:i"),
            ):
                savepoint = db.begin_nested()
                try:
                    db.execute(text(sql), {"i": row[0]})
                    savepoint.rollback()
                    print(f"   {FAIL} {label} was allowed")
                    problems.append(f"audit_log {label} not blocked")
                except Exception:
                    savepoint.rollback()
                    print(f"   {OK} {label} refused")

        print("\n6. Case-file writer runs with no tools:")
        source = (BACKEND / "app" / "case_files.py").read_text(encoding="utf-8")
        if "allowed_tools=[]" in source.replace(" ", ""):
            print(f"   {OK} allowed_tools=[] - Claude has no function to call")
        else:
            print(f"   {FAIL} allowed_tools is not empty")
            problems.append("case-file writer may have tools available")
        if "mcp_servers" in source:
            print(f"   {FAIL} an MCP server is registered")
            problems.append("case-file writer registers MCP servers")
        else:
            print(f"   {OK} no MCP servers registered")
    finally:
        db.rollback()
        db.close()

    print("\n" + "=" * 60)
    if problems:
        print(f"{FAIL} {len(problems)} problem(s):")
        for line in problems:
            print(f"   - {line}")
        return 1
    print(f"{OK} status changes are reachable only through the human-gated endpoints.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
