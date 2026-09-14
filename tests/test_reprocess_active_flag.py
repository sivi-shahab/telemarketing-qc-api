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
from datetime import datetime, timedelta

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
                   scope: str = "ticket", age_hours: float = 0):
    """Satu job + satu item, tersimpan di dalam transaksi test.

    ``age_hours`` memundurkan ``created_at`` job — umur itulah yang membedakan
    antrean yang benar-benar menunggu worker dari job yang tersangkut.
    """
    from db.models import ReprocessJob, ReprocessJobItem

    job = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], scope=scope,
                       status=job_status, total_tickets=1,
                       created_by_username="pytest",
                       created_at=datetime.now() - timedelta(hours=age_hours))
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
    from db import crud

    tid = _tid("A")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_item_processing_menandai_tiket_sedang_direproses(db):
    from db import crud

    tid = _tid("B")
    _job_with_item(db, job_status="running", item_status="processing", ticket_id=tid)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_item_selesai_tidak_lagi_menahan_tombol(db):
    """Inti bug-nya: tombol harus kembali ENABLE begitu reproses selesai."""
    from db import crud

    tid = _tid("C")
    _job_with_item(db, job_status="running", item_status="done", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_item_gagal_tidak_menahan_tombol(db):
    """Item ``failed`` boleh dicoba lagi — row lamanya sengaja dipertahankan."""
    from db import crud

    tid = _tid("D")
    _job_with_item(db, job_status="running", item_status="failed", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_job_dibatalkan_tidak_menahan_tombol(db):
    """Sama seperti pengaman 409: item pada job ``cancelled`` tidak akan dikerjakan."""
    from db import crud

    tid = _tid("E")
    _job_with_item(db, job_status="cancelled", item_status="pending", ticket_id=tid)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_job_massal_juga_menahan_tombol(db):
    """Job scope ``campaign`` membekukan row tiket ini juga, jadi tombolnya ikut
    ditahan — ``reprocess_single_ticket`` memang menolaknya dengan 409."""
    from db import crud

    tid = _tid("F")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid,
                   scope="campaign")
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_hanya_tiket_yang_diminta_yang_dikembalikan(db):
    """Dipanggil per halaman (<= 100 baris), jadi hasilnya harus tersaring —
    bukan seluruh antrean. Saat ini ada ratusan job berjalan sekaligus."""
    from db import crud

    diminta, lain = _tid("G"), _tid("H")
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=diminta)
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=lain)
    assert crud.active_reprocess_ticket_ids(db, [diminta]) == {diminta}


def test_daftar_tiket_kosong_tidak_menyentuh_db(db):
    """Halaman tanpa baris tidak boleh memicu query apa pun."""
    from db import crud

    assert crud.active_reprocess_ticket_ids(db, []) == set()


# --------------------------------------------------------------------------
# Job yang tersangkut
#
# Kejadian nyata, 11 September 2026: dua job ``scope="ticket"`` dibuat pukul
# 10:39, task Celery-nya tidak pernah sampai ke worker (antrean kosong, item tidak
# pernah berpindah ke ``processing``), dan jobnya tertinggal ``running``. Tidak ada
# timeout dan tidak ada reaper, jadi kedua tiket itu ditandai "sedang direproses"
# SELAMANYA — tombol Reprocess mati, tombol Delete mati, dan Delete All melewatinya.
# Layar pun tidak menyediakan jalan keluar: tombol "Batalkan" hanya muncul untuk
# job ``scope="campaign"``.
#
# Karena itu umur ikut menentukan: item ``pending`` pada job yang jauh lebih tua
# dari waktu kerja yang wajar bukan antrean, melainkan sisa.
# --------------------------------------------------------------------------

def test_item_pending_pada_job_tersangkut_tidak_lagi_menahan_tombol(db):
    from db import crud

    tid = _tid("S1")
    umur = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 1
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid,
                   age_hours=umur)
    assert crud.active_reprocess_ticket_ids(db, [tid]) == set()


def test_item_pending_yang_masih_wajar_tetap_menahan_tombol(db):
    """Ambangnya harus melepas yang tersangkut TANPA melepas antrean sungguhan."""
    from db import crud

    tid = _tid("S2")
    umur = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 - 1
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid,
                   age_hours=umur)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_item_processing_tua_tetap_menahan_tombol(db):
    """Sengaja TIDAK kedaluwarsa: ``processing`` berarti seorang worker sudah
    memegang tiket ini dan mungkin sedang menunggu jawaban LLM. Melepasnya berarti
    menghapus row yang sebentar lagi disentuh worker itu — bahaya yang justru
    ingin dicegah seluruh pemeriksaan ini. Item ``pending`` tidak punya risiko itu:
    menurut definisinya belum ada yang memegangnya."""
    from db import crud

    tid = _tid("S3")
    _job_with_item(db, job_status="running", item_status="processing", ticket_id=tid,
                   age_hours=crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 48)
    assert tid in crud.active_reprocess_ticket_ids(db, [tid])


def test_aturan_umur_juga_berlaku_pada_pengaman_409(db):
    """Kalau hanya salah satu yang tahu soal umur, tombolnya kembali berbohong."""
    from db import crud

    tid = _tid("S4")
    umur = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 1
    _job_with_item(db, job_status="running", item_status="pending", ticket_id=tid,
                   age_hours=umur)
    assert crud.active_reprocess_item_for_ticket(db, tid) is None


