"""Capability baru: blok Manual Status di tab Overview

Tab Overview menampilkan DUA blok yang sejajar: "AI Status" (vonis mesin) dan
"Manual Status (penilaian Human)" beserta grafiknya. Yang kedua sebenarnya bahan
evaluasi divisi QC itu sendiri — berapa banyak keputusan AI yang dikoreksi manusia,
dan oleh siapa — bukan gambaran mutu panggilan.

Dipisah jadi ``stats.manual_status`` dan hanya diberikan ke **SPQ Head** dan
**Admin**. Role lain (termasuk QC dan Team Leader QC) tetap melihat seluruh blok AI
Status; hanya blok Manual Status + grafiknya yang hilang.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0032 & 0035) agar role yang
sudah disesuaikan operator lewat Manage Role tidak ikut ditimpa.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "stats.manual_status"
_ROLES = ("spq_head", "admin")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            # jsonb_exists() alih-alih operator "?" dan CAST(... AS text) alih-alih
            # "::text": tanda tanya ditafsirkan sebagai placeholder parameter, dan
            # "::" memutus pembacaan nama parameter ":perm". (Lihat 0032.)
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text)))"
        ),
        {"perm": _PERM},
    )
