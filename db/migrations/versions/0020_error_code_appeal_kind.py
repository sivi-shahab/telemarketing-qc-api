"""error_code_appeals.appeal_kind (remove vs change)

Distinguishes a banding that REMOVES the error code (current behaviour: approve
flips the scorecard item / verification field, dropping the error and lifting the
score) from one that only CHANGES the code to another (New Error Code) without
necessarily removing the error. Default 'remove' keeps existing rows behaving as
before.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "error_code_appeals",
        sa.Column("appeal_kind", sa.String(10), nullable=False, server_default="remove"),
    )


def downgrade() -> None:
    op.drop_column("error_code_appeals", "appeal_kind")
