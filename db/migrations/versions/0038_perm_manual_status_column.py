"""Capability baru: kolom "Manual Status" di halaman Results

Sampai sekarang kolom Manual Status tampil untuk SEMUA role, termasuk divisi sales
(Telesales Head, Area Manager, Team Leader Sales, Sales Agent/TLO). Bagi mereka
kolom itu justru membingungkan: vonis human adalah urusan QC, dan yang mereka
butuhkan hanya AI Status (permintaan 10 Agustus 2026).

Karena itu dipisah jadi ``results.manual_status.column`` — MELIHAT kolomnya, bukan
mengubahnya (``results.manual_status.set`` tetap terpisah) — dan hanya diberikan ke
sisi QC + administrasi: ``spq_head``, ``admin``, ``team_leader_qc``, ``qc``,
``qc_support``, dan ``demo`` (showcase yang meniru tampilan SPQ).

Kalau suatu saat salah satu role sales perlu melihatnya lagi, cukup dicentang lewat
menu Manage Role — tidak perlu ganti kode.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0035) agar role yang sudah
disesuaikan operator tidak ikut ditimpa.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.manual_status.column"
_ROLES = ("spq_head", "admin", "team_leader_qc", "qc", "qc_support", "demo")


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
