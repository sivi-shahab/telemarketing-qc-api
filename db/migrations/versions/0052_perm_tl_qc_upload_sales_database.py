"""Menu Upload Database Sales dibuka untuk Team Leader QC

Sebelumnya hanya ``admin`` yang memegang dua capability ini, jadi Team Leader QC
tidak melihat menunya sama sekali.

DUA capability, bukan satu — dan keduanya wajib:

  * ``menu.upload_sales_database`` menampilkan menunya di sidebar dan membuka
    route ``/upload/sales-database`` di dashboard (keduanya dibaca dari
    permissions.js, jadi tidak perlu build ulang dashboard).
  * ``admin.sales_database.write`` adalah gate di ``api/routers/sales_database.py``,
    yang dipasang di level ROUTER (``APIRouter(dependencies=[...])``) sehingga
    berlaku untuk semua endpoint-nya: upload, list, maupun roster.

Kalau hanya yang pertama diberikan, menunya muncul tapi setiap permintaan dibalas
403 — persis jenis kegagalan yang menyesatkan operator.

``menu.sales_database`` (menu "Database Sales" untuk melihat isinya) SENGAJA tidak
ikut: yang diminta adalah fitur unggahnya. Kalau nanti perlu, cukup dicentang lewat
menu Manage Role tanpa mengubah kode.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0032, 0035, 0048, 0049)
agar role yang sudah disesuaikan operator tidak ikut ditimpa.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = ("menu.upload_sales_database", "admin.sales_database.write")
_ROLES = ("team_leader_qc",)


def upgrade() -> None:
    conn = op.get_bind()
    for perm in _PERMS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "keys": list(_ROLES)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for perm in _PERMS:
        # Dibatasi ke _ROLES: role lain (mis. admin) memang berhak atas capability
        # yang sama sejak seed 0031 dan tidak boleh ikut kehilangan.
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = "
                "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
                " FROM jsonb_array_elements(permissions) v "
                " WHERE v <> to_jsonb(CAST(:perm AS text))) "
                "WHERE key = ANY(:keys)"
            ),
            {"perm": perm, "keys": list(_ROLES)},
        )
