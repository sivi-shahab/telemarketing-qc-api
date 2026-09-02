"""Menu Assign Ticket / Manual Check / Pending Check dikembalikan ke SPQ Head

Permintaan 2 September 2026 — membatalkan 0050 yang sehari sebelumnya mencabut
``menu.assign_ticket``, ``menu.manual_check``, dan ``menu.pending_check`` dari
SPQ Head. Ketiga antrean kerja QC itu diminta kembali terlihat: membagi tiket ke
QC lewat Assign Ticket, dan dua antrean tiket yang menunggu review lewat Manual
Check & Pending Check.

Pola yang sama dengan 0036 → 0037: perubahan dibatalkan lewat revisi maju, bukan
dengan menghapus 0050, supaya riwayat migrasi tetap lurus di semua environment
yang terlanjur menjalankan 0050.

Yang tidak berubah dari 0050: ``qc.assignment.write`` memang tidak pernah ikut
dicabut, jadi begitu menu Assign Ticket muncul lagi, endpoint ``/qc_assignment``
langsung punya permukaan lagi tanpa migrasi tambahan. ``menu.results`` dan
wewenang memutus banding (``manual_status.review.spq`` / ``error_code.review.spq``)
juga tidak pernah tersentuh.

Penjaga rutenya digerakkan capability (``dashboard/src/router`` membaca
``ROUTE_PERMISSIONS``), jadi mengembalikan ketiga izin ini sekaligus membuka
kembali akses lewat URL langsung maupun tautan di sidebar. Tidak ada perubahan
kode dashboard yang dibutuhkan.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0051"
down_revision: Union[str, None] = "0050"
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
    # Ditambahkan satu per satu supaya izin yang sudah ada tidak jadi duplikat
    # (pola downgrade 0050).
    for perm in _PERMS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = :role AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "role": _ROLE},
        )


def downgrade() -> None:
    conn = op.get_bind()
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
