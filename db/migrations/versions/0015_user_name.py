"""add name column to users

Adds an optional display name (full name) to user accounts, entered alongside the
username (NIP) in the "Buat User Baru" form.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "name")
