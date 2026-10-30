"""Akses Upload Audio / Upload Transcript per user

Permintaan 30 Oktober 2026: Admin bisa mengaktifkan/menonaktifkan Upload Audio dan
Upload Transcript per user di Manage User, untuk semua user kecuali role ``admin``.

Dua kolom nullable di ``users``. NULL = ikut role, jadi tanpa backfill pun
default-nya sama persis dengan sekarang (mis. Team Leader QC tetap aktif keduanya,
QC tetap nonaktif). Nilai True/False hanya terisi setelah Admin menekan saklarnya.

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("upload_audio_enabled", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("upload_transcript_enabled", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "upload_transcript_enabled")
    op.drop_column("users", "upload_audio_enabled")
