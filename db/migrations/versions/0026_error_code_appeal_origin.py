"""error_code_appeals.origin (qc vs tl_direct vs spq_direct)

Distinguishes HOW a banding entered the system. Default 'qc' is a QC-submitted
appeal that flows through the tiered review (QC -> Team Leader QC -> [SPQ Head]).
A 'tl_direct' / 'spq_direct' row is a DIRECT edit made by Team Leader QC / SPQ
Head respectively: it is created already finalized (tl_qc_status='approved'), so
it applies immediately without any approval hierarchy. Default 'qc' keeps every
existing row behaving as before.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "error_code_appeals",
        sa.Column("origin", sa.String(20), nullable=False, server_default="qc"),
    )


def downgrade() -> None:
    op.drop_column("error_code_appeals", "origin")
