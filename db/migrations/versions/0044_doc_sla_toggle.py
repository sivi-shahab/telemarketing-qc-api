"""Sakelar kebijakan SLA H+2 di menu Results (khusus role ``admin``)

Permintaan 24 Agustus 2026. Tenggat H+2 (48 jam sejak ``tms_cashline.submit_time``)
yang menentukan kapan tiket kekurangan dokumen berpindah dari ``PENDING`` ke ``FAIL``
sebelumnya adalah KONSTANTA di kode (``compliance.stats_aggregate.DOC_SLA_ENABLED``).
Mematikannya untuk keperluan uji berarti mengedit file lalu me-restart container —
tidak bisa dilakukan operator, dan tidak terlihat sama sekali di layar.

Dua hal yang ditambahkan:

* Tabel ``app_settings`` — penyimpanan key/value sederhana untuk kebijakan tingkat
  aplikasi yang boleh diubah saat berjalan. Baris pertamanya ``doc_sla_enabled``.
  Sengaja generik supaya sakelar berikutnya tidak perlu tabel baru lagi.
* Capability ``admin.doc_sla.write`` — hanya role ``admin`` yang boleh MENGUBAH
  sakelarnya. MEMBACA statusnya tidak butuh capability apa pun: indikator kebijakan
  tampil untuk semua orang yang bisa membuka menu Results, karena status PENDING/FAIL
  yang mereka lihat memang bergantung padanya.

CATATAN PENTING — sakelar ini dibaca saat MEMBACA data, bukan saat evaluasi. Jadi
mengubahnya langsung menilai ulang SELURUH tiket yang ada (tiket kekurangan dokumen
yang tenggatnya sudah lewat berpindah FAIL <-> PENDING seketika). Itu memang perilaku
konstanta lama; yang berubah hanya cara mengubahnya.

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "admin.doc_sla.write"


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_by_username", sa.String(100)),
    )
    # Nilai awal = perilaku lama (aturan H+2 AKTIF), supaya upgrade tidak diam-diam
    # mengubah status tiket mana pun.
    op.execute(
        "INSERT INTO app_settings (key, value) VALUES ('doc_sla_enabled', 'true')"
        " ON CONFLICT (key) DO NOTHING"
    )
    # Capability baru untuk role admin. ``roles.permissions`` adalah JSONB array.
    op.execute(
        f"""
        UPDATE roles
           SET permissions = permissions || '["{_PERM}"]'::jsonb
         WHERE key = 'admin'
           AND NOT (permissions @> '["{_PERM}"]'::jsonb)
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE roles
           SET permissions = permissions - '{_PERM}'
         WHERE permissions @> '["{_PERM}"]'::jsonb
        """
    )
    op.drop_table("app_settings")
