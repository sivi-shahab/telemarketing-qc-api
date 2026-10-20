"""Edit User: users.left_qc_at, riwayat user_change_events, permission qc.user.edit

Fitur Edit User (Admin dan Team Leader QC) mengubah NIP, nama, email, role, dan
kata sandi user. Tiga perubahan skema:

- ``users.left_qc_at`` — kapan user keluar dari role QC Telemarketing (ganti role),
  dipakai untuk membagi ulang tiket hari itu yang belum dikerjakan. Nullable tanpa
  default: user yang ada tidak punya waktu keluar.
- ``user_change_events`` — riwayat APPEND-ONLY, satu baris per field yang berubah.
  Sengaja tanpa FK ke ``users`` (pola sama dengan ``qc_assignment_events``); nilai
  lama/baru kata sandi selalu NULL.
- Permission ``qc.user.edit`` untuk ``team_leader_qc`` lewat pembaruan JSONB (pola
  sama dengan 0066) agar role yang sudah disesuaikan operator tidak ikut tertimpa.

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0070"
down_revision: Union[str, None] = "0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "qc.user.edit"
_ROLES = ("team_leader_qc",)


def upgrade() -> None:
    op.add_column("users", sa.Column("left_qc_at", sa.DateTime(), nullable=True))

    op.create_table(
        "user_change_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("target_username", sa.String(100)),
        sa.Column("field", sa.String(20), nullable=False),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("actor_user_id", sa.Integer),
        sa.Column("actor_username", sa.String(100)),
        sa.Column("actor_role", sa.String(50)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_user_change_events_user_id", "user_change_events", ["user_id"])
    op.create_index("ix_user_change_events_target_username", "user_change_events", ["target_username"])
    op.create_index("ix_user_change_events_created_at", "user_change_events", ["created_at"])

    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = ANY(:keys)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )
    op.drop_index("ix_user_change_events_created_at", table_name="user_change_events")
    op.drop_index("ix_user_change_events_target_username", table_name="user_change_events")
    op.drop_index("ix_user_change_events_user_id", table_name="user_change_events")
    op.drop_table("user_change_events")
    op.drop_column("users", "left_qc_at")
