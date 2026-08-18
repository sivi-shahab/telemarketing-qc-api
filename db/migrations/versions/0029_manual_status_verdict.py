"""Manual Status jadi vonis human yang berdiri sendiri

Aturan yang benar: **AI Status** = vonis AI (Qualified / Not Qualified / Pending),
**Manual Status** = vonis HUMAN dengan nilai yang sama, lewat hierarki
QC -> Team Leader QC -> SPQ Head, di mana TL QC dan SPQ Head boleh menetapkannya
LANGSUNG tanpa approval. Keduanya berdiri sendiri; vonis human tidak lagi menimpa
kolom AI Status.

Dua kolom yang perlu menyesuaikan:

- ``requested_status`` masih ``String(4)`` (cukup untuk PASS/FAIL) padahal sekarang
  harus memuat ``PENDING`` juga -> dilebarkan ke ``String(10)``.
- ``origin`` baru: 'qc' (usulan QC, lewat hierarki) vs 'tl_direct' / 'spq_direct'
  (ditetapkan langsung oleh reviewer, sudah final saat dibuat). Mencerminkan kolom
  ``origin`` pada ``error_code_appeals`` (migrasi 0026), yang polanya sama.

Baris yang sudah ada tetap ``origin='qc'`` sehingga perilakunya tidak berubah.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "qc_status_requests",
        "requested_status",
        existing_type=sa.String(4),
        type_=sa.String(10),
        existing_nullable=False,
    )
    op.add_column(
        "qc_status_requests",
        sa.Column(
            "origin",
            sa.String(20),
            nullable=False,
            server_default="qc",
        ),
    )


def downgrade() -> None:
    # PENDING tidak muat di String(4); kembalikan ke FAIL agar downgrade tidak gagal
    # (FAIL = tidak lolos, pilihan paling aman untuk vonis yang belum tuntas).
    op.execute("UPDATE qc_status_requests SET requested_status = 'FAIL' WHERE requested_status = 'PENDING'")
    op.drop_column("qc_status_requests", "origin")
    op.alter_column(
        "qc_status_requests",
        "requested_status",
        existing_type=sa.String(10),
        type_=sa.String(4),
        existing_nullable=False,
    )
