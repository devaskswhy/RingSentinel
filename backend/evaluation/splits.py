"""Evaluation split selection. READS GROUND TRUTH - detection code must not.

Why this lives outside `detection/`
-----------------------------------
"Run detection against the tuning split only" and "the detector never sees
ground truth" pull in opposite directions: you cannot select the tuning split
without reading `is_synthetic_ring_id`.

The resolution is that split selection is an *evaluation harness* concern, not a
detector concern. This module reads the label, works out which transaction ids
are out of scope, and hands the detector an opaque set of ids to exclude. The
detector is told nothing about splits, labels, or rings - only "skip these ids".

Keeping this in a separate package from `detection/` makes the boundary
structural rather than a matter of remembering. If an import of
`evaluation.*` ever appears inside `detection/`, that is a bug.

Label format, set by the Phase 2 generator:

    ring_09|promo_farming|agent|holdout
    ^ring    ^pattern      ^cadence ^split

Background traffic has NULL and belongs to every split - it is the noise the
detector must not trip over regardless of which rings are in scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

SPLIT_TUNING = "tuning"
SPLIT_HOLDOUT = "holdout"
SPLIT_ALL = "all"


@dataclass(frozen=True)
class RingTruth:
    """Ground truth for one seeded ring."""

    ring: str
    pattern: str
    cadence: str
    split: str
    transaction_count: int
    customer_entity_ids: frozenset[uuid.UUID]

    @property
    def label(self) -> str:
        return f"{self.ring}|{self.pattern}|{self.cadence}|{self.split}"


def load_ring_truth(db: Session, split: str | None = None) -> list[RingTruth]:
    """Every seeded ring, optionally filtered to one split."""
    rows = db.execute(
        text(
            """
            SELECT split_part(is_synthetic_ring_id, '|', 1) AS ring,
                   split_part(is_synthetic_ring_id, '|', 2) AS pattern,
                   split_part(is_synthetic_ring_id, '|', 3) AS cadence,
                   split_part(is_synthetic_ring_id, '|', 4) AS split,
                   count(*)                                  AS transaction_count,
                   array_agg(DISTINCT customer_entity_id)     AS customers
            FROM transactions
            WHERE is_synthetic_ring_id IS NOT NULL
            GROUP BY 1, 2, 3, 4
            ORDER BY 1
            """
        )
    ).all()

    rings = [
        RingTruth(
            ring=r.ring,
            pattern=r.pattern,
            cadence=r.cadence,
            split=r.split,
            transaction_count=r.transaction_count,
            customer_entity_ids=frozenset(r.customers),
        )
        for r in rows
    ]
    if split and split != SPLIT_ALL:
        rings = [r for r in rings if r.split == split]
    return rings


def transactions_to_exclude(db: Session, split: str) -> set[uuid.UUID]:
    """Transaction ids the detector should NOT see for this split.

    For `tuning`, that is every transaction belonging to a held-out ring.
    Background traffic is never excluded - it is present in every split.
    """
    if split == SPLIT_ALL:
        return set()

    excluded_split = SPLIT_HOLDOUT if split == SPLIT_TUNING else SPLIT_TUNING
    rows = db.execute(
        text(
            """
            SELECT id FROM transactions
            WHERE is_synthetic_ring_id IS NOT NULL
              AND split_part(is_synthetic_ring_id, '|', 4) = :split
            """
        ),
        {"split": excluded_split},
    ).scalars()
    return set(rows)


def normal_customer_ids(db: Session) -> set[uuid.UUID]:
    """Accounts that only ever appear in unlabelled background traffic.

    An account is 'normal' only if none of its transactions carry a ring label,
    so an account bridging a ring and background traffic is not miscounted as
    clean when measuring false flags.
    """
    rows = db.execute(
        text(
            """
            SELECT customer_entity_id
            FROM transactions
            GROUP BY customer_entity_id
            HAVING count(*) FILTER (WHERE is_synthetic_ring_id IS NOT NULL) = 0
            """
        )
    ).scalars()
    return set(rows)
