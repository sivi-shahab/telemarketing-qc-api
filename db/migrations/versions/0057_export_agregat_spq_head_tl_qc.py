"""Export Agregat kembali untuk SPQ Head + baru untuk Team Leader QC

Permintaan 21 September 2026: menu Export Agregat di halaman Results
(``results.export.verification``) perlu tersedia juga bagi **SPQ Head** dan
**Team Leader QC**.

Ini MEMBALIK sebagian keputusan 14 Agustus 2026 (migrasi 0041), yang mencabut
capability itu dari SPQ Head dan menggantinya dengan ``results.export.tickets``.
Pengganti itu TIDAK dicabut — SPQ Head kini memegang keduanya: Export Tiket (tarikan
periode, satu baris per tiket) dan Export Agregat (tarikan temuan, satu kategori).
Sejak 21 September 2026 Export Agregat juga punya kategori per fase percakapan
(``conversation_phases`` KB), yang membuatnya berguna bagi pengawas QC.

Hanya ``results.export.verification`` yang diberikan. Team Leader QC TIDAK ikut
mendapat ``results.export.tickets`` — itu tidak diminta.

Cakupan datanya tidak berubah: keduanya ``SCOPE_ALL`` dan export tetap dibatasi
campaign role (``effective_campaigns_for``), jadi tidak ada penyempitan per-tiket yang
terlewat. Satu catatan: agregat export tidak menerapkan isolasi tiket QC Support
(disembunyikan dari role lain di tabel Results), sama seperti tab Statistics yang sudah
dipakai SPQ Head; saat ini tidak ada tiket QC Support di data (0 dari 54).

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0039) agar role yang sudah
disesuaikan operator tidak ikut ditimpa. ``downgrade`` mencabutnya dari KEDUA role itu
saja — ``admin``/``demo`` tidak disentuh.

Revision ID: 0057  (monolit 0059)
Revises: 0056
Create Date: 2026-09-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.export.verification"
_ROLES = ("spq_head", "team_leader_qc")


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = ANY(:keys)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )
