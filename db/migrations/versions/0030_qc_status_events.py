"""Jejak audit append-only untuk Manual Status

``qc_status_requests`` memakai pola UPSERT dengan ``UNIQUE(result_id)`` — satu baris
per tiket yang DITIMPA setiap kali berubah. Akibatnya vonis sebelumnya, alasannya,
siapa & kapan, serta komentar TL QC / SPQ Head hilang permanen setiap kali Manual
Status diubah. (Docstring ``QcManualCheck`` sudah menyebut pola itu "destructive".)

Kebutuhannya meningkat setelah dua perubahan terakhir: permintaan baru kini mereset
KEDUA tier review (perbaikan bug warisan keputusan), dan TL QC / SPQ Head boleh
menetapkan Manual Status LANGSUNG tanpa approval — jadi tidak ada tahap review yang
bisa dijadikan bukti siapa memutuskan apa.

Tabel ini APPEND-ONLY dan berdiri sendiri: tidak ada satu pun jalur baca yang berubah
(``qc_status_requests`` tetap satu baris per tiket). Riwayat sebelum tabel ini
dipasang TIDAK bisa direkonstruksi — data lamanya sudah tertimpa.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qc_status_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=False),
        # usul | set_langsung | tl_approve | tl_reject | tl_escalate | spq_approve | spq_reject
        sa.Column("event", sa.String(20), nullable=False),
        sa.Column("actor_username", sa.String(100)),
        sa.Column("actor_role", sa.String(20)),
        # Vonis yang diusulkan/ditetapkan pada saat itu (PASS | FAIL | PENDING).
        sa.Column("requested_status", sa.String(10)),
        # Manual Status EFEKTIF sebelum & sesudah event ini (NULL = belum ada vonis).
        sa.Column("status_before", sa.String(10)),
        sa.Column("status_after", sa.String(10)),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["result_id"], ["results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qc_status_events_result_id", "qc_status_events", ["result_id"])


def downgrade() -> None:
    op.drop_index("ix_qc_status_events_result_id", table_name="qc_status_events")
    op.drop_table("qc_status_events")
