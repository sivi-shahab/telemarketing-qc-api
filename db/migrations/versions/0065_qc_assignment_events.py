"""Tabel qc_assignment_events — jejak audit assignment QC

``qc_assignments`` hanya menyimpan kepemilikan TERKINI: re-assign menimpa barisnya
dan "Lepas" menghapusnya. Tabel ini mencatat setiap assign / reassign / unassign
(siapa, dari QC mana ke QC mana, kapan, lewat jalur apa), append-only, ditulis di
transaksi yang sama dengan perubahannya (lihat ``crud.record_assignment_event``).

Kepemilikan yang sudah ada saat migrasi dicatat sekali sebagai ``assign`` dengan
``source='backfill'`` dan ``created_at = assigned_at`` — titik awal riwayatnya.
Re-assign / lepas SEBELUM migrasi ini tidak pernah disimpan dan tidak bisa
dipulihkan.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qc_assignment_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("qc_username", sa.String(100)),
        sa.Column("previous_qc_username", sa.String(100)),
        sa.Column("actor_username", sa.String(100)),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_qc_assignment_events_ticket_id", "qc_assignment_events", ["ticket_id"])
    op.create_index("ix_qc_assignment_events_qc_username", "qc_assignment_events", ["qc_username"])
    op.create_index("ix_qc_assignment_events_created_at", "qc_assignment_events", ["created_at"])

    op.execute(
        """
        INSERT INTO qc_assignment_events
            (ticket_id, action, qc_username, actor_username, source, created_at)
        SELECT ticket_id, 'assign', qc_username, assigned_by_username, 'backfill',
               COALESCE(assigned_at, now())
        FROM qc_assignments
        ORDER BY assigned_at, id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_qc_assignment_events_created_at", table_name="qc_assignment_events")
    op.drop_index("ix_qc_assignment_events_qc_username", table_name="qc_assignment_events")
    op.drop_index("ix_qc_assignment_events_ticket_id", table_name="qc_assignment_events")
    op.drop_table("qc_assignment_events")
