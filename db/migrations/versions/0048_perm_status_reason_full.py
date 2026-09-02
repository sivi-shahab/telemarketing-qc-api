"""Capability baru: keterangan lengkap di kolom AI Status

Kolom AI Status membawa keterangan kecil di bawah badge-nya. Isinya bercampur dua
hal yang audiensnya berbeda:

* ``Menunggu dokumen <jenis>`` (dan varian ``(SLA H+2)``) — pekerjaan yang memang
  bisa ditindaklanjuti sisi sales: berkasnya tinggal diunggah;
* ``Transkrip/Data TMS/Agent/Data Ascend Kosong`` — kekurangan data operasional,
  bukan kinerja agent, dan ``Error non-tolerable`` / ``Terindikasi Badword`` —
  vonis QC, sejalan dengan Critical Failure(s) yang juga tidak dibuka ke sisi sales.

Sejak 28 Agustus 2026 kelompok kedua dipisah ke ``results.status_reason_full`` dan
hanya diberikan ke divisi QC + Admin: QC, Team Leader QC, QC Support, SPQ Head,
admin, demo. Empat role sisi sales (Sales Agent, Team Leader, Area Manager,
Telesales Head) tetap melihat keterangan "Menunggu dokumen ...".

Penyaringannya di BACKEND (``api/routers/stats.py``), jadi keterangan yang
disembunyikan tidak ikut terkirim ke browser — bukan sekadar tidak digambar.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0032 & 0035) agar role
yang sudah disesuaikan operator tidak ikut ditimpa.

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.status_reason_full"
_ROLES = ("qc", "team_leader_qc", "qc_support", "spq_head", "admin", "demo")


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
        )
    )
