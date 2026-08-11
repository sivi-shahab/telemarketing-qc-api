"""Celery client sisi API — hanya untuk mengirim task, bukan menjalankannya.

API tidak pernah mengeksekusi task; ia cuma memanggil
``celery_app.send_task("<nama task>", args=[...])``. Mengirim task by name tidak
butuh kode worker sama sekali, cukup broker URL — jadi API tidak perlu (dan tidak
boleh) meng-import ``worker.celery_app``, yang setelah pemisahan repo memang tidak
ada di image API.

Konfigurasi serialisasi & timezone disamakan dengan ``worker/celery_app.py``
supaya pesan yang dikirim dari sini identik dengan yang dikirim worker.
"""
from celery import Celery

from api.dependencies import get_settings

_settings = get_settings()

celery_app = Celery(
    "bank_qa",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jakarta",
    enable_utc=True,
)
