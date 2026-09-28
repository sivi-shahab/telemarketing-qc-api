"""Result yang tertahan ``processing`` selamanya harus ditutup jadi ``failed``.

Kasus 28 September 2026: 56 result Cashline tertahan ``processing`` di halaman
Results. Worker yang mengambilnya berhenti sesudah ``unduh_pdf``/``cek_nama_agent``
tanpa sempat menjalankan ``except`` di ``process_transcript`` (proses mati, bukan
exception), jadi tidak ada yang pernah menulis ``failed``. Tanpa pembersih, baris
seperti itu tampil "sedang diproses" untuk selamanya.

``crud.fail_stale_processing_results`` menutup baris ``processing`` yang
``started_at``-nya lebih tua dari ``STALE_PROCESSING_AFTER``. ``started_at`` ditulis
worker dalam UTC naive, jadi "sekarang" diberikan dari Python, bukan ``now()`` DB
(zona DB = WIB).

Semua baris test memakai tahun 2000 dan ``now`` di tahun 2000 juga, supaya baris
sungguhan di DB (tahun 2026, selalu lebih baru dari batasnya) tidak pernah ikut
tersentuh walau test ini jalan terhadap DB produksi. Transaksi selalu di-rollback.
"""
import uuid
from datetime import datetime, timedelta

NOW = datetime(2000, 1, 1, 12, 0, 0)


def _result(db, status, started_at, stage="unduh_pdf"):
    from db.models import Result

    row = Result(id=uuid.uuid4(), campaign="Cashline", status=status,
                 started_at=started_at, current_stage=stage)
    db.add(row)
    db.flush()
    return row


def test_processing_basi_ditutup_jadi_failed_dengan_tahap_terakhir(db):
    from db import crud

    old = _result(db, "processing", NOW - crud.STALE_PROCESSING_AFTER - timedelta(minutes=1))

    closed = crud.fail_stale_processing_results(db, now=NOW)

    db.refresh(old)
    assert str(old.id) in closed
    assert old.status == "failed"
    assert "unduh_pdf" in old.error_message
    assert old.completed_at is None


def test_processing_yang_masih_dalam_batas_waktu_tidak_disentuh(db):
    from db import crud

    fresh = _result(db, "processing", NOW - crud.STALE_PROCESSING_AFTER + timedelta(minutes=1))

    closed = crud.fail_stale_processing_results(db, now=NOW)

    db.refresh(fresh)
    assert str(fresh.id) not in closed
    assert fresh.status == "processing"
    assert fresh.error_message is None


def test_status_lain_dan_started_at_kosong_tidak_disentuh(db):
    from db import crud

    long_ago = NOW - timedelta(days=1)
    done = _result(db, "done", long_ago)
    pending = _result(db, "pending", long_ago)
    no_start = _result(db, "processing", None)

    closed = crud.fail_stale_processing_results(db, now=NOW)

    for row in (done, pending, no_start):
        db.refresh(row)
        assert str(row.id) not in closed
    assert (done.status, pending.status, no_start.status) == ("done", "pending", "processing")
