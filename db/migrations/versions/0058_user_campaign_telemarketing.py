"""Tag campaign user QC: ``Cashline`` -> grup ``Telemarketing``

``Cashline`` adalah config PENILAIAN produk (tabel ``campaigns``), bukan cakupan
orang. QC, Team Leader QC, dan SPQ Head telemarketing mengurus seluruh produk
telemarketing — Cashline, NTB, dan semua produk di tiket App C — jadi tag mereka
di tab Assign Role diganti ke grup ``Telemarketing`` (``api.campaign_groups``),
yang diekspansi saat request menjadi setiap config non-Collection dan dipetakan ke
seluruh baris App C.

Pemicu: sejak load_date 2026-09-17 App C mengisi ``context`` dengan kode campaign,
sehingga tag ``Cashline`` (peta ``Cashline:cashline``) membuang setiap baris —
menu Transkrip dan Assign Ticket kosong bagi 12 login ini (1 SPQ Head, 1 TL QC,
10 QC pada 23 September 2026).

Hanya role sisi QC yang disentuh. Role cakupan sales (``team_leader``,
``area_manager``, ``sales_agent``) memakai tag roster per produk, dan ``admin`` /
``telesales_head`` tidak punya menu Transkrip / Assign Ticket — tag mereka dibiarkan.

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLES = ("spq_head", "team_leader_qc", "qc")


def _retag(old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE user_campaigns uc SET campaign = :new "
            "FROM users u "
            "WHERE uc.user_id = u.id AND u.role = ANY(:roles) AND uc.campaign = :old "
            "AND NOT EXISTS (SELECT 1 FROM user_campaigns x "
            "                WHERE x.user_id = uc.user_id AND x.campaign = :new)"
        ),
        {"old": old, "new": new, "roles": list(_ROLES)},
    )


def upgrade() -> None:
    _retag("Cashline", "Telemarketing")


def downgrade() -> None:
    _retag("Telemarketing", "Cashline")
