"""Capability baru: tabel perbandingan OCR dokumen (View Document)

Modal "View Document" menampilkan DUA hal: dokumen pendukungnya
(KTP/NPWP/KK/cover buku tabungan) dan tabel perbandingan hasil OCR-nya terhadap
acuan TMS/Ascend. Sampai sekarang keduanya menempel pada satu capability
(``results.document.view``), sehingga semua role yang boleh membuka dokumen ikut
membaca vonis cocok/tidaknya.

Tabel perbandingan itu adalah penilaian QC, bukan dokumen. Karena itu dipisah jadi
``results.document.verification`` dan hanya diberikan ke divisi QC:
QC, Team Leader QC, dan SPQ Head.

Role lain yang punya ``results.document.view`` (``admin``, ``qc_support``,
``telesales_head``, ``area_manager``, ``team_leader``, ``sales_agent``, ``demo``)
tetap bisa MEMBUKA dokumennya, tanpa tabel perbandingan. Kalau salah satunya
ternyata perlu, cukup dicentang lewat menu Manage Role — tidak perlu ganti kode.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0032) agar role yang sudah
disesuaikan operator tidak ikut ditimpa.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.document.verification"
_ROLES = ("qc", "team_leader_qc", "spq_head")


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
