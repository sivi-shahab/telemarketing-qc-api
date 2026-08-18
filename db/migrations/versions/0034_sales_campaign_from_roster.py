"""Campaign sisi sales diambil dari tag roster, bukan dari role

Migrasi `0033` mengunci `area_manager` / `team_leader` / `sales_agent` ke campaign
`cashline` demi mempertahankan perilaku lama. Pengecekan roster kemudian menunjukkan
penguncian itu tidak diperlukan sekaligus salah untuk satu level:

* dari 377 agent dan 15 team leader, TIDAK ADA satu pun yang lintas campaign — NIP
  mereka di kolom ``Dedicated`` sudah menentukan campaign-nya, sehingga pembatasan
  lewat role hanyalah salinan kedua yang bisa berbeda sendiri;
* 4 dari 5 area manager JUSTRU lintas campaign (satu memegang lima), sehingga
  mengunci mereka ke `cashline` menyembunyikan sebagian area yang benar-benar
  mereka pegang.

Karena itu ketiga baris `role_campaigns` tersebut dihapus. Setelah ini campaign sisi
sales datang dari ``sales_lookup.roster_campaigns_for`` lewat
``api.rbac.effective_campaigns_for``; campaign pada role tetap dihormati sebagai
BATAS ATAS bila operator sengaja mengisinya (mis. role bespoke ``tl_ntb``).

Sekalian menambahkan ``results.filter.qc_side`` untuk ``team_leader_qc``, menggantikan
pengecekan ``role == "team_leader_qc"`` yang masih tersisa di
``api/routers/stats.py`` saat menentukan dropdown filter sisi QC.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SALES_ROLES = ("area_manager", "team_leader", "sales_agent")
_CAMPAIGN = "cashline"
_PERM = "results.filter.qc_side"
_PERM_ROLES = ("team_leader_qc",)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM role_campaigns WHERE campaign = :campaign AND role_id IN "
            "(SELECT id FROM roles WHERE key = ANY(:keys))"
        ),
        {"campaign": _CAMPAIGN, "keys": list(_SALES_ROLES)},
    )
    # jsonb_exists() + CAST(... AS text): operator "?" ditafsirkan sebagai placeholder
    # parameter dan "::" memutus pembacaan nama parameter — sama seperti di 0032.
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_PERM_ROLES)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO role_campaigns (role_id, campaign) "
            "SELECT id, :campaign FROM roles WHERE key = ANY(:keys) "
            "ON CONFLICT (role_id, campaign) DO NOTHING"
        ),
        {"campaign": _CAMPAIGN, "keys": list(_SALES_ROLES)},
    )
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text)))"
        ),
        {"perm": _PERM},
    )
