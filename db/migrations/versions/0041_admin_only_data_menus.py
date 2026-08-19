"""Pengurusan data pindah ke Admin + dokumen ditutup dari Sales Agent

Permintaan 14 Agustus 2026, tiga pencabutan yang berdiri sendiri.

1. **Seluruh pengurusan data hanya milik ``admin``.** Campaigns, Database Sales,
   Database QC, semua menu Upload Data, dan Delete Campaign — beserta capability
   tulisnya — dicabut dari SETIAP role selain ``admin``. Daftarnya cermin dari
   ``api.permissions.ADMIN_ONLY_PERMISSIONS``; sejak sekarang capability itu juga
   tidak bisa diberikan lagi lewat Manage Role, jadi migrasi ini adalah satu-satunya
   pintu masuknya.

   Yang paling terasa: ``qc_support`` kehilangan Upload Audio & Upload Transcript.
   Karena cakupan datanya "hanya tiket yang di-upload sendiri", role itu tidak akan
   punya tiket baru sama sekali. Ini disengaja dan sudah dikonfirmasi — bukan efek
   samping yang terlewat.

2. **SPQ Head kehilangan ``admin.ticket.delete`` dan
   ``results.export.verification``.** Tombol Delete dan Export Agregat di halaman
   Results memang ditujukan pindah ke Admin. Sebagai gantinya SPQ Head (dan Admin)
   mendapat ``results.export.tickets`` — export SEMUA tiket pada rentang tanggal
   yang sedang dipilih.

3. **Sales Agent kehilangan ``results.document.view``.** Sales agent tidak lagi
   bisa membuka dokumen pendukung. Atasannya tidak disentuh.

``downgrade`` mengembalikan ketiganya persis ke keadaan sebelum migrasi ini.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Cermin ADMIN_ONLY_PERMISSIONS. Ditulis literal (bukan di-import dari api/) supaya
# migrasi ini tetap menggambarkan keadaan 14 Agustus 2026 walau daftar di kode
# berubah kemudian — itulah gunanya migrasi.
_ADMIN_ONLY = (
    "menu.campaigns",
    "menu.sales_database",
    "menu.qc_database",
    "menu.upload_campaign",
    "menu.upload_audio",
    "menu.upload_transcript",
    "menu.get_result",
    "menu.upload_sales_database",
    "menu.upload_qc_database",
    "menu.delete_campaign",
    "menu.manage_user",
    "menu.manage_role",
    "admin.user.write",
    "admin.role.write",
    "admin.campaign.write",
    "admin.sales_database.write",
    "admin.qc_database.write",
    "transcript.upload",
    "audio.upload",
)

# Dicabut hanya dari SPQ Head.
_SPQ_REVOKE = ("admin.ticket.delete", "results.export.verification")
_EXPORT_TICKETS = "results.export.tickets"

# Keadaan sebelum migrasi, dipakai downgrade. role key -> capability yang dulu dimiliki.
_RESTORE = {
    "spq_head": (
        "menu.campaigns", "menu.sales_database", "menu.qc_database",
        "menu.upload_campaign", "menu.upload_audio", "menu.upload_transcript",
        "menu.get_result", "menu.upload_sales_database", "menu.upload_qc_database",
        "menu.delete_campaign", "admin.campaign.write",
        "admin.sales_database.write", "admin.qc_database.write",
        "transcript.upload", "audio.upload",
        "admin.ticket.delete", "results.export.verification",
    ),
    "team_leader_qc": (
        "menu.upload_audio", "menu.upload_transcript",
        "transcript.upload", "audio.upload",
    ),
    "qc_support": (
        "menu.upload_audio", "menu.upload_transcript",
        "transcript.upload", "audio.upload",
    ),
    "demo": ("menu.campaigns", "menu.upload_transcript", "transcript.upload"),
    "sales_agent": ("results.document.view",),
}

_REVOKE_SQL = sa.text(
    "UPDATE roles SET permissions = "
    "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
    " FROM jsonb_array_elements(permissions) v "
    " WHERE NOT (v IN (SELECT to_jsonb(x) FROM unnest(CAST(:perms AS text[])) x))) "
    "WHERE key <> ALL(CAST(:except_keys AS text[]))"
)

_GRANT_SQL = sa.text(
    "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
    "WHERE key = :role AND NOT jsonb_exists(permissions, :perm)"
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Pengurusan data: cabut dari semua role KECUALI admin.
    conn.execute(_REVOKE_SQL, {"perms": list(_ADMIN_ONLY), "except_keys": ["admin"]})

    # 2. SPQ Head: cabut Delete & Export Agregat, beri Export Tiket.
    #    `key <> ALL(...)` dengan daftar "semua role selain spq_head" tidak praktis,
    #    jadi dipakai bentuk yang sama tetapi dibatasi lewat WHERE tambahan.
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE NOT (v IN (SELECT to_jsonb(x) FROM unnest(CAST(:perms AS text[])) x))) "
            "WHERE key = :role"
        ),
        {"perms": list(_SPQ_REVOKE), "role": "spq_head"},
    )
    for role in ("spq_head", "admin"):
        conn.execute(_GRANT_SQL, {"perm": _EXPORT_TICKETS, "role": role})

    # 3. Sales Agent: cabut hak melihat dokumen.
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = :role"
        ),
        {"perm": "results.document.view", "role": "sales_agent"},
    )


def downgrade() -> None:
    conn = op.get_bind()
    for role in ("spq_head", "admin"):
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = "
                "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
                " FROM jsonb_array_elements(permissions) v "
                " WHERE v <> to_jsonb(CAST(:perm AS text))) "
                "WHERE key = :role"
            ),
            {"perm": _EXPORT_TICKETS, "role": role},
        )
    for role, perms in _RESTORE.items():
        for perm in perms:
            conn.execute(_GRANT_SQL, {"perm": perm, "role": role})
