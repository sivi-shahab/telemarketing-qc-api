"""rename the 'admin' role to 'spq_head'

Renames the existing user role value ``admin`` to ``spq_head`` (displayed as
"SPQ Head"). Idempotent on fresh databases where 0001 already seeds the new
value.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'spq_head' WHERE role = 'admin'"))
    conn.execute(
        sa.text("UPDATE results SET uploaded_by_role = 'spq_head' WHERE uploaded_by_role = 'admin'")
    )
    conn.execute(
        sa.text(
            "UPDATE qc_status_requests SET requested_by_role = 'spq_head' "
            "WHERE requested_by_role = 'admin'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'admin' WHERE role = 'spq_head'"))
    conn.execute(
        sa.text("UPDATE results SET uploaded_by_role = 'admin' WHERE uploaded_by_role = 'spq_head'")
    )
    conn.execute(
        sa.text(
            "UPDATE qc_status_requests SET requested_by_role = 'admin' "
            "WHERE requested_by_role = 'spq_head'"
        )
    )
