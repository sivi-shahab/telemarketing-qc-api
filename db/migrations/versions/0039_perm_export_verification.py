"""Capability baru: export XLSX agregat per kategori verifikasi

Menu Results kini punya satu tarikan LINTAS TIKET: pilih kategori (Verifikasi
Statik, Verifikasi Dinamik, Cashline Verification, Cardholder Verification) lalu
unduh semua baris verifikasi yang tidak cocok dari tiket Not Qualified & Pending
(permintaan 10 Agustus 2026).

Berbeda dengan tombol Export XLSX per baris (yang mengikuti kepemilikan detail
evaluasi), tarikan ini melintasi seluruh tiket sekaligus, jadi diberi capability
sendiri — ``results.export.verification`` — dan hanya untuk ``spq_head`` & ``admin``.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0035) agar role yang sudah
disesuaikan operator tidak ikut ditimpa.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.export.verification"
_ROLES = ("spq_head", "admin")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text)))"
        ),
        {"perm": _PERM},
    )
