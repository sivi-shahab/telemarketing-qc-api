"""ticket_load_dates — load_date App C per tiket, untuk filter tanggal Results & Stats

Filter tanggal Results dan Stats pindah dari Tanggal Agree ke ``load_date`` App C.
Satu tiket bisa dimuat ulang di hari lain, jadi kunci tabel (ticket_id, load_date);
filter memakai load_date terakhir. Tabel baru, tidak menyentuh data yang ada.

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_load_dates",
        sa.Column("ticket_id", sa.String(100), nullable=False),
        sa.Column("load_date", sa.Date, nullable=False),
        sa.Column("campaign", sa.String(100), nullable=True),
        sa.Column("synced_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("ticket_id", "load_date"),
    )
    op.create_index("ix_ticket_load_dates_load_date", "ticket_load_dates", ["load_date"])


def downgrade() -> None:
    op.drop_index("ix_ticket_load_dates_load_date", table_name="ticket_load_dates")
    op.drop_table("ticket_load_dates")
