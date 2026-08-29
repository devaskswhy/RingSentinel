"""Record what each case file actually cost.

The Agent SDK's ResultMessage carries `total_cost_usd`, `usage`, and
`model_usage` for every call. Storing them turns the "what would this cost at
scale?" question from an estimate into a measurement: cost per cluster is then
a number we observed, multiplied by a volume assumption, rather than two
assumptions multiplied together.

Also records which model produced the case file, so a change of model is
visible in the data rather than inferred from a deploy date.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "case_files",
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "case_files",
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "case_files",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "case_files",
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    #: Raw usage payload from the SDK, kept whole so a later pricing question can
    #: be answered without regenerating anything.
    op.add_column(
        "case_files",
        sa.Column(
            "usage_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    for column in (
        "usage_json",
        "duration_ms",
        "output_tokens",
        "input_tokens",
        "cost_usd",
    ):
        op.drop_column("case_files", column)
