"""Kunci role sisi sales ke campaign cashline (mempertahankan perilaku lama)

Sebelum capability layer, cakupan sisi sales diambil lewat ``_cashline_agent_ids_by``
yang mengunci ``DEDICATED == "cashline"``. Setelah filter itu diparameterkan, role
tanpa baris ``role_campaigns`` berarti SEMUA campaign — dan itu diam-diam MELEBARKAN
akses: Area Manager 23122301 melompat dari 28 menjadi 73 agent karena roster memuat
NTB/LOC/RETENTION/REINSTATE/ACTIVATION/MEGAPAY.

Karena itu ketiga role sales dikunci eksplisit ke ``cashline`` supaya sama persis
dengan perilaku sebelum migrasi. Operator bisa melepas/menambah campaign-nya lewat
menu Manage Role.

Yang TIDAK dikunci, dan alasannya:

* ``qc`` / ``team_leader_qc`` / ``qc_support`` — cakupannya dari ASSIGNMENT tiket,
  bukan campaign. QC memang boleh di-assign tiket campaign mana pun.
* ``telesales_head`` — sebelumnya termasuk role "unscoped" yang melihat SEMUA
  hasil lintas campaign; mengunci ke cashline justru akan mempersempitnya.
* ``spq_head`` / ``admin`` / ``demo`` — memang melihat seluruh sistem.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SALES_ROLES = ("area_manager", "team_leader", "sales_agent")
_CAMPAIGN = "cashline"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO role_campaigns (role_id, campaign) "
            "SELECT id, :campaign FROM roles WHERE key = ANY(:keys) "
            "ON CONFLICT (role_id, campaign) DO NOTHING"
        ),
        {"campaign": _CAMPAIGN, "keys": list(_SALES_ROLES)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM role_campaigns WHERE campaign = :campaign AND role_id IN "
            "(SELECT id FROM roles WHERE key = ANY(:keys))"
        ),
        {"campaign": _CAMPAIGN, "keys": list(_SALES_ROLES)},
    )
