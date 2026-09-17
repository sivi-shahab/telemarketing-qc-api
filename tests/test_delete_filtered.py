"""Delete All: menghapus tiket yang COCOK DENGAN FILTER menu Results.

Saudara kembar ``test_reprocess_filtered.py``, dan bahayanya persis sama tapi
lebih tajam: Reprocess All yang salah sasaran membakar panggilan LLM dan masih
menyisakan entry lama kalau gagal, sedangkan Delete All yang salah sasaran
**tidak bisa dibatalkan**. Modal konfirmasi menyebut "120 ticket akan dihapus";
kalau daftar yang benar-benar dihapus berbeda, tidak ada jalan pulang.

Karena itu jalur pemilihan tiketnya WAJIB ``stats._resolve_filtered_results`` —
jalur yang sama dengan ``/list_results`` dan dengan Reprocess All. Filter
``ai_status``/``manual_status`` diturunkan di Python, bukan di SQL, jadi query
sendiri di endpoint delete pasti menyimpang dari angka yang dibaca Admin.

Test memakai fixture ``db`` (SAVEPOINT + rollback), jadi baris yang DIHAPUS di
sini kembali lagi begitu test selesai — termasuk saat dijalankan terhadap DB
berisi data sungguhan.
"""
import uuid

import pytest

from api.routers import stats


def _existing_ticket_ids(db, n=3):
    from db.models import Result

    seen = []
    for row in db.query(Result).limit(200).all():
        tid = stats._customer_id_from_files(row.source_files)
        if tid and tid not in seen:
            seen.append(tid)
        if len(seen) >= n:
            break
    if len(seen) < n:
        pytest.skip(f"butuh {n} ticket berbeda di database")
    return seen


def _rows_for(db, ticket_id):
    from sqlalchemy import func

    from db.models import Result

    return (
        db.query(Result)
        .filter(func.split_part(Result.source_files[0].astext, "_", 1) == ticket_id)
        .count()
    )


def _clear_running_jobs(db):
    """Netralkan job reproses yang berjalan di data NYATA, di dalam transaksi test.

    Tanpa ini test tidak deterministik: tiket mana pun yang dipungut dari tabel
    berpeluang sudah ditandai sibuk oleh dunia luar, dan ``skipped`` ikut naik.
    """
    from db.models import ReprocessJob, ReprocessJobItem

    db.query(ReprocessJob).filter(ReprocessJob.status == "running").update(
        {"status": "done"}, synchronize_session=False)
    # Status job saja tidak cukup: item ``processing`` tetap dihitung aktif walau
    # job-nya sudah bukan ``running`` (lihat crud._reprocess_item_active_clause).
    db.query(ReprocessJobItem).filter(
        ReprocessJobItem.status.in_(["pending", "processing"])
    ).update({"status": "done"}, synchronize_session=False)
    db.flush()


def _queue_ticket(db, ticket_id):
    from db.models import ReprocessJob, ReprocessJobItem

    job = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], scope="ticket",
                       status="running", total_tickets=1, created_by_username="pytest")
    db.add(job)
    db.flush()
    db.add(ReprocessJobItem(job_id=job.id, ticket_id=ticket_id, campaign="Cashline",
                            old_result_ids=[], status="pending"))
    db.flush()


def _body(**over):
    from api.schemas.reprocess import ReprocessFilterRequest

    return ReprocessFilterRequest(**over)


# --------------------------------------------------------------------------
# Pemilihan tiket
# --------------------------------------------------------------------------

def test_daftar_tiket_sama_dengan_jalur_list_results(db, admin_user):
    """Satu-satunya cara agar angka modal = baris yang terhapus."""
    _clear_running_jobs(db)
    tids, skipped, _camps = stats._tickets_for_filtered_delete(db, admin_user, {})
    rows, _ = stats._resolve_filtered_results(db, admin_user, page=1, limit=stats._DELETE_ROW_CAP)
    harapan = []
    for row in rows:
        tid = stats._customer_id_from_files(row.source_files)
        if tid and tid not in harapan:
            harapan.append(tid)
    assert tids == harapan
    assert skipped == 0


def test_daftar_tiket_mengikuti_filter(db, admin_user):
    tid = _existing_ticket_ids(db, 1)[0]
    tids, _skipped, _camps = stats._tickets_for_filtered_delete(db, admin_user, {"ticket_id": tid})
    assert tid in tids
    semua, _s, _c = stats._tickets_for_filtered_delete(db, admin_user, {})
    assert len(tids) <= len(semua)


