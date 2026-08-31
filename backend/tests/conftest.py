"""Shared fixtures.

Every test in this suite is a **pure unit test**: no database, no network, no
Razorpay, no Claude. That is deliberate rather than lazy. The properties that
actually matter in this project — the human gate, the append-only log, the
detector's isolation from labels, the failure handling — are already proven
against a live database by `scripts/verify_*.py`, which break things for real
and roll back. Re-asserting those here against a mock would be weaker evidence
dressed up as stronger.

So this suite covers what those scripts cannot: the arithmetic, the parsing,
and the specific bugs that shipped once and must not ship twice.
"""

from __future__ import annotations

import pytest

from detection.config import DetectorConfig


@pytest.fixture
def config() -> DetectorConfig:
    """The shipped detector configuration, unmodified.

    Tests assert against the real thresholds rather than a fixture-local set,
    so retuning the detector surfaces here instead of passing silently.
    """
    return DetectorConfig()