def _netralkan_job_berjalan(db):
    """Netralkan job `running` milik data NYATA, di dalam transaksi test.

    ``running_reprocess_job`` menanyai SELURUH tabel, bukan ticket tertentu, jadi
    tanpa ini hasilnya bergantung pada apa yang kebetulan berjalan di dunia luar.
    Perubahannya ikut ter-rollback.
    """
    from db.models import ReprocessJob

    db.query(ReprocessJob).filter(ReprocessJob.status == "running").update(
        {"status": "done"}, synchronize_session=False)
    db.flush()


def test_job_dengan_item_pending_baru_terlihat_berjalan(db):
    from db import crud

    _netralkan_job_berjalan(db)
    _job_with_item(db, job_status="running", item_status="pending",
                   ticket_id=_tid("R1"), scope="campaign")
    assert crud.running_reprocess_job(db, scope="campaign") is not None


def test_job_massal_tersangkut_tidak_lagi_memblokir_reprocess_all(db):
    """Pengaman 409 "masih ada job massal berjalan" memakai fungsi ini. Job yang
    tersangkut karena itu memblokir Reprocess All SELAMANYA — jebakan yang sama
    dengan yang mengunci tombol Delete, hanya satu tingkat di atasnya."""
    from db import crud

    _netralkan_job_berjalan(db)
    umur = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 1
    _job_with_item(db, job_status="running", item_status="pending",
                   ticket_id=_tid("R2"), scope="campaign", age_hours=umur)
    assert crud.running_reprocess_job(db, scope="campaign") is None


def test_job_dengan_item_processing_tua_tetap_terlihat_berjalan(db):
    """Alasannya sama dengan pada tombol per-ticket: ada worker yang memegangnya."""
    from db import crud

    _netralkan_job_berjalan(db)
    _job_with_item(db, job_status="running", item_status="processing",
                   ticket_id=_tid("R3"), scope="campaign",
                   age_hours=crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 48)
    assert crud.running_reprocess_job(db, scope="campaign") is not None


def test_job_yang_seluruh_itemnya_selesai_tidak_terlihat_berjalan(db):
    """``finish_reprocess_job_if_complete`` dipanggil worker setiap satu item
    selesai; kalau worker mati tepat sebelum item terakhir, statusnya tidak pernah
    berpindah. Job seperti itu tidak punya pekerjaan tersisa, jadi tidak boleh
    memblokir apa pun."""
    from db import crud

    _netralkan_job_berjalan(db)
    _job_with_item(db, job_status="running", item_status="done",
                   ticket_id=_tid("R4"), scope="campaign")
    assert crud.running_reprocess_job(db, scope="campaign") is None


def test_job_tersangkut_tetap_lepas_walau_ada_job_lain_yang_baru(db):
    """Umur yang dibaca harus umur JOB ITU, bukan sembarang job di tabel.

    Klausanya menyebut ``ReprocessJob.created_at`` dari dalam subquery EXISTS. Kalau
    korelasinya lepas — subquery membawa ``FROM reprocess_jobs`` sendiri — syarat
    umurnya berubah makna menjadi "ada job baru di mana pun", dan job tersangkut
    kembali memblokir begitu ada satu job baru mana pun. Test tersangkut yang polos
    tidak akan menangkapnya karena di sana tabelnya hanya berisi job tua itu.
    """
    from db import crud

    _netralkan_job_berjalan(db)
    umur = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 1
    _job_with_item(db, job_status="running", item_status="pending",
                   ticket_id=_tid("R6"), scope="campaign", age_hours=umur)
    _job_with_item(db, job_status="running", item_status="pending",
                   ticket_id=_tid("R7"), scope="ticket")   # baru, scope lain
    assert crud.running_reprocess_job(db, scope="campaign") is None


def test_scope_tetap_menyaring_jenis_job(db):
    """Aturan umur tidak boleh diam-diam melonggarkan penyaringan scope."""
    from db import crud

    _netralkan_job_berjalan(db)
    _job_with_item(db, job_status="running", item_status="pending",
                   ticket_id=_tid("R5"), scope="ticket")
    assert crud.running_reprocess_job(db, scope="campaign") is None
    assert crud.running_reprocess_job(db, scope="ticket") is not None
    assert crud.running_reprocess_job(db) is not None


def test_aturan_sama_dengan_pengaman_409(db):
    """Penanda tombol dan penolakan 409 harus tidak pernah berbeda pendapat.

    ``active_reprocess_item_for_ticket`` adalah yang menolak POST /reprocess_ticket.
    Kalau kedua aturan ini menyimpang, tombolnya kembali berbohong.
    """
    from db import crud

    tua = crud.REPROCESS_STALE_AFTER.total_seconds() / 3600 + 1
    for job_status, item_status, umur in [
        ("running", "pending", 0), ("running", "processing", 0),
        ("running", "done", 0), ("running", "failed", 0), ("running", "skipped", 0),
        ("cancelled", "pending", 0), ("done", "pending", 0),
        # Umur ikut diuji di sini, bukan hanya di test-nya sendiri: justru pasangan
        # inilah yang paling mudah menyimpang kalau nanti salah satu fungsi diubah.
        ("running", "pending", tua), ("running", "processing", tua),
    ]:
        tid = _tid("Z")
        _job_with_item(db, job_status=job_status, item_status=item_status,
                       ticket_id=tid, age_hours=umur)
        via_batch = tid in crud.active_reprocess_ticket_ids(db, [tid])
        via_guard = crud.active_reprocess_item_for_ticket(db, tid) is not None
        assert via_batch == via_guard, (
            f"job={job_status} item={item_status} umur={umur}j: "
            f"batch={via_batch} guard={via_guard}"
        )
