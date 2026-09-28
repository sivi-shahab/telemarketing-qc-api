"""Capability Generate PPT Error Rate Update: tambahkan ke Team Leader QC

Menyusul migrasi 0061 (spq_head, admin, demo), TL QC sekarang juga bisa
men-generate deck "Error Rate Update" — lihat
``api/permissions.py::STATS_EXPORT_ERROR_RATE_PPT``.

Diterapkan lewat pembaruan JSONB (pola sama dengan 0059/0061) agar role yang
sudah disesuaikan operator tidak ikut tertimpa.

Nomor di repo 4-service: 0061 (dinomori ulang).

Revision ID: 0062
Revises: 0061
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "stats.export.error_rate_ppt"
_ROLES = ("team_leader_qc",)


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
