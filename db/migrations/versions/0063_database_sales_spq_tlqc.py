"""Fitur Database Sales (lihat & unggah) untuk SPQ Head dan Team Leader QC

Sebelumnya menu "Database Sales" (``menu.sales_database``) hanya milik Admin, dan
SPQ Head juga tidak memegang Upload Database Sales. TL QC sudah memegang dua
capability unggah sejak migrasi 0052, jadi baginya yang bertambah hanya menu lihat.

Ketiga capability dibutuhkan:

  * ``menu.sales_database`` — menu & route ``/dashboard/sales-database``.
  * ``menu.upload_sales_database`` — menu & route ``/upload/sales-database``.
  * ``admin.sales_database.write`` — gate level ROUTER di
    ``api/routers/sales_database.py``; halaman lihat pun memanggil
    ``/list_sales_databases`` dan ``/sales_database/roster`` di baliknya.

Login yang HANYA memegang campaign Collection tidak mendapatkannya: ketiganya ada
di ``COLLECTION_REMOVED_PERMISSIONS`` (dihitung saat request, bukan di sini).

Ditambahkan lewat pembaruan JSONB (pola sama dengan 0052/0059/0062) agar role
yang sudah disesuaikan operator tidak ikut tertimpa.

Revision ID: 0063
Revises: 0062
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Capability -> role yang menerimanya DI MIGRASI INI. Upload untuk TL QC tidak
# dicantumkan: sudah diberikan 0052 dan downgrade ini tidak boleh mencabutnya.
_GRANTS = {
    "menu.sales_database": ("spq_head", "team_leader_qc"),
    "menu.upload_sales_database": ("spq_head",),
    "admin.sales_database.write": ("spq_head",),
}


def upgrade() -> None:
    conn = op.get_bind()
    for perm, roles in _GRANTS.items():
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "keys": list(roles)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for perm, roles in _GRANTS.items():
        # Dibatasi ke role di _GRANTS: admin/demo memegang capability yang sama
        # sejak seed 0031 dan tidak boleh ikut kehilangan.
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = "
                "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
                " FROM jsonb_array_elements(permissions) v "
                " WHERE v <> to_jsonb(CAST(:perm AS text))) "
                "WHERE key = ANY(:keys)"
            ),
            {"perm": perm, "keys": list(roles)},
        )
