"""sales_databases table (Upload Database Sales — Sales Agent)

Stores one row per uploaded sales-database XLSX. Only the newest upload is
active; ``crud.create_sales_database`` flips previous rows to inactive.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_databases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("uploaded_by_username", sa.String(100)),
        sa.Column("uploaded_by_role", sa.String(20)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_sales_databases_is_active", "sales_databases", ["is_active"]
    )


def downgrade() -> None:
    op.drop_index("idx_sales_databases_is_active")
    op.drop_table("sales_databases")