def test_tiket_yang_sedang_direproses_dilewati(db, admin_user):
    """Job reproses sudah membekukan ``old_result_ids`` tiket ini. Kalau row-nya
    dihapus duluan, worker akan mencoba menghapus row yang sudah tidak ada."""
    _clear_running_jobs(db)
    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    tids, skipped, _camps = stats._tickets_for_filtered_delete(db, admin_user, {})
    assert tid not in tids
    assert skipped == 1


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------

def test_preview_melaporkan_matched_skipped_dan_will_delete(db, admin_user):
    _clear_running_jobs(db)
    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    res = stats.delete_tickets_preview(body=_body(), db=db, current_user=admin_user)
    assert res.skipped == 1
    assert res.will_delete == res.matched - res.skipped
    assert res.matched >= 1


def test_preview_menghitung_seluruh_entry_tiket_bukan_hanya_yang_cocok(db, admin_user):
    """``results`` adalah baris yang BENAR-BENAR terhapus: delete memakai ticket id,
    jadi entry lain milik tiket yang sama ikut hilang walau tidak cocok filter."""
    tid = _existing_ticket_ids(db, 1)[0]
    res = stats.delete_tickets_preview(body=_body(ticket_id=tid), db=db, current_user=admin_user)
    assert res.results == sum(_rows_for(db, t) for t in
                              stats._tickets_for_filtered_delete(db, admin_user, {"ticket_id": tid})[0])


def test_preview_tidak_menghapus_apa_pun(db, admin_user):
    from db.models import Result

    sebelum = db.query(Result).count()
    stats.delete_tickets_preview(body=_body(), db=db, current_user=admin_user)
    assert db.query(Result).count() == sebelum


# --------------------------------------------------------------------------
# Endpoint hapus
# --------------------------------------------------------------------------

def test_hapus_hanya_menyentuh_tiket_yang_cocok(db, admin_user):
    _clear_running_jobs(db)
    tids = _existing_ticket_ids(db, 2)
    sasaran, lain = tids[0], tids[1]
    if _rows_for(db, lain) == 0:
        pytest.skip("ticket pembanding tidak punya row")
    res = stats.delete_tickets_filtered(body=_body(ticket_id=sasaran), db=db, current_user=admin_user)
    assert res.deleted >= 1
    assert _rows_for(db, sasaran) == 0
    assert _rows_for(db, lain) >= 1


def test_hapus_melewati_tiket_yang_sedang_direproses(db, admin_user):
    from fastapi import HTTPException

    _clear_running_jobs(db)
    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    with pytest.raises(HTTPException) as exc:
        stats.delete_tickets_filtered(body=_body(ticket_id=tid), db=db, current_user=admin_user)
    assert exc.value.status_code == 404
    assert _rows_for(db, tid) >= 1


def test_hapus_menolak_filter_yang_tidak_cocok_apa_pun(db, admin_user):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        stats.delete_tickets_filtered(body=_body(ticket_id="TIDAKADA123"), db=db, current_user=admin_user)
    assert exc.value.status_code == 404


def test_hapus_menolak_campaign_di_luar_cakupan_role(db, admin_user):
    """Cakupan diwarisi dari _resolve_filtered_results — kosong, bukan melebar."""
    from fastapi import HTTPException

    from db.models import Result

    sebelum = db.query(Result).count()
    with pytest.raises(HTTPException):
        stats.delete_tickets_filtered(
            body=_body(campaign="Campaign Yang Tidak Ada 12345"), db=db, current_user=admin_user)
    assert db.query(Result).count() == sebelum


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

def test_crud_daftar_kosong_tidak_menghapus_apa_pun(db):
    from db import crud
    from db.models import Result

    sebelum = db.query(Result).count()
    assert crud.delete_results_by_ticket_ids(db, []) == 0
    assert db.query(Result).count() == sebelum


def test_crud_mengembalikan_jumlah_baris_yang_terhapus(db):
    from db import crud

    tid = _existing_ticket_ids(db, 1)[0]
    n = _rows_for(db, tid)
    assert crud.delete_results_by_ticket_ids(db, [tid]) == n
    assert _rows_for(db, tid) == 0


def test_crud_menghitung_baris_untuk_banyak_tiket(db):
    from db import crud

    tids = _existing_ticket_ids(db, 2)
    assert crud.results_count_by_ticket_ids(db, tids) == sum(_rows_for(db, t) for t in tids)
    assert crud.results_count_by_ticket_ids(db, []) == 0
