"""results.current_stage — live pipeline-stage progress for QC while processing

Permintaan 14 September 2026: saat status masih pending/processing, dashboard
hanya menampilkan "Status: processing — hasil belum tersedia" tanpa rincian,
padahal worker sudah punya checkpoint per tahap (unduh_pdf, baca_teks_pdf,
klasifikasi_llm, rangkai_transkrip, campaign_dan_acuan, penilaian_llm,
gabung_dan_skor, simpan_hasil, tandai_selesai — lihat _Tahap di
worker/tasks/process_transcript.py). Kolom ini menyimpan checkpoint TERAKHIR
yang selesai dijalankan, ditulis live (commit langsung) tiap kali tahap itu
selesai, supaya API bisa menyusun tabel progres saat tiket masih diproses.

NULL sebelum checkpoint pertama selesai (hasil lama pun otomatis NULL — tidak
butuh backfill, tampilan lama "processing" tanpa rincian tetap berfungsi).

DINOMORI 0053, BUKAN 0052. Di repo monolit 4-service-telemarketing-qc-system
migrasi ini bernomor 0052, tetapi nomor itu di sini sudah dipakai
``0052_perm_tl_qc_upload_sales_database``. Keduanya sama-sama ``down_revision
= "0051"``, jadi memakai nomor asalnya akan membuat dua kepala revisi dan
``alembic upgrade head`` gagal.

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column("current_stage", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "current_stage")
