"""users.deactivated_at — kapan QC dinonaktifkan, untuk bagi ulang tiketnya

Batch auto assign terjadwal membagi ulang tiket yang di-assign HARI INI ke QC yang
dinonaktifkan hari ini (Kelola QC maupun Admin) dan belum dikerjakan, di slot
berikutnya sesudah QC itu nonaktif (``qc_auto_assign.reassign_from_inactive``).
Untuk itu waktu nonaktifnya perlu dicatat.

Kolom nullable tanpa default: user yang sekarang nonaktif tidak punya waktu nonaktif,
jadi tiketnya tidak tersentuh aturan baru ini.

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "deactivated_at")
