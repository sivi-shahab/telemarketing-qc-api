"""qc_manual_checks table (per-ticket "sudah dicek manual oleh QC" audit trail)

Append-only: one row per approval event, keyed by result_id. The latest row per
result_id is the authoritative state; earlier rows are kept as the audit trail.
Mirrors the error_code_appeals pattern rather than the upsert qc_status_requests one.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qc_manual_checks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checked_by_username", sa.String(100), nullable=False),
        sa.Column("checked_by_role", sa.String(20)),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_qc_manual_checks_result_id", "qc_manual_checks", ["result_id"])


def downgrade() -> None:
    op.drop_index("idx_qc_manual_checks_result_id")
    op.drop_table("qc_manual_checks")
