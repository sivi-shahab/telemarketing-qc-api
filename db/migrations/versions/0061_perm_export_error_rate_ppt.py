"""Capability baru: Generate PPT Error Rate Update

Menu baru di halaman Stats yang men-generate deck "Error Rate Update" (.pptx)
dari data agregat yang sudah ada (Error Rate per Campaign/Area Manager/
SPV/Top TLO, Detail Error Reason). Beberapa bagian PPT acuan (Submission/
Sampling volume asli, %KPI, section Complaint) tidak ada datanya di sistem ini
dan tampil sebagai placeholder di hasil unduhan — lihat
``api/permissions.py::STATS_EXPORT_ERROR_RATE_PPT``.

Diberikan ke ``spq_head``, ``admin``, dan ``demo`` (dua terakhir lewat
``_ADMIN_PERMISSIONS``, sama seperti seluruh capability Stats lain).
Diterapkan lewat pembaruan JSONB (pola sama dengan 0057/0059) agar role yang sudah
disesuaikan operator tidak ikut tertimpa.

Nomor di repo 4-service: 0060 (dinomori ulang — prod 0060 = timestamp_simpan_utc).

Revision ID: 0061
Revises: 0060
Create Date: 2026-09-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "stats.export.error_rate_ppt"
_ROLES = ("spq_head", "admin", "demo")


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
