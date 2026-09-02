"""Tombol Reprocess per tiket di menu Results — kolom ``reprocess_jobs.scope``

Permintaan 21 Agustus 2026. Menu Results mendapat tombol **Reprocess** yang bekerja
untuk SATU ticket id saja: tiket itu dievaluasi ulang memakai konfigurasi campaign
yang berlaku sekarang, lalu seluruh row LAMA-nya dihapus sehingga tersisa tepat satu
row — persis semantik menu "Reprocess All Ticket", hanya cakupannya satu tiket.

Mesinnya dipakai ulang seutuhnya (``reprocess_jobs`` + ``reprocess_job_items`` +
task Celery ``reprocess_ticket``), jadi jaminan yang sama tetap berlaku: row lama
hanya dihapus setelah row barunya ``done``, dan yang dihapus persis id yang dibekukan
saat tombol ditekan.

Yang baru hanya satu kolom penanda:

* ``reprocess_jobs.scope`` — ``campaign`` (job massal dari menu Reprocess All Ticket)
  atau ``ticket`` (satu tiket dari tombol di Results). Penanda ini yang membuat layar
  "Reprocess All Ticket" tidak ikut menempel pada job satu-tiket milik orang lain,
  sementara pengaman "satu job massal pada satu waktu" tetap melihat keduanya.

Baris lama otomatis bernilai ``campaign`` lewat ``server_default``. Tidak ada
capability baru: tombolnya memakai ``admin.ticket.reprocess`` yang sudah ada.

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reprocess_jobs",
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="campaign"),
    )


def downgrade() -> None:
    op.drop_column("reprocess_jobs", "scope")
