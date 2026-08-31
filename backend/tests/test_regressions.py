"""Bugs that shipped once. Each of these was real, and each was invisible.

A test is worth writing when the bug it catches would otherwise pass review,
pass a smoke test, and produce a confident wrong answer. Every case here did
exactly that.
"""

from __future__ import annotations

import re

import pytest

from app.config import _normalise_database_url
from evaluation.explanation_quality import FREE_NUMBER_CEILING, _numbers_in


class TestGraderTokeniser:
    """§5k: the tokeniser that matched nothing and reported 100%.

    It shipped with its `\\b` word boundaries replaced by literal backspace
    bytes (0x08) — a shell heredoc consumed the escape before Python saw it,
    *inside a raw string*, where it is invisible in every editor. The pattern
    became `\\x08\\d{1,6}\\x08`, matched no digits at all, and a case file
    claiming 9,471 transactions passed the grounding check cleanly.

    The pass rate did not reveal it. Nothing did, until the numbers were
    counted. These tests count them.
    """

    def test_extracts_a_plain_integer(self):
        assert 9471 in _numbers_in("the cluster covers 9471 transactions")

    def test_extracts_a_comma_grouped_integer(self):
        assert 9471 in _numbers_in("the cluster covers 9,471 transactions")

    def test_does_not_shred_comma_groups_into_fragments(self):
        """A naive \\b\\d{1,4}\\b scan reads '3,328-8,608 INR, median 6,128' as
        3, 328, 8, 608 and 128 — none of which appear in the evidence — and
        reports three fabrications in a sentence that was entirely accurate.
        """
        found = _numbers_in("amounts ran 3,328-8,608 INR, median 6,128")
        assert 328 not in found
        assert 608 not in found

    def test_finds_something_at_all(self):
        """The empty-set guard, stated as its own test.

        This project has now had three checkers report success over an empty
        set: this tokeniser, the blind-spot matcher whose LIKE pattern matched
        no subjects, and a chain verifier over zero rows. A tokeniser that
        returns nothing must fail here rather than pass everything downstream.
        """
        body = "1,499 transactions across 12 clusters, 635 entities, 4089 links"
        found = _numbers_in(body)
        assert found, "tokeniser matched nothing — the 0x08 failure mode"
        assert {1499, 635, 4089} <= found

    def test_no_control_characters_in_the_compiled_patterns(self):
        """Guards the exact mechanism rather than only its symptom.

        The corruption is invisible on screen, so this asserts on the module's
        source bytes: no C0 control character may appear in it except tab,
        newline and carriage return.
        """
        import evaluation.explanation_quality as mod

        raw = open(mod.__file__, "rb").read()
        illegal = {b for b in raw if b < 0x20 and b not in (0x09, 0x0A, 0x0D)}
        assert not illegal, f"control bytes in source: {sorted(illegal)}"

    def test_small_integers_are_ordinary_english(self):
        """'two of the four' is prose, not a claim. Documented as a limit of
        the grader's reach rather than hidden — §5k reports that of 111 numbers
        asserted across 15 case files, only 31 were genuinely constrained.
        """
        assert FREE_NUMBER_CEILING == 32


class TestDatabaseUrlNormaliser:
    """The deploy bug: SQLAlchemy read the host's URL as psycopg2.

    Managed hosts hand out `postgresql://…`, which SQLAlchemy resolves to
    psycopg2 — a driver this project does not install. The failure at startup
    named the driver and not the cause. Every form below was seen from Neon
    during the actual deploy.
    """

    @pytest.mark.parametrize(
        "given",
        [
            "postgres://u:p@host/db",
            "postgresql://u:p@host/db",
            "postgresql://u:p@host/db?sslmode=require",
            "postgresql://u:p@ep-x-pooler.region.aws.neon.tech/neondb?sslmode=require",
        ],
    )
    def test_every_host_given_form_becomes_psycopg3(self, given):
        assert _normalise_database_url(given).startswith("postgresql+psycopg://")

    def test_the_query_string_is_left_alone(self):
        """sslmode is how the connection is secured. Rewriting the scheme must
        not touch it.
        """
        out = _normalise_database_url("postgresql://u:p@host/db?sslmode=require")
        assert out.endswith("?sslmode=require")

    def test_an_already_correct_url_is_unchanged(self):
        url = "postgresql+psycopg://u:p@db:5432/ringsentinel"
        assert _normalise_database_url(url) == url

    def test_normalising_twice_is_the_same_as_once(self):
        """Alembic and the app both normalise. If this were not idempotent the
        second pass would corrupt the first.
        """
        once = _normalise_database_url("postgres://u:p@host/db")
        assert _normalise_database_url(once) == once


class TestAuditActionNames:
    """§5c: `f"cluster_{action}d"` produced `cluster_dismissd`.

    An audit trail with a typo in an action name is one nobody can reliably
    query, and the row is written correctly enough that nothing complains.
    """

    def test_names_are_spelled_out_not_constructed(self):
        from app.routers.clusters import ACTION_TO_AUDIT_NAME

        assert ACTION_TO_AUDIT_NAME["approve"] == "cluster_approved"
        assert ACTION_TO_AUDIT_NAME["dismiss"] == "cluster_dismissed"

    def test_every_name_is_a_real_past_participle(self):
        from app.routers.clusters import ACTION_TO_AUDIT_NAME

        for name in ACTION_TO_AUDIT_NAME.values():
            assert re.fullmatch(r"cluster_[a-z]+ed", name), name


class TestCounterfactualCannotDriftFromScoring:
    """§5i: the counterfactual imports the weights rather than restating them.

    Restated constants are the classic way for two files to disagree quietly —
    the counterfactual would keep answering 'how close was this?' using weights
    the scorer no longer uses, and every answer would look reasonable.
    """

    def test_module_declares_no_numeric_weight_of_its_own(self):
        import detection.counterfactual as mod

        source = open(mod.__file__, encoding="utf-8").read()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        # A module-level float assignment would be a restated constant.
        restated = re.findall(r"^\s*[A-Z_]{3,}\s*=\s*[\d.]+", code, re.MULTILINE)
        assert not restated, f"counterfactual restates constants: {restated}"

    def test_it_imports_from_config(self):
        import detection.counterfactual as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "from detection.config import" in source
