"""Card Holder (B17) appeal fields: qc_reference_value + qc_extracted_value

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # QC-submitted corrected values for Card Holder Verification (B17) appeals.
    # Nullable — existing scorecard (SC_CL_*) appeals leave these empty.
    op.add_column("error_code_appeals", sa.Column("qc_reference_value", sa.Text))
    op.add_column("error_code_appeals", sa.Column("qc_extracted_value", sa.Text))


def downgrade() -> None:
    op.drop_column("error_code_appeals", "qc_extracted_value")
    op.drop_column("error_code_appeals", "qc_reference_value")
