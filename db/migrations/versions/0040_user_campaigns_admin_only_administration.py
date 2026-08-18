"""Tabel ``user_campaigns`` + menu Administration khusus Admin

Dua perubahan, keduanya permintaan 10 Agustus 2026.

1. **Tab "Assign Role"** (menu Manage Role) menugaskan SATU USERNAME ke campaign
   tertentu. Sebelumnya campaign hanya bisa dibatasi per ROLE (``role_campaigns``)
   atau — untuk sisi sales — lewat kolom Dedicated di Sales Database, sehingga
   membatasi satu orang saja menuntut pembuatan role bespoke. Tabel ``user_campaigns``
   mengisi celah itu: tidak ada baris = tidak dibatasi di tingkat orang; ada baris =
   batas ATAS tambahan yang di-IRIS dengan batas role & roster (lihat
   ``api.rbac.effective_campaigns_for``), jadi tidak pernah memperlebar akses.

2. **Menu Administration (Manage User & Manage Role) hanya untuk Admin.** SPQ Head
   kehilangan ``menu.manage_user``, ``menu.manage_role``, ``admin.user.write``, dan
   ``admin.role.write`` — pengelolaan user & role adalah pekerjaan Admin (mengurus
   sistem), bukan SPQ Head (memutus perkara QC). Capability QC milik SPQ Head tidak
   disentuh sama sekali.

   Peringatan operasional: sesudah ini HANYA role ``admin`` yang bisa mengelola role.
   Pastikan minimal satu akun Admin yang aktif dan diketahui password-nya sebelum
   naik ke produksi; ``downgrade`` mengembalikan keempat capability itu.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = (
    "menu.manage_user",
    "menu.manage_role",
    "admin.user.write",
    "admin.role.write",
)
_ROLE = "spq_head"


def upgrade() -> None:
    op.create_table(
        "user_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("campaign", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_campaigns_user_id", "user_campaigns", ["user_id"])

    conn = op.get_bind()
    # Cabut keempat capability dari spq_head dalam satu pembaruan JSONB (pola 0037).
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
    op.drop_index("ix_user_campaigns_user_id", table_name="user_campaigns")
    op.drop_table("user_campaigns")
