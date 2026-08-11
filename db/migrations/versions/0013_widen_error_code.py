"""Widen error_code_appeals.error_code (fits Cashline "B02/B03/B05" fallback)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cashline rows can carry the generic "B02/B03/B05" fallback code (11 chars),
    # which overflows the original String(10). Widen to String(20).
    op.alter_column(
        "error_code_appeals",
        "error_code",
        type_=sa.String(20),
        existing_type=sa.String(10),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "error_code_appeals",
        "error_code",
        type_=sa.String(10),
        existing_type=sa.String(20),
        existing_nullable=False,
    )
