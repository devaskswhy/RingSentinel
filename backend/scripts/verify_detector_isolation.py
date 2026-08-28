"""Prove the detector cannot see ground truth. CLAUDE.md invariant #4.

A grep is not good enough here: `detection/graph.py` legitimately *mentions*
`is_synthetic_ring_id` in a docstring, explaining that the view omits it. So this
walks the AST and inspects executable string literals only, ignoring docstrings
and comments entirely.

Four checks:
  1. no module under detection/ imports the evaluation package
  2. no executable string literal in detection/ names the ground-truth column
  3. no executable string literal in detection/ selects the base transactions table
  4. at runtime, the view the detector reads really lacks the column

Run:  docker compose exec backend python -m scripts.verify_detector_isolation
"""

from __future__ import annotations

import ast
import pathlib
import sys

from sqlalchemy import text

from app.db import SessionLocal

OK = "[ok]"
FAIL = "[FAIL]"

GROUND_TRUTH_COLUMN = "is_synthetic_ring_id"
BASE_TABLE_PATTERNS = ("from transactions", "join transactions", "update transactions")
DETECTION_DIR = pathlib.Path(__file__).resolve().parents[1] / "detection"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of Constant nodes that are docstrings, so we can ignore them."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def check_module(path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_nodes(tree)

    # 1. imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "evaluation"
        ):
            problems.append(
                f"{path.name}:{node.lineno} imports from the evaluation package"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("evaluation"):
                    problems.append(
                        f"{path.name}:{node.lineno} imports {alias.name}"
                    )

    # 2 & 3. executable string literals only
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        lowered = node.value.lower()
        if GROUND_TRUTH_COLUMN in lowered:
            problems.append(
                f"{path.name}:{node.lineno} executable string names "
                f"{GROUND_TRUTH_COLUMN}"
            )
        for pattern in BASE_TABLE_PATTERNS:
            if pattern in lowered:
                problems.append(
                    f"{path.name}:{node.lineno} executable string queries the "
                    f"base transactions table ({pattern!r})"
                )
    return problems


def main() -> int:
    print("Detector ground-truth isolation check (CLAUDE.md invariant #4)\n")
    problems: list[str] = []

    modules = sorted(DETECTION_DIR.glob("*.py"))
    print(f"Static analysis of {len(modules)} module(s) under detection/:")
    for path in modules:
        found = check_module(path)
        if found:
            problems.extend(found)
            for item in found:
                print(f"  {FAIL} {item}")
        else:
            print(f"  {OK} {path.name}")

    print("\nRuntime check:")
    db = SessionLocal()
    try:
        columns = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'v_transactions_detector'"
                )
            ).all()
        }
        if not columns:
            print(f"  {FAIL} v_transactions_detector does not exist")
            problems.append("detector view missing")
        elif GROUND_TRUTH_COLUMN in columns:
            print(f"  {FAIL} the view exposes {GROUND_TRUTH_COLUMN}")
            problems.append("view leaks ground truth")
        else:
            print(f"  {OK} v_transactions_detector has {len(columns)} columns, "
                  f"none of them {GROUND_TRUTH_COLUMN}")

        # The detector must still be able to do its job through the view.
        usable = db.execute(
            text("SELECT count(*) FROM v_transactions_detector")
        ).scalar_one()
        print(f"  {OK} view is queryable: {usable} transactions visible")
    finally:
        db.close()

    print()
    if problems:
        print(f"{FAIL} {len(problems)} isolation problem(s) found.")
        return 1
    print(f"{OK} the detector cannot read ground truth, by construction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
