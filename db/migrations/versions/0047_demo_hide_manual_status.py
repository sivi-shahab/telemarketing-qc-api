"""Role ``demo``: kolom Manual Status dilepas

Permintaan 27 Agustus 2026. ``results.manual_status.column`` dicabut dari ``demo``,
sehingga kolom Manual Status DAN dropdown filternya (keduanya memakai gate yang sama
di ``ResultsView.vue``) hilang dari layar demo.

Bukan pencabutan kewenangan: demo tidak pernah punya ``results.manual_status.set``
— sama seperti Admin — jadi yang berubah hanya apa yang terlihat, bukan apa yang
bisa dilakukan. Ini pembeda KEDUA antara izin demo dan admin, setelah
``results.layout.demo`` (migrasi 0046); lihat migrasi 0045 yang menyetarakan
keduanya.

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.manual_status.column"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = 'demo'"
        ),
        {"perm": _PERM},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = 'demo' AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM},
    )
