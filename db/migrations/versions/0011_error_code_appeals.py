"""error_code_appeals table (QC per-error-code appeal + SPQ Head approval)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "error_code_appeals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(10), nullable=False),
        sa.Column("item_code", sa.String(50), nullable=False),  # SC_CL_*
        sa.Column("ai_sumber", sa.String(100)),
        sa.Column("ai_risk_base", sa.String(10)),
        sa.Column("ai_details_error", sa.Text),
        sa.Column("ai_reason", sa.Text),
        sa.Column("ai_evidence", sa.Text),
        sa.Column("ai_ticket_id", sa.String(100)),
        sa.Column("qc_reason", sa.Text, nullable=False),
        sa.Column("qc_evidence", sa.Text),
        sa.Column("qc_ticket_id", sa.String(100)),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_by_username", sa.String(100)),
        sa.Column("requested_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("reviewed_by_username", sa.String(100)),
        sa.Column("reviewed_at", sa.DateTime),
    )
    op.create_index(
        "ix_error_code_appeals_result_id", "error_code_appeals", ["result_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_error_code_appeals_result_id", table_name="error_code_appeals")
    op.drop_table("error_code_appeals")
