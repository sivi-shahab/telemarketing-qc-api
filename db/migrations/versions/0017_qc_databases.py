"""qc_databases table (Upload Database QC — SPQ Head / Admin)

Stores one row per uploaded QC-database XLSX. Only the newest upload is active;
``crud.create_qc_database`` flips previous rows to inactive. Mirrors sales_databases.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qc_databases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("uploaded_by_username", sa.String(100)),
        sa.Column("uploaded_by_role", sa.String(20)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_qc_databases_is_active", "qc_databases", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_qc_databases_is_active")
    op.drop_table("qc_databases")
