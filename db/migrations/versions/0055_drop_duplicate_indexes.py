"""Drop duplicate indexes: campaigns.name, qc_assignments.ticket_id

Port dari monolit 0057 (17 September 2026, improvement.md item 1.6), DIPANGKAS:
monolit 0055 (``ix_results_status`` / ``ix_result_data_result_id``) TIDAK diport
karena keduanya duplikat ``idx_results_status`` / ``idx_result_data_result_id`` yang
sudah ada sejak 0001 — monolit sendiri membatalkannya di 0057. Yang tersisa:

- ``idx_campaigns_name`` duplikat unique constraint ``campaigns_name_key``.
- ``ix_qc_assignments_ticket_id`` duplikat unique constraint
  ``qc_assignments_ticket_id_key``.

Diverifikasi di produksi (schema ``dashboard``, 21 September 2026): keempat index
dan kedua constraint pengganti ada. Tabelnya kecil (2 dan ~900 baris) jadi DROP
INDEX biasa (ACCESS EXCLUSIVE sesaat) aman.

Revision ID: 0055  (monolit 0057, dipangkas)
Revises: 0054
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_campaigns_name")
    op.execute("DROP INDEX IF EXISTS ix_qc_assignments_ticket_id")


def downgrade() -> None:
    op.create_index("ix_qc_assignments_ticket_id", "qc_assignments", ["ticket_id"])
    op.create_index("idx_campaigns_name", "campaigns", ["name"])
