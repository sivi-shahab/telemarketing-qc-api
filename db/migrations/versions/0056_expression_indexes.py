"""Expression indexes on results: split_part(source_files->>0,'_',1) (+ lower())

Port dari monolit 0058 (improvement.md item 3.1), DIPANGKAS: index ekspresi
``tms_cashline`` / ``ascend_custp`` tidak diport — di sini kedua tabel itu legacy
dan kosong (reference data dibaca dari DWH API), jadi index-nya tidak pernah
dipakai. Ekspresi ``split_part(Result.source_files[0].astext, '_', 1)`` dipakai
luas di ``db/crud.py`` (filter ticket-scope, hidden tickets, cashline_agent_index).

Tanpa CONCURRENTLY: ``results`` ~261 baris saat ini, CREATE INDEX selesai instan.
Bila tabel sudah besar saat dijalankan, ganti ke CREATE INDEX CONCURRENTLY di
dalam ``op.get_context().autocommit_block()``.

Revision ID: 0056  (monolit 0058, dipangkas)
Revises: 0055
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_results_ticket_id_expr ON results "
        "(split_part(source_files ->> 0, '_', 1))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_results_ticket_id_expr_lower ON results "
        "(lower(split_part(source_files ->> 0, '_', 1)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_results_ticket_id_expr_lower")
    op.execute("DROP INDEX IF EXISTS ix_results_ticket_id_expr")
