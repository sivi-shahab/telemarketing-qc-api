"""Kolom default DB yang terisi WIB digeser ke UTC (simpan UTC, tampilkan WIB)

Konvensi aplikasi: timestamp disimpan UTC naive. Worker menulis ``_utcnow()``,
core mengonversi ``uploaded_at`` UTC->WIB untuk batas hari/bulan, dashboard menambah
``'Z'`` lalu merender Asia/Jakarta. Postgres produksi memakai ``TimeZone =
Asia/Jakarta``, sehingga semua ``server_default=func.now()`` menulis **WIB**:
``uploaded_at`` terkonversi dua kali (upload sesudah 17:00 WIB masuk hari berikutnya)
dan tampil 7 jam maju (28 September 2026).

Mulai revisi ini sesi api/worker dipaksa ``timezone=UTC`` (``api.dependencies`` dan
``worker.config``). Migrasi ini menggeser −7 jam nilai LAMA yang terbukti WIB:

- ``results.uploaded_at``, ``result_data.created_at``, ``documents.created_at``,
  ``reprocess_jobs.created_at``, ``qc_status_events``/``qc_manual_checks``/
  ``qc_databases``/``sales_databases``/``roles``.``created_at``,
  ``campaigns.created_at``/``updated_at``: hanya pernah diisi default DB. Terverifikasi:
  ``result_data.created_at − results.completed_at`` bermedian tepat +7 jam.
- ``results.started_at``/``completed_at`` baris jalur salin (``crud`` lama menulis
  ``func.now()`` ke keduanya, jadi ``started_at = completed_at``). Baris hasil worker
  sudah UTC dan tidak disentuh.
- ``reprocess_jobs.finished_at`` hanya yang ``>= created_at``. Versi lama menulis WIB,
  kode sekarang ``datetime.now()`` = UTC di container (selalu < ``created_at`` WIB).
  Id yang digeser dicatat di ``_tz0060_job_finished_wib`` supaya downgrade tepat.
- ``users.created_at`` hanya akun yang dibuat sesudah DB ini diinisialisasi
  (``roles.created_at`` = 2026-09-03 13:52:19 WIB). Akun hasil impor monolit membawa
  nilai UTC dari Postgres monolit.

TIDAK disentuh: ``qc_assignments.assigned_at`` (selalu ``utcnow`` eksplisit),
``stats_snapshots.computed_at`` (tak pernah dibaca), ``app_settings.updated_at``
(satu baris, asal tidak bisa dipastikan), ``qc_status_requests``/``error_code_appeals``
(kosong saat migrasi).

Pengaman: data hanya digeser bila zona sesi alembic (= bawaan server, ``env.py`` tidak
mengaturnya) berselisih +7 jam dari UTC. DB ber-TimeZone UTC (stack e2e) dilewati.

Revision ID: 0060
Revises: 0059
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIB_OFFSET_SEC = 7 * 3600
_DB_INIT_WIB = "2026-09-03 13:52:19"   # roles.created_at produksi (WIB)
_JOBS = "_tz0060_job_finished_wib"

_DEFAULT_ONLY = [
    ("results", "uploaded_at"),
    ("result_data", "created_at"),
    ("documents", "created_at"),
    ("qc_status_events", "created_at"),
    ("qc_manual_checks", "created_at"),
    ("qc_databases", "created_at"),
    ("sales_databases", "created_at"),
    ("roles", "created_at"),
    ("campaigns", "created_at"),
    ("campaigns", "updated_at"),
]


def upgrade_statements() -> list:
    """Geser WIB -> UTC. Terpisah dari ``upgrade`` supaya bisa diuji di transaksi."""
    h = "interval '7 hours'"
    return [
        # finished_at dicatat SEBELUM created_at digeser: syaratnya membandingkan
        # dengan created_at yang masih WIB.
        f"CREATE TABLE {_JOBS} AS SELECT id FROM reprocess_jobs "
        f"WHERE finished_at IS NOT NULL AND finished_at >= created_at",
        f"UPDATE reprocess_jobs SET finished_at = finished_at - {h} "
        f"WHERE id IN (SELECT id FROM {_JOBS})",
        f"UPDATE reprocess_jobs SET created_at = created_at - {h}",
        f"UPDATE results SET started_at = started_at - {h}, completed_at = completed_at - {h} "
        f"WHERE started_at = completed_at",
        *[f"UPDATE {t} SET {c} = {c} - {h} WHERE {c} IS NOT NULL" for t, c in _DEFAULT_ONLY],
        f"UPDATE users SET created_at = created_at - {h} "
        f"WHERE created_at >= TIMESTAMP '{_DB_INIT_WIB}'",
    ]


def downgrade_statements() -> list:
    """Kebalikan persis ``upgrade_statements`` (kembali ke nilai WIB)."""
    h = "interval '7 hours'"
    return [
        f"UPDATE users SET created_at = created_at + {h} "
        f"WHERE created_at >= TIMESTAMP '{_DB_INIT_WIB}' - {h}",
        *[f"UPDATE {t} SET {c} = {c} + {h} WHERE {c} IS NOT NULL" for t, c in _DEFAULT_ONLY],
        f"UPDATE results SET started_at = started_at + {h}, completed_at = completed_at + {h} "
        f"WHERE started_at = completed_at",
        f"UPDATE reprocess_jobs SET created_at = created_at + {h}",
        f"UPDATE reprocess_jobs SET finished_at = finished_at + {h} "
        f"WHERE id IN (SELECT id FROM {_JOBS})",
        f"DROP TABLE {_JOBS}",
    ]


def _server_is_wib(bind) -> bool:
    offset = int(bind.execute(sa.text("SELECT extract(timezone FROM now())")).scalar())
    if offset == 0:
        return False
    if offset == _WIB_OFFSET_SEC:
        return True
    raise RuntimeError(f"TimeZone server tak terduga (offset {offset} detik) — "
                       "0060 hanya mengenal UTC atau WIB")


def upgrade() -> None:
    bind = op.get_bind()
    if not _server_is_wib(bind):
        return
    for sql in upgrade_statements():
        op.execute(sql)


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT to_regclass(:t)"), {"t": _JOBS}).scalar()
    if not exists:   # upgrade dilewati (DB UTC) — tidak ada yang perlu dibalik
        return
    for sql in downgrade_statements():
        op.execute(sql)
