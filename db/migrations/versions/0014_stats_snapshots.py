"""stats_snapshots table (daily-cached Statistics dashboard payload)

Caches the full computed Statistics payload (overview, per-agent, campaign
month-to-month, org hierarchy) once per WIB calendar day so the dashboard reads
a snapshot instead of rescanning every result's evaluation JSON on each request.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stats_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.String(10), nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("computed_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stats_snapshots")
