"""provisi + penalti pelunasan dipercepat as TMS columns

Both were constants in ``compliance/reference_data.py`` ("2% dari limit kredit" /
"7% dari sisa pokok pinjaman") because the TMS export carries no column for them.
Holding them as data lets a ticket override the product default (a promo rate) and
removes the frozen constants from code.

Existing rows are backfilled with those same constants, so verification behaves
exactly as before for historical tickets. A row left empty falls back to the
campaign's RIPLAY value (TnC Product) — see compliance/reference_data.py.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tms_cashline", sa.Column("provisi", sa.Text(), nullable=True))
    op.add_column(
        "tms_cashline",
        sa.Column("penalti-pelunasan-dipercepat", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE tms_cashline
           SET provisi = '2% dari limit kredit',
               "penalti-pelunasan-dipercepat" = '7% dari sisa pokok pinjaman'
        """
    )


def downgrade() -> None:
    op.drop_column("tms_cashline", "penalti-pelunasan-dipercepat")
    op.drop_column("tms_cashline", "provisi")
