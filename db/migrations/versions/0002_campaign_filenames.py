"""add original upload filenames to campaigns

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("prompt_filename", sa.String(255), nullable=True))
    op.add_column("campaigns", sa.Column("scorecard_filename", sa.String(255), nullable=True))
    op.add_column("campaigns", sa.Column("kb_filename", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "kb_filename")
    op.drop_column("campaigns", "scorecard_filename")
    op.drop_column("campaigns", "prompt_filename")
