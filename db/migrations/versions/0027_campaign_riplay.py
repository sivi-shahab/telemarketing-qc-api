"""RIPLAY upload + dynamic KB overlay on campaigns

Stores the RIPLAY (Ringkasan Informasi Produk dan Layanan) PDF extraction next to
the campaign config. ``kb_text_raw`` holds the knowledge base exactly as it was
uploaded; ``kb_text`` holds that same text with the RIPLAY values overlaid, so a
new RIPLAY can be re-applied to a pristine base instead of stacking edits.

Existing rows are backfilled with kb_text_raw = kb_text (no RIPLAY yet, so the
two are identical).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("kb_text_raw", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_filename", sa.String(255), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_product_name", sa.String(255), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_similarity", sa.Float(), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_extraction", postgresql.JSONB(), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_applied", postgresql.JSONB(), nullable=True))
    op.add_column("campaigns", sa.Column("riplay_uploaded_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE campaigns SET kb_text_raw = kb_text WHERE kb_text_raw IS NULL")


def downgrade() -> None:
    op.drop_column("campaigns", "riplay_uploaded_at")
    op.drop_column("campaigns", "riplay_applied")
    op.drop_column("campaigns", "riplay_extraction")
    op.drop_column("campaigns", "riplay_similarity")
    op.drop_column("campaigns", "riplay_product_name")
    op.drop_column("campaigns", "riplay_filename")
    op.drop_column("campaigns", "kb_text_raw")
