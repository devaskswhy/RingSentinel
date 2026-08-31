"""The product invariants, tested where a unit test can reach them.

`scripts/verify_human_gate.py` and `scripts/verify_detector_isolation.py` prove
these against a live database and by walking the AST, and they remain the real
proof. What is added here is speed: these run in milliseconds with no database,
so a violation surfaces on the commit that introduces it rather than the next
time somebody remembers to run the verifiers.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _python_files(package: str) -> list[pathlib.Path]:
    return [
        p
        for p in (BACKEND / package).rglob("*.py")
        if "__pycache__" not in p.parts
    ]


class TestInvariantOneNothingCanAct:
    """Invariant #1: no code path may block, freeze or decline a customer."""

    FORBIDDEN = ("block_customer", "freeze_account", "decline_payment", "ban_account")

    def test_no_acting_function_is_defined_anywhere(self):
        offenders = []
        for path in _python_files("app") + _python_files("detection"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name in self.FORBIDDEN:
                        offenders.append(f"{path.name}:{node.name}")
        assert not offenders, offenders


class TestInvariantTwoOnlyOneWriterOfDecisions:
    """Invariant #2: `app/routers/clusters.py` is the only module that may
    record a decision, and the only one that may set the transaction flag the
    Postgres guard demands."""

    GUARD_FLAG = "ringsentinel.human_review"

    def test_only_the_gate_sets_the_human_review_flag(self):
        setters = [
            path.relative_to(BACKEND).as_posix()
            for path in _python_files("app")
            + _python_files("detection")
            + _python_files("evaluation")
            + _python_files("scripts")
            if self.GUARD_FLAG in path.read_text(encoding="utf-8")
            and not path.name.startswith("verify_")
        ]
        assert setters == ["app/routers/clusters.py"], setters

    def test_the_gate_demands_a_written_reason(self):
        source = (BACKEND / "app/routers/clusters.py").read_text(encoding="utf-8")
        assert "min_length=5" in source or "min_length =" in source, (
            "the reason requirement is enforced in Postgres too (migration "
            "0007), but the API must not stop asking for it"
        )


class TestInvariantFourTheDetectorCannotSeeLabels:
    """Invariant #4: `detection/` reads the label-free view and never imports
    `evaluation.*`.

    Deliberately an AST walk rather than a grep: `graph.py` legitimately
    mentions the ground-truth column in a docstring, and a grep would fail on
    prose while missing a computed string.
    """

    LABEL = "is_synthetic_ring_id"

    def test_no_executable_string_names_the_label_column(self):
        offenders = []
        for path in _python_files("detection"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and self.LABEL in node.value
                    and id(node) not in docstrings
                ):
                    offenders.append(f"{path.name}: {node.value[:60]}")
        assert not offenders, offenders

    def test_detection_never_imports_evaluation(self):
        offenders = []
        for path in _python_files("detection"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "evaluation"
                ):
                    offenders.append(f"{path.name} -> {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("evaluation"):
                            offenders.append(f"{path.name} -> {alias.name}")
        assert not offenders, offenders

    def test_detection_queries_the_view_not_the_base_table(self):
        """The view is what makes invariant #4 a property of the database
        rather than a matter of discipline.
        """
        offenders = []
        for path in _python_files("detection"):
            source = path.read_text(encoding="utf-8").lower()
            if "from transactions" in source:
                offenders.append(path.name)
        assert not offenders, offenders


class TestInvariantFiveTestModeOnly:
    """Invariant #5: a live Razorpay key must never appear anywhere."""

    def test_no_live_key_value_appears_anywhere(self):
        """A live key is 'rzp_live_' followed by an actual secret.

        The prefix ALONE is not a violation — `razorpay_client.py` has to name
        it in order to reject it, and this test file has to name it in order to
        test the rejection. What must never appear is the prefix followed by
        something that looks like a real key body, so that is what is matched.
        """
        credential = re.compile(r"rzp_live_[A-Za-z0-9]{8,}")
        allowed = {"test_invariants.py"}  # constructs one deliberately, below
        offenders = []
        for path in BACKEND.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".sh", ".yml", ".yaml", ".env", ".txt", ".md"}:
                continue
            if path.name in allowed:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if credential.search(line):
                    offenders.append(f"{path.name}: {line.strip()[:70]}")
        assert not offenders, offenders

    def test_the_prefix_guard_itself_is_still_present(self):
        """Pairs with the test above, which would also pass if the guard were
        deleted outright. A rejection nobody performs is not a rejection.
        """
        source = (BACKEND / "app/razorpay_client.py").read_text(encoding="utf-8")
        assert "rzp_live_" in source, "the live-key guard has been removed"

    def test_the_client_refuses_a_live_key(self):
        from app.config import Settings

        live = Settings(razorpay_key_id="rzp_live_abcdef123456")
        assert live.razorpay_is_test_mode is False

        test = Settings(razorpay_key_id="rzp_test_abcdef123456")
        assert test.razorpay_is_test_mode is True


class TestDefensiveOnly:
    """The track rule: strictly defence-only.

    §5k records that a literal grep cannot prove this, because writing the
    policy down necessarily contains the vocabulary the policy is about. What
    *is* mechanical is that no module produces guidance: nothing here generates
    a recipe, and the adversarial designer returns a specification that this
    repo realises, measures and rolls back.
    """

    def test_the_designer_produces_a_specification_and_writes_nothing(self):
        """Claude returns a *shape* — how many accounts, what they share, how
        they are paced — which this repo then realises. `adversarial.py` builds
        `RobustnessCase` objects and never touches a session; anything it
        emitted directly would be model output reaching the database.
        """
        source = (BACKEND / "evaluation/adversarial.py").read_text(encoding="utf-8")
        assert "RobustnessCase" in source
        for writer in ("db.add", "db.commit", "session.add", "session.commit"):
            assert writer not in source, f"the designer writes: {writer}"

    def test_realised_cases_are_rolled_back_and_never_persisted(self):
        """The insert/measure/roll-back harness both this and the Phase 9
        robustness cases run through. Two properties would otherwise be
        damaged: every stored transaction traces to a real Razorpay order, and
        the held-out numbers must not be disturbed by diagnostic data.
        """
        source = (BACKEND / "evaluation/blindspots.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        rolled_back = any(
            isinstance(node, ast.Try) and node.finalbody for node in ast.walk(tree)
        )
        assert rolled_back, "cases must be rolled back in a finally"
        assert "rollback" in source.lower()
        assert "db.commit" not in source, "the harness must never commit"

    def test_the_model_designing_cases_has_no_tools(self):
        for module in ("evaluation/adversarial.py", "app/case_files.py"):
            source = (BACKEND / module).read_text(encoding="utf-8")
            assert "allowed_tools=[]" in source, module
