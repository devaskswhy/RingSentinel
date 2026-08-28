"""Give clusters a stable identity across detection runs.

The problem this fixes
----------------------
`_persist` deleted every pending cluster and inserted fresh rows on each run.
Two consequences, both bad:

  - Case files cascade-deleted with their cluster. Each one is a ~20s Claude
    call, so a routine `detect` run silently threw away minutes of generated
    explanation.
  - A group a human had already approved got re-flagged as a brand new pending
    cluster on the next run, so the review queue filled with duplicates of work
    already done.

The fix is a fingerprint over the cluster's customer accounts. The same set of
accounts produces the same fingerprint, so a re-run updates the existing row
in place - score, evidence, cadence - and leaves its status, its case files, and
its audit history intact.

Nullable and non-unique on purpose: rows written before this migration have no
fingerprint, and two genuinely different runs could in principle land on the
same account set, which is a match rather than an error.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clusters", sa.Column("fingerprint", sa.Text(), nullable=True))
    op.create_index("ix_clusters_fingerprint", "clusters", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_clusters_fingerprint", table_name="clusters")
    op.drop_column("clusters", "fingerprint")
