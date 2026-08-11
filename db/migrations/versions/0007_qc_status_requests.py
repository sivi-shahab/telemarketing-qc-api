"""qc_status_requests table (QC-proposed AI-Status change + Admin approval)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qc_status_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requested_status", sa.String(4), nullable=False),  # PASS | FAIL
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("requested_by_username", sa.String(100)),
        sa.Column("requested_by_role", sa.String(20)),
        sa.Column("requested_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_username", sa.String(100)),
        sa.Column("reviewed_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("qc_status_requests")
