"""error_code_appeals.qc_new_error_code (QC-proposed replacement Error Code)

Adds an optional column holding the new Error Code a QC proposes on the Manual
Check form (placeholder shows the existing code). Surfaced read-only to Team
Leader QC and SPQ Head in the appeal review.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("error_code_appeals", sa.Column("qc_new_error_code", sa.String(20)))


def downgrade() -> None:
    op.drop_column("error_code_appeals", "qc_new_error_code")
