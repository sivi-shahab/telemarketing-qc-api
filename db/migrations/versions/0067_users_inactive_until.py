"""users.inactive_until — nonaktif QC dari Kelola QC hanya sampai 00.00 WIB

Team Leader QC yang menonaktifkan QC Telemarketing lewat Kelola QC kini hanya
berlaku sampai 00.00 WIB berikutnya; lewat dari itu QC aktif kembali
(``crud.reactivate_expired_qc_users``, dijalankan beat worker dan saat login).
Nonaktif oleh Admin (Manage User) tetap permanen — kolomnya NULL.

Kolom nullable tanpa default, jadi user yang sekarang nonaktif tetap nonaktif
permanen.

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("inactive_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "inactive_until")
