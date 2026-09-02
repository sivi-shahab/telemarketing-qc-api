"""Menu Assign Ticket / Manual Check / Pending Check dicabut dari SPQ Head

Permintaan 1 September 2026. SPQ Head kehilangan ``menu.assign_ticket``,
``menu.manual_check``, dan ``menu.pending_check`` — tiga menu ANTREAN KERJA QC
(membagi tiket ke QC, dan dua antrean tiket yang menunggu review). Mengurus
antrean adalah pekerjaan sisi QC (Team Leader QC & QC), bukan SPQ Head.

Yang TIDAK disentuh, dan sengaja:

* ``menu.results`` tetap ada. Halaman di balik Manual Check & Pending Check
  adalah ResultsView yang sama, hanya disaring ke tiket yang menunggu tingkat
  review si pemanggil dan direntang ke seluruh tanggal (Results sendiri
  bertumpu pada tanggal yang sedang dipilih). Jadi SPQ Head tidak kehilangan
  AKSES ke tiketnya — yang hilang hanya jalan pintas berupa antrean siap-saring.
* ``manual_status.review.spq`` & ``error_code.review.spq`` tetap ada, sehingga
  wewenang MEMUTUS banding yang naik ke SPQ Head sama sekali tidak berubah;
  tiketnya dibuka lewat menu Results.
* ``qc.assignment.write`` tetap ada. Permintaannya adalah MENYEMBUNYIKAN menu,
  bukan mencabut wewenang; endpoint ``/qc_assignment`` karena itu dibiarkan.
  Praktisnya capability itu jadi menganggur — satu-satunya permukaannya adalah
  halaman Assign Ticket yang kini tertutup — jadi ia bisa ikut dicabut kapan
  saja tanpa mengubah apa pun yang terlihat.

Penjaga rutenya digerakkan capability (``dashboard/src/router`` membaca
``ROUTE_PERMISSIONS``), jadi mencabut ketiga izin ini sekaligus menutup akses
lewat URL langsung — bukan sekadar menyembunyikan tautannya di sidebar. Tidak
ada perubahan kode dashboard yang dibutuhkan.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = (
    "menu.assign_ticket",
    "menu.manual_check",
    "menu.pending_check",
)
_ROLE = "spq_head"


def upgrade() -> None:
    conn = op.get_bind()
    # Ketiga izin dicabut dalam satu pembaruan JSONB (pola 0037 / 0040).
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE NOT (v IN (SELECT to_jsonb(x) FROM unnest(CAST(:perms AS text[])) x))) "
            "WHERE key = :role"
        ),
        {"perms": list(_PERMS), "role": _ROLE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    for perm in _PERMS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = :role AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "role": _ROLE},
        )
