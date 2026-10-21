"""Hitung ulang snapshot Statistics SEGERA setelah vonis/dokumen berubah (21 Oktober 2026).

Kasus 0704449OzZ: TL QC meng-approve Manual Status PASS pukul 15.01.13 WIB, tetapi
snapshot Statistics baru menyusul 15.03.39. Snapshot ter-cache hanya dihitung ulang
oleh jadwal beat tiap 2 menit (yang antre di belakang evaluasi LLM) atau saat
seseorang membuka halaman — dan pembuka pertama tetap menerima angka lama.

Hook di sesi DB API: commit yang menyentuh Manual Status, banding error code, atau
dokumen pendukung mengirim ``refresh_stats_snapshot`` ke antrean ``stats``, yang
dikerjakan worker khusus (service ``worker-stats`` di compose repo worker) sehingga
evaluasi LLM tidak bisa menahannya. Satu kunci Redis per jendela ``DEBOUNCE_SEC``
menggabungkan rentetan klik menjadi satu hitung ulang; task-nya baru jalan setelah
jendela itu lewat, jadi perubahan di dalamnya ikut terhitung.

Hanya snapshot GLOBAL yang dihitung ulang di sini; snapshot ter-scope (AM/TL/QC,
filter tanggal, grafik per waktu) tetap dihitung ulang saat dibuka, karena kuncinya
bergantung pada parameter pemakainya.
"""
import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from db.models import Document, ErrorCodeAppeal, QcStatusRequest
from services import redis_cache

logger = logging.getLogger(__name__)

TASK_NAME = "worker.tasks.maintenance.refresh_stats_snapshot"
QUEUE = "stats"
DEBOUNCE_SEC = 5
# Pesan yang tidak sempat diambil (worker-stats mati) dibuang; jadwal beat menutupnya.
EXPIRES_SEC = 120
_LOCK_KEY = "lock:stats-refresh-request"
_FLAG = "stats_refresh_pending"
_TRACKED = (QcStatusRequest, ErrorCodeAppeal, Document)


def _send_task(name, **kw):
    from api.celery_client import celery_app

    celery_app.send_task(name, **kw)


def request_stats_refresh() -> None:
    """Kirim satu permintaan hitung ulang per jendela debounce. Tidak pernah melempar:
    broker yang bermasalah tidak boleh menggagalkan keputusan QC yang sudah tersimpan."""
    try:
        if not redis_cache.acquire(_LOCK_KEY, ttl_sec=DEBOUNCE_SEC):
            return
        # retry=False: broker mati -> gagal seketika, bukan menahan respons API.
        _send_task(TASK_NAME, queue=QUEUE, countdown=DEBOUNCE_SEC, expires=EXPIRES_SEC,
                   retry=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stats] permintaan hitung ulang Statistics gagal dikirim: %s", exc)


def _after_flush(session, flush_context) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, _TRACKED):
            session.info[_FLAG] = True
            return


def _after_commit(session) -> None:
    if session.info.pop(_FLAG, False):
        request_stats_refresh()


def _after_rollback(session) -> None:
    session.info.pop(_FLAG, None)


def install(session_cls=Session) -> None:
    """Pasang hook sekali per kelas sesi (idempoten)."""
    for name, fn in (("after_flush", _after_flush), ("after_commit", _after_commit),
                     ("after_rollback", _after_rollback)):
        if not event.contains(session_cls, name, fn):
            event.listen(session_cls, name, fn)
