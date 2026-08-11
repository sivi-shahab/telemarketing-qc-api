"""documents table (Upload Document + OCR-via-LLM per result)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-21 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("object_path", sa.String(500)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ocr_json", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("ix_documents_result_id", "documents", ["result_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_result_id", table_name="documents")
    op.drop_table("documents")
