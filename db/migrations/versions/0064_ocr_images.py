"""Tabel ocr_images + menu OCR Gambar untuk Admin/Demo

Alat OCR mandiri (1 Oktober 2026): gambar yang di-upload disalin teksnya oleh
worker (``worker.tasks.process_ocr_image``) dan disimpan sebagai riwayat.

``menu.ocr_image`` ditambahkan ke role ``admin`` dan ``demo`` lewat pembaruan
JSONB (pola 0063) agar role yang sudah disesuaikan operator tidak tertimpa. User
non-admin mendapatkannya saat request lewat ``OCR_IMAGE_CAMPAIGNS``, bukan di sini.

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "menu.ocr_image"
_ROLES = ("admin", "demo")


def upgrade() -> None:
    op.create_table(
        "ocr_images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("text", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("token_usage", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("idx_ocr_images_user_created", "ocr_images", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_ocr_images_batch", "ocr_images", ["batch_id"])
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
            " FROM jsonb_array_elements(permissions) v "
            " WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = ANY(:keys)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )
    op.drop_index("idx_ocr_images_batch")
    op.drop_index("idx_ocr_images_user_created")
    op.drop_table("ocr_images")
