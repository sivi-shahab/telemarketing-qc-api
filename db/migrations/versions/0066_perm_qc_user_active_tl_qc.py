"""Capability Kelola QC: aktifkan/nonaktifkan QC Telemarketing untuk Team Leader QC

Team Leader QC kini bisa mengaktifkan/menonaktifkan akun QC Telemarketing sendiri
(keluar-masuk pool pembagian tiket) tanpa bisa membuat, menghapus, atau mengubah
role user — lihat ``api/permissions.py::QC_USER_ACTIVE_WRITE``. Login Collection
tidak mendapatkannya (``COLLECTION_REMOVED_PERMISSIONS``).

Diterapkan lewat pembaruan JSONB (pola sama dengan 0062) agar role yang sudah
disesuaikan operator tidak ikut tertimpa.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "qc.user.active.write"
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
