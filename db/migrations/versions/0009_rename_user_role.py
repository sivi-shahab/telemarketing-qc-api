"""rename the 'user' role to 'sales_agent'

Renames the existing user role value ``user`` to ``sales_agent`` (displayed as
"Sales Agent"). Idempotent on fresh databases where 0001 already seeds the new
default.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'sales_agent' WHERE role = 'user'"))
    conn.execute(
        sa.text("UPDATE results SET uploaded_by_role = 'sales_agent' WHERE uploaded_by_role = 'user'")
    )
    conn.execute(
        sa.text(
            "UPDATE qc_status_requests SET requested_by_role = 'sales_agent' "
            "WHERE requested_by_role = 'user'"
        )
    )
    # Column default follows the new role name for fresh inserts.
    op.alter_column("users", "role", server_default="sales_agent")


def downgrade() -> None:
    conn = op.get_bind()
    op.alter_column("users", "role", server_default="user")
    conn.execute(sa.text("UPDATE users SET role = 'user' WHERE role = 'sales_agent'"))
    conn.execute(
        sa.text("UPDATE results SET uploaded_by_role = 'user' WHERE uploaded_by_role = 'sales_agent'")
    )
    conn.execute(
        sa.text(
            "UPDATE qc_status_requests SET requested_by_role = 'user' "
            "WHERE requested_by_role = 'sales_agent'"
        )
    )
