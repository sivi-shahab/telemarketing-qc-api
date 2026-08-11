"""results.generated_at (transcript "Generated" timestamp)

Wall-clock timestamp parsed from the transcript PDF header ("Generated : YYYY-MM-DD
HH:MM:SS"), latest across the ticket's PDFs. Drives ONLY the Statistics AI-status
chart x-axis; NULL falls back to uploaded_at there. Nullable — populated by the
worker on processing and backfilled for existing rows.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column("generated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "generated_at")
