"""tiered review comments: tl_qc_comment + review_comment (replaces reject_comment)

Splits the single ``reject_comment`` (only kept on reject) into two attributed notes
so BOTH the Team Leader QC's comment (on approve/reject/escalate) and the SPQ Head's
comment (on approve/reject) are stored and shown next to their author. Applies to
error-code appeals and QC status ("Manual Status") requests.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("error_code_appeals", "qc_status_requests")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("tl_qc_comment", sa.Text(), nullable=True))
        op.add_column(t, sa.Column("review_comment", sa.Text(), nullable=True))
        op.drop_column(t, "reject_comment")


def downgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("reject_comment", sa.Text(), nullable=True))
        op.drop_column(t, "review_comment")
        op.drop_column(t, "tl_qc_comment")
