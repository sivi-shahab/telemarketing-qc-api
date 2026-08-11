"""initial schema (transcript QA)

Revision ID: 0001
Revises:
Create Date: 2026-06-08 00:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from passlib.context import CryptContext

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade() -> None:
    # ------------------------------------------------------------------ users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="sales_agent"),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )

    # -------------------------------------------------------------- campaigns
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("scorecard_text", sa.Text, nullable=False),
        sa.Column("kb_text", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_campaigns_name", "campaigns", ["name"])

    # ---------------------------------------------------------------- results
    op.create_table(
        "results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("campaign", sa.String(100)),
        sa.Column("passing_grade", sa.Float),
        sa.Column("source_files", postgresql.JSONB),
        sa.Column("num_calls", sa.Integer),
        sa.Column("transcript_path", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
        sa.Column("result_path", sa.String(500)),
        sa.Column("uploaded_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("processing_sec", sa.Float),
    )
    op.create_index("idx_results_status", "results", ["status"])
    op.create_index("idx_results_campaign", "results", ["campaign"])
    op.create_index(
        "idx_results_uploaded",
        "results",
        ["uploaded_at"],
        postgresql_ops={"uploaded_at": "DESC"},
    )

    # ------------------------------------------------------------ result_data
    op.create_table(
        "result_data",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
        ),
        sa.Column("result_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_result_data_result_id", "result_data", ["result_id"])

    # ------------------------------------------------------ seed SPQ Head user
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
    admin_email = os.environ.get("ADMIN_EMAIL", f"{admin_username}@bank.local")

    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT id FROM users WHERE username = :u"),
        {"u": admin_username},
    ).fetchone()

    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO users (username, email, hashed_password, role, is_active) "
                "VALUES (:u, :e, :p, 'spq_head', true)"
            ),
            {"u": admin_username, "e": admin_email, "p": _pwd.hash(admin_password)},
        )


def downgrade() -> None:
    op.drop_index("idx_result_data_result_id")
    op.drop_table("result_data")
    op.drop_index("idx_results_uploaded")
    op.drop_index("idx_results_campaign")
    op.drop_index("idx_results_status")
    op.drop_table("results")
    op.drop_index("idx_campaigns_name")
    op.drop_table("campaigns")
    op.drop_table("users")
