"""Cabut capability ``stats.manual_status`` — bloknya sudah tidak ada

Diperkenalkan beberapa jam sebelumnya (0036) untuk membatasi blok "Manual Status
(penilaian Human)" di tab Overview ke SPQ Head & Admin. Sesudah aturan AI Status
mengikuti Manual Status yang disetujui (7 Agustus 2026), kedua grafik itu menampilkan
angka yang persis sama — jadi bloknya dihapus seluruhnya dan tab Overview kembali
memuat SATU grafik.

Capability-nya ikut dicabut supaya tidak tersisa checkbox di menu Manage Role yang
tidak menggerakkan apa pun — itu jebakan: orang mencentangnya lalu bertanya-tanya
kenapa tidak ada yang berubah.

Tidak ada ``upgrade`` yang perlu dibalik secara bermakna: ``downgrade`` mengembalikan
capability-nya ke SPQ Head & Admin (sama seperti 0036), berguna kalau bloknya suatu
saat dihidupkan lagi.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "stats.manual_status"
_ROLES = ("spq_head", "admin")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )
