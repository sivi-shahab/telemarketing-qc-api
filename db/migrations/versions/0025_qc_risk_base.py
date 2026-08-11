"""editable risk base override on error-code appeals (qc_risk_base)

Lets QC edit the Risk Base in the Manual Check / Add Error Code forms instead of
always inheriting the master-catalog default. Stored per appeal; when set it wins
over the catalog value in the built Error Code table (add + change bandings).
Nullable — empty means "use the catalog default for the error code".

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("error_code_appeals", sa.Column("qc_risk_base", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("error_code_appeals", "qc_risk_base")
