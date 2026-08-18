"""Dua capability yang terlewat di seed 0031

`0031` menurunkan capability dari gate yang ada, tapi dua gate belum punya
padanannya sehingga akan jatuh ke "tidak ada yang boleh":

* ``DELETE /delete_ticket`` (api/routers/stats.py) — dulu ``get_spq_head_user``.
* ``POST /qc_manual_check/{result_id}`` (api/routers/qc_manual_check.py) — dulu
  ``get_qc_user``, khusus role ``qc`` dan terpisah dari Manual Status.

Ditambahkan lewat pembaruan JSONB agar role yang sudah disesuaikan operator
(mis. permission-nya sudah diubah lewat Manage Role) tidak ikut ditimpa.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRANTS = {
    "admin.ticket.delete": ("spq_head", "admin"),
    "results.manual_check.approve": ("qc",),
}


def upgrade() -> None:
    conn = op.get_bind()
    for perm, role_keys in _GRANTS.items():
        conn.execute(
            sa.text(
                # jsonb_exists() alih-alih operator "?" dan CAST(... AS text)
                # alih-alih "::text": tanda tanya ditafsirkan sebagai placeholder
                # parameter, dan "::" memutus pembacaan nama parameter ":perm".
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "keys": list(role_keys)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for perm in _GRANTS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = "
                "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
                " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text)))"
            ),
            {"perm": perm},
        )
