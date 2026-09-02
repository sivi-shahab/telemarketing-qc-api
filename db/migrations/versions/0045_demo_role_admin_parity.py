"""Role ``demo`` disetarakan dengan ``admin`` + masuk PROTECTED_ROLES

Permintaan 27 Agustus 2026: akun demo harus bisa melakukan apa pun yang bisa
dilakukan Admin — upload campaign, upload audio/transkrip, kelola user & role,
sampai hapus campaign — supaya demo end-to-end tidak lagi menuntut akun Admin
terpisah (lihat migrasi 0041 yang dulu memindahkan semuanya ke ``admin``).

Yang dilakukan: ``roles.permissions`` milik ``demo`` diisi dengan SALINAN PERSIS
milik ``admin``. Disalin dari baris ``admin`` yang ada di DB, bukan dari daftar
literal, supaya "sama dengan Admin" tetap benar walau baris Admin sempat disunting
lewat Manage Role. Kalau baris ``admin`` tidak ada (DB belum ter-seed), dipakai
snapshot literal di bawah — cermin ``_ADMIN_PERMISSIONS`` per 27 Agustus 2026.

Sisi kode yang menyertainya, TIDAK bisa dilakukan migrasi:

* ``api.permissions.ADMIN_LIKE_ROLES`` kini memuat ``demo``. Tanpa itu
  ``api/routers/role.py`` menolak menyimpan capability admin-only pada ``demo``,
  dan menyimpan role demo lewat Manage Role akan mencabut semuanya kembali.
* ``api.permissions.PROTECTED_ROLES`` kini memuat ``demo``: tidak bisa dihapus dan
  tidak bisa kehilangan ``admin.role.write``.

Konsekuensi yang disengaja: akun demo tidak lagi aman dipinjamkan ke orang luar —
ia bisa menghapus campaign dan mengubah role. ``downgrade`` mengembalikan izin demo
ke daftar read-only per sebelum migrasi ini.

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Cermin `api.permissions._ADMIN_PERMISSIONS` per 27 Agustus 2026. Hanya dipakai
# kalau baris `admin` tidak ada di DB.
_ADMIN_SNAPSHOT = [
    "menu.stats", "menu.results", "menu.transcripts", "menu.assign_ticket",
    "menu.manual_check", "menu.pending_check", "menu.campaigns",
    "menu.sales_database", "menu.qc_database", "menu.upload_campaign",
    "menu.upload_audio", "menu.upload_transcript", "menu.get_result",
    "menu.upload_sales_database", "menu.upload_qc_database",
    "menu.reprocess_tickets",
    "menu.delete_campaign", "menu.manage_user", "menu.manage_role",
    "menu.role_hierarchy",
    "results.evaluation_detail", "results.critical_failure",
    "results.category_score", "results.manual_status.column",
    "results.document.upload", "results.document.view",
    "results.export.verification", "results.export.tickets",
    "stats.failure_reason", "stats.qc_performance", "stats.risk_base",
    "stats.risk_system_new",
    "admin.user.write", "admin.role.write", "admin.campaign.write",
    "admin.sales_database.write", "admin.qc_database.write",
    "admin.ticket.delete", "admin.ticket.reprocess",
    "qc.assignment.write", "transcript.upload", "audio.upload",
]

# Izin demo SEBELUM migrasi ini (read-only showcase), dipakai downgrade.
_DEMO_BEFORE = [
    "menu.stats", "menu.results",
    "results.evaluation_detail", "results.critical_failure",
    "results.category_score", "results.document.view",
    "stats.risk_base", "stats.risk_system_new",
    "results.manual_status.column",
]

_SET_SQL = sa.text(
    "UPDATE roles SET permissions = CAST(:perms AS jsonb) WHERE key = 'demo'"
)


def _set_demo(conn, perms) -> None:
    import json

    conn.execute(_SET_SQL, {"perms": json.dumps(perms)})


def upgrade() -> None:
    conn = op.get_bind()
    admin = conn.execute(
        sa.text("SELECT permissions FROM roles WHERE key = 'admin'")
    ).scalar()
    _set_demo(conn, admin if admin else _ADMIN_SNAPSHOT)
    # Cakupan data demo memang sudah `all`, sama dengan Admin — ditegaskan agar
    # kesetaraannya utuh walau baris demo pernah disunting.
    conn.execute(sa.text("UPDATE roles SET data_scope = 'all' WHERE key = 'demo'"))
    # Batas campaign per role: Admin tidak dibatasi, jadi demo pun tidak.
    conn.execute(
        sa.text(
            "DELETE FROM role_campaigns WHERE role_id = "
            "(SELECT id FROM roles WHERE key = 'demo')"
        )
    )


def downgrade() -> None:
    _set_demo(op.get_bind(), _DEMO_BEFORE)
