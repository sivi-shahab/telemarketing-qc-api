"""Team Leader QC tier: intermediate review columns on appeals/qc-status + qc_assignments

Adds the tiered banding/AI-status review (QC -> Team Leader QC -> SPQ Head):
  * error_code_appeals & qc_status_requests get tl_qc_status / tl_qc_username /
    tl_qc_reviewed_at (Team Leader QC's intermediate decision; SPQ Head can only
    approve once tl_qc_status = 'approved').
Adds the QC ticket-assignment table (a Team Leader QC assigns a ticket to a QC;
one ticket -> one QC; a QC only sees / can act on assigned tickets).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Team Leader QC intermediate review on both request types ----------
    for table in ("error_code_appeals", "qc_status_requests"):
        op.add_column(
            table,
            sa.Column("tl_qc_status", sa.String(20), nullable=False, server_default="pending"),
        )
        op.add_column(table, sa.Column("tl_qc_username", sa.String(100)))
        op.add_column(table, sa.Column("tl_qc_reviewed_at", sa.DateTime))

    # --- QC ticket assignments (Team Leader QC -> QC) ---------------------
    op.create_table(
        "qc_assignments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # ticket_id = the customer-id prefix of a result's source filenames
        # (same value as tms_cashline.result_id / list_results `id`). One ticket
        # maps to exactly one QC (unique), reassignable.
        sa.Column("ticket_id", sa.String(100), nullable=False, unique=True),
        sa.Column("qc_username", sa.String(100), nullable=False),
        sa.Column("assigned_by_username", sa.String(100)),
        sa.Column("assigned_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_qc_assignments_ticket_id", "qc_assignments", ["ticket_id"])
    op.create_index("ix_qc_assignments_qc_username", "qc_assignments", ["qc_username"])


def downgrade() -> None:
    op.drop_index("ix_qc_assignments_qc_username", table_name="qc_assignments")
    op.drop_index("ix_qc_assignments_ticket_id", table_name="qc_assignments")
    op.drop_table("qc_assignments")
    for table in ("error_code_appeals", "qc_status_requests"):
        op.drop_column(table, "tl_qc_reviewed_at")
        op.drop_column(table, "tl_qc_username")
        op.drop_column(table, "tl_qc_status")
