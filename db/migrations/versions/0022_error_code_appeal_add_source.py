"""error_code_appeals.add_source (for appeal_kind='add')

The new 'add' banding lets QC propose a NEW error code. Because the code is picked
from the master catalog (which does not imply a source), the source is stored
explicitly: 'scorecard'|'cashline_data'|'card_holder'|'others'. NULL for the
existing 'remove'/'change' bandings.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("error_code_appeals", sa.Column("add_source", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("error_code_appeals", "add_source")
