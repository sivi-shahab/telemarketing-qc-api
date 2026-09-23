"""Upload Audio & Upload Transcript untuk SPQ Head dan Team Leader QC

Permintaan 23 September 2026: menu Upload Audio dan Upload Transcript perlu
tersedia juga bagi **SPQ Head** dan **Team Leader QC**.

Ini MEMBALIK sebagian keputusan 14 Agustus 2026 (migrasi 0041), yang menjadikan
seluruh Upload Data milik Admin. Empat capability dikembalikan ke kedua role itu:
``menu.upload_audio``, ``menu.upload_transcript``, ``audio.upload`` dan
``transcript.upload``. Di kode, keempatnya ikut dikeluarkan dari
``api.permissions.ADMIN_ONLY_PERMISSIONS`` — tanpa itu Manage Role akan diam-diam
mencabutnya lagi saat role disimpan ulang (form tidak mengirim capability
admin-only dan hanya role admin-like yang membawanya dari DB).

Menu Upload lainnya (Upload Campaign, Get Result, Database Sales/QC, Reprocess)
tetap milik Admin. ``qc_support`` TIDAK disentuh — tidak diminta.

Ditambahkan lewat pembaruan JSONB (pola yang sama dengan 0057) agar role yang sudah
disesuaikan operator tidak ikut ditimpa. ``downgrade`` mencabutnya dari KEDUA role
itu saja — ``admin``/``demo`` tidak disentuh.

Revision ID: 0059
Revises: 0058
Create Date: 2026-09-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = (
    "menu.upload_audio",
    "menu.upload_transcript",
    "audio.upload",
    "transcript.upload",
)
_ROLES = ("spq_head", "team_leader_qc")


def upgrade() -> None:
    conn = op.get_bind()
    for perm in _PERMS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
                "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
            ),
            {"perm": perm, "keys": list(_ROLES)},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE NOT (v IN (SELECT to_jsonb(x) FROM unnest(CAST(:perms AS text[])) x))) "
            "WHERE key = ANY(:keys)"
        ),
        {"perms": list(_PERMS), "keys": list(_ROLES)},
    )
