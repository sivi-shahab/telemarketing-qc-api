"""Menu "Reprocess All Ticket" — tabel job + capability Admin

Permintaan 20 Agustus 2026. Submenu baru di grup **Upload Data** (khusus Admin):
pilih satu atau beberapa campaign lewat checkbox, lalu SETIAP unique ticket id di
campaign itu diproses ulang memakai konfigurasi campaign yang berlaku sekarang
(prompt/scorecard/KB terbaru di tabel ``campaigns``). Begitu satu tiket selesai
dengan status ``done``, seluruh row LAMA milik ticket id itu dihapus sehingga
tersisa tepat satu row per unique id.

Dua tabel baru:

* ``reprocess_jobs`` — satu baris per perintah (campaign apa, siapa, kapan).
* ``reprocess_job_items`` — satu baris per unique ticket id, memegang
  ``old_result_ids`` yang dibekukan saat perintah diberikan. Pembekuan itu yang
  membuat penghapusan aman: hanya row yang sudah ada saat itu yang boleh dihapus,
  jadi upload baru yang masuk di tengah job (webhook, Upload Transcript) tidak ikut
  terhapus hanya karena ticket id-nya sama.

Capability-nya dua, sengaja dipisah: ``menu.reprocess_tickets`` (melihat menunya)
dan ``admin.ticket.reprocess`` (menjalankannya). Keduanya masuk
``ADMIN_ONLY_PERMISSIONS``, jadi sama seperti seluruh menu Upload Data lainnya ia
tidak bisa diberikan ke role buatan operator lewat Manage Role.

``downgrade`` membuang kedua tabel dan mencabut kedua capability dari role mana pun.

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = ("menu.reprocess_tickets", "admin.ticket.reprocess")
_ROLES = ("admin",)


def upgrade() -> None:
    op.create_table(
        "reprocess_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("campaigns", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("total_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_username", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_table(
        "reprocess_job_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reprocess_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("ticket_id", sa.String(length=100), nullable=False),
        sa.Column("campaign", sa.String(length=100)),
        sa.Column("old_result_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_result_id", postgresql.UUID(as_uuid=True)),
        sa.Column("new_result_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("deleted_old", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("idx_reprocess_items_job", "reprocess_job_items", ["job_id"])
    op.create_index("idx_reprocess_items_ticket", "reprocess_job_items", ["ticket_id"])

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
    conn = op.get_bind()
    for perm in _PERMS:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = "
                "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
                " FROM jsonb_array_elements(permissions) v WHERE v <> to_jsonb(CAST(:perm AS text)))"
            ),
            {"perm": perm},
        )
    op.drop_index("idx_reprocess_items_ticket", table_name="reprocess_job_items")
    op.drop_index("idx_reprocess_items_job", table_name="reprocess_job_items")
    op.drop_table("reprocess_job_items")
    op.drop_table("reprocess_jobs")
