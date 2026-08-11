"""reject_comment on error_code_appeals & qc_status_requests

A mandatory comment the reviewer (Team Leader QC or SPQ Head) must give when they
REJECT a banding — error-code appeal or QC AI-status request. Nullable at the DB
level (approve/escalate leave it NULL); the mandatory-on-reject rule is enforced in
the API routers.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("error_code_appeals", sa.Column("reject_comment", sa.Text(), nullable=True))
    op.add_column("qc_status_requests", sa.Column("reject_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("qc_status_requests", "reject_comment")
    op.drop_column("error_code_appeals", "reject_comment")
