"""drop results.passing_grade (passing_grade is now dynamic from LLM output)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("results", "passing_grade")


def downgrade() -> None:
    op.add_column("results", sa.Column("passing_grade", sa.Float(), nullable=True))
