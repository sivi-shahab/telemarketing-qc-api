"""Tombol Reprocess di menu Results harus TETAP disable setelah refresh.

Bug yang dijaga di sini: ``reprocessActive`` di ``ResultsView.vue`` adalah state
komponen yang hanya diisi oleh ``confirmReprocess()`` — yaitu saat tombolnya
ditekan di sesi itu juga. Refresh halaman atau pindah menu membuang komponennya
(``onBeforeUnmount`` -> ``stopReprocessPolling``), dan pada mount berikutnya peta
itu kosong lagi. Akibatnya tiket yang job-nya masih ``running`` di server kembali
tampil ENABLE; Admin menekannya, dan baru mendapat 409 dari
``api/routers/reprocess.py`` sesudah menekan "Proses Ulang" di modal.

Layar Reprocess massal (``ReprocessTicketsView.vue``) sudah menangani hal yang
sama lewat ``running_job_id`` pada ``/reprocess_preview``; menu Results tidak
pernah mendapat jalur setara. ``/reprocess_jobs`` dan ``/reprocess_preview``
keduanya menyaring ``scope="campaign"``, jadi job satu-tiket memang tidak
terlihat dari mana pun.

Perbaikannya: ``/list_results`` mengirim ``reprocess_active`` per baris, diambil
dari ``crud.active_reprocess_ticket_ids``. Aturan "aktif"-nya harus sama persis
dengan pengaman 409 di ``crud.active_reprocess_item_for_ticket`` — kalau tidak,
tombolnya kembali berbohong: enable padahal server menolak, atau disable padahal
server menerima.

Test DB memakai transaksi yang selalu di-rollback; tidak ada baris yang tertinggal.
"""
import uuid

import pytest

from api.schemas.result import ResultListItem


# --------------------------------------------------------------------------
# Kontrak field (murni, tanpa DB)
# --------------------------------------------------------------------------

def test_result_list_item_punya_field_reprocess_active():
    """Baris Results membawa penanda reproses, default False.

    Default-nya harus False dan bukan None: template menahan tombolnya dengan
    ``:disabled``, dan None di sana membaca sebagai "tidak sibuk" secara diam-diam
    kalau suatu saat backend lupa mengisinya.
    """
    item = ResultListItem(result_id=str(uuid.uuid4()), campaign="Cashline",
                          source_files=["010203aBcD_20260830.pdf"], num_calls=1,
                          status="done", uploaded_at=None, completed_at=None,
                          processing_sec=None)
    assert item.reprocess_active is False


# --------------------------------------------------------------------------
# Aturan "sedang direproses" (butuh DB; dilewati kalau tidak terjangkau)
# --------------------------------------------------------------------------

# Fixture ``db`` (transaksi yang di-rollback) ada di tests/conftest.py — dipakai
# bersama dengan test Reprocess All.


def _job_with_item(db, *, job_status: str, item_status: str, ticket_id: str,
                   scope: str = "ticket"):
    """Satu job + satu item, tersimpan di dalam transaksi test."""
    from qc_core.db.models import ReprocessJob, ReprocessJobItem

    job = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], scope=scope,
                       status=job_status, total_tickets=1,
                       created_by_username="pytest")
    db.add(job)
    db.flush()
    item = ReprocessJobItem(job_id=job.id, ticket_id=ticket_id, campaign="Cashline",
                            old_result_ids=[], status=item_status)
    db.add(item)
    db.flush()
    return job, item


def _tid(suffix: str) -> str:
    """Ticket id unik per test supaya tidak beririsan dengan data nyata."""
    return f"PYTEST{uuid.uuid4().hex[:8]}{suffix}"


def test_item_pending_menandai_tiket_sedang_direproses(db):
    from qc_core.db import crud

    tid = _tid("A")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_item_processing_menandai_tiket_sedang_direproses(db):
    from qc_core.db import crud

    tid = _tid("B")
    _job_with_item(db, job_status="running", item_status="processing", ticket_id=tid)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_item_selesai_tidak_lagi_menahan_tombol(db):
    """Inti bug-nya: tombol harus kembali ENABLE begitu reproses selesai."""
    from qc_core.db import crud

    tid = _tid("C")
    _job_with_item(db, job_status="running", item_status="done", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_item_gagal_tidak_menahan_tombol(db):
    """Item ``failed`` boleh dicoba lagi — row lamanya sengaja dipertahankan."""
    from qc_core.db import crud

    tid = _tid("D")
    _job_with_item(db, job_status="running", item_status="failed", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_job_dibatalkan_tidak_menahan_tombol(db):
    """Sama seperti pengaman 409: item pada job ``cancelled`` tidak akan dikerjakan."""
    from qc_core.db import crud

    tid = _tid("E")
    _job_with_item(db, job_status="cancelled", item_status="pending", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_job_massal_juga_menahan_tombol(db):
    """Job scope ``campaign`` membekukan row tiket ini juga, jadi tombolnya ikut
    ditahan — ``reprocess_single_ticket`` memang menolaknya dengan 409."""
    from qc_core.db import crud

    tid = _tid("F")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid,
                   scope="campaign")
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_hanya_tiket_yang_diminta_yang_dikembalikan(db):
    """Dipanggil per halaman (<= 100 baris), jadi hasilnya harus tersaring —
    bukan seluruh antrean. Saat ini ada ratusan job berjalan sekaligus."""
    from qc_core.db import crud

    diminta, lain = _tid("G"), _tid("H")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=diminta)
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=lain)
    assert crud.active_reprocess_ticket_ids(db, [diminta]) == {diminta}


def test_daftar_tiket_kosong_tidak_menyentuh_db(db):
    """Halaman tanpa baris tidak boleh memicu query apa pun."""
    from qc_core.db import crud

    assert crud.active_reprocess_ticket_ids(db, []) == set()


def test_aturan_sama_dengan_pengaman_409(db):
    """Penanda tombol dan penolakan 409 harus tidak pernah berbeda pendapat.

    ``active_reprocess_item_for_ticket`` adalah yang menolak POST /reprocess_ticket.
    Kalau kedua aturan ini menyimpang, tombolnya kembali berbohong.
    """
    from qc_core.db import crud

    for job_status, item_status in [
        ("running", "pending"), ("running", "processing"),
        ("running", "done"), ("running", "failed"), ("running", "skipped"),
        ("cancelled", "pending"), ("done", "pending"),
    ]:
        tid = _tid("Z")
        _job_with_item(db, job_status=job_status, item_status=item_status, ticket_id=tid)
        via_batch = tid in crud.active_reprocess_ticket_ids(db, [tid])
        via_guard = crud.active_reprocess_item_for_ticket(db, tid) is not None
        assert via_batch == via_guard, (
            f"job={job_status} item={item_status}: batch={via_batch} guard={via_guard}"
        )
