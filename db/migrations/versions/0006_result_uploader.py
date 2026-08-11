"""track transcript uploader on results (username + role)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column("uploaded_by_username", sa.String(length=100), nullable=True))
    op.add_column("results", sa.Column("uploaded_by_role", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "uploaded_by_role")
    op.drop_column("results", "uploaded_by_username")
