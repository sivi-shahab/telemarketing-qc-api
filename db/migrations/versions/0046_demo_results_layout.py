"""Tata letak kolom Results versi Demo: capability ``results.layout.demo``

Permintaan 27 Agustus 2026. Role ``demo`` memakai susunan kolom sendiri di menu
Results — ID, Call Duration (satu butir per PDF), Campaign Interest, SCOREBOMB,
Grade, AI Status, Manual Status, Document, Action. Number of Calls dan Export per
baris dilepas; "Critical Failure(s)" dijuduli SCOREBOMB; "Passing Grade" (persen)
diganti "Grade" = nilai akhir / passing grade.

Dibuat sebagai CAPABILITY, bukan perbandingan nama role di Vue: halaman Results
sudah sepenuhnya digerakkan capability sejak migrasi 0031, dan dengan begini tata
letaknya bisa dipindah ke role lain lewat Manage Role tanpa menyentuh kode.

Ini SATU-SATUNYA hal yang membedakan izin ``demo`` dari ``admin`` (lihat migrasi
0045 yang menyetarakan keduanya) — dan yang dibedakan hanyalah penyajian, bukan
data atau aksi: setiap kolomnya tetap tunduk pada capability-nya masing-masing.

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "results.layout.demo"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = 'demo' AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE v <> to_jsonb(CAST(:perm AS text)))"
        ),
        {"perm": _PERM},
    )
