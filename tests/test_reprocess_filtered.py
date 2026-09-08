"""Reprocess All: memproses ulang tiket yang COCOK DENGAN FILTER menu Results.

Bahaya utama fitur ini bukan kode yang salah, melainkan angka yang berbohong.
Modal konfirmasi menyebut "120 tiket akan diproses" dan Admin menekannya; kalau
daftar yang benar-benar dikerjakan ternyata berbeda, yang hilang adalah ratusan
panggilan LLM dan ratusan entry lama yang terhapus di luar dugaan.

Kenapa gampang berbeda: filter **AI Status** dan **Manual Status** TIDAK bisa
dihitung di SQL. Keduanya diturunkan per hasil di Python (``_apply_status_filters``)
dari result_json + banding + QC status + dokumen. ``crud.reprocess_ticket_plan``
yang dipakai menu Reprocess massal hanya tahu campaign, jadi ia tidak bisa dipakai
di sini. Satu-satunya cara agar dua angka itu tidak menyimpang adalah memakai
JALUR PEMILIHAN BARIS YANG SAMA dengan ``/list_results``.

Karena itu blok pemilihan baris di ``list_results`` diekstrak menjadi
``_resolve_filtered_results``, dan berkas ini yang menjaga keduanya tetap sepakat.
Pola bug yang dihindari sudah pernah terjadi di berkas yang sama: ``stats.py``
dulu menyimpan salinan ``_max_score``/``_scorecard_score`` sendiri dan tertinggal
saat modul aslinya berubah (docs/README.md, Pembaruan 28 Agustus 2026).

Test memakai fixture ``db`` (transaksi yang selalu di-rollback), jadi baris yang
disisipkan tidak pernah tertinggal.
"""
import uuid

import pytest

from api.routers import stats


# --------------------------------------------------------------------------
# Bantuan
# --------------------------------------------------------------------------

def _call_list_results(db, user, **over):
    """Panggil route ``list_results`` sebagai fungsi Python biasa.

    Seluruh parameter WAJIB diisi eksplisit: nilai bawaannya objek ``Query(...)``,
    bukan nilai biasa, jadi parameter yang dilewat akan terbaca sebagai objek
    FastAPI dan merusak aritmetika halaman.
    """
    kw = dict(
        status=None, campaign=None, ticket_id=None, ai_status=None,
        manual_status=None, am_nip=None, tl_nip=None, agent_nip=None,
        qc_username=None, qc_support_username=None, date_start=None,
        date_end=None, banding_pending=False, manual_status_pending=False,
        page=1, limit=100,
    )
    kw.update(over)
    return stats.list_results(db=db, current_user=user, **kw)


def _tickets_from_response(res):
    return [it.id for it in res.items if it.id]


def _tickets_from_rows(rows):
    return [stats._customer_id_from_files(r.source_files) for r in rows]


def _some_campaign(db):
    from qc_core.db.models import Result

    row = db.query(Result).filter(Result.campaign.isnot(None)).first()
    if row is None:
        pytest.skip("tidak ada result dengan campaign di database")
    return row.campaign


# --------------------------------------------------------------------------
# _resolve_filtered_results sepakat dengan /list_results
#
# Inilah yang menjaga angka di modal = tiket yang dikerjakan. Kalau suatu saat
# seseorang menyalin ulang logika filter ke endpoint reproses, test ini yang
# berteriak.
# --------------------------------------------------------------------------

def test_tanpa_filter_helper_sepakat_dengan_list_results(db, admin_user):
    rows, _ = stats._resolve_filtered_results(db, admin_user, page=1, limit=100)
    assert _tickets_from_rows(rows) == _tickets_from_response(_call_list_results(db, admin_user))


def test_filter_campaign_helper_sepakat_dengan_list_results(db, admin_user):
    camp = _some_campaign(db)
    rows, _ = stats._resolve_filtered_results(db, admin_user, campaign=camp, page=1, limit=100)
    expected = _call_list_results(db, admin_user, campaign=camp)
    assert _tickets_from_rows(rows) == _tickets_from_response(expected)


@pytest.mark.parametrize("ai", ["PASS", "FAIL", "PENDING"])
def test_filter_ai_status_helper_sepakat_dengan_list_results(db, admin_user, ai):
    """Filter yang diturunkan di Python — di sinilah dua jalur paling mudah menyimpang."""
    rows, _ = stats._resolve_filtered_results(db, admin_user, ai_status=ai, page=1, limit=100)
    expected = _call_list_results(db, admin_user, ai_status=ai)
    assert _tickets_from_rows(rows) == _tickets_from_response(expected)


@pytest.mark.parametrize("manual", ["PASS", "FAIL", "PENDING"])
def test_filter_manual_status_helper_sepakat_dengan_list_results(db, admin_user, manual):
    rows, _ = stats._resolve_filtered_results(db, admin_user, manual_status=manual, page=1, limit=100)
    expected = _call_list_results(db, admin_user, manual_status=manual)
    assert _tickets_from_rows(rows) == _tickets_from_response(expected)


def test_filter_tanggal_helper_sepakat_dengan_list_results(db, admin_user):
    rows, _ = stats._resolve_filtered_results(
        db, admin_user, date_start="2026-08-01", date_end="2026-08-31", page=1, limit=100)
    expected = _call_list_results(db, admin_user, date_start="2026-08-01", date_end="2026-08-31")
    assert _tickets_from_rows(rows) == _tickets_from_response(expected)


def test_filter_campaign_di_luar_cakupan_role_menghasilkan_kosong(db, admin_user):
    """Menyempitkan, tidak pernah melebar — pengaman RBAC yang sama dengan list_results."""
    rows, total = stats._resolve_filtered_results(
        db, admin_user, campaign="Campaign Yang Tidak Ada 12345", page=1, limit=100)
    assert rows == [] and total == 0


# --------------------------------------------------------------------------
# Rencana reproses untuk sekumpulan ticket id
# --------------------------------------------------------------------------

def _existing_ticket_ids(db, n=3):
    from qc_core.db.models import Result

    seen = []
    for row in db.query(Result).limit(50).all():
        tid = stats._customer_id_from_files(row.source_files)
        if tid and tid not in seen:
            seen.append(tid)
        if len(seen) >= n:
            break
    if not seen:
        pytest.skip("tidak ada result dengan source_files di database")
    return seen


def test_rencana_dibuat_untuk_setiap_ticket_id_yang_ada(db):
    from qc_core.db import crud

    tids = _existing_ticket_ids(db, 3)
    plan = crud.reprocess_plan_for_tickets(db, tids)
    assert sorted(p["ticket_id"] for p in plan) == sorted(tids)


def test_rencana_membawa_seluruh_row_lama_tiket(db):
    """``old_result_ids`` dibekukan saat job dibuat; harus memuat SEMUA row tiket itu."""
    from qc_core.db import crud

    tid = _existing_ticket_ids(db, 1)[0]
    plan = crud.reprocess_plan_for_tickets(db, [tid])
    satu = crud.reprocess_plan_for_ticket(db, tid)
    assert sorted(plan[0]["old_result_ids"]) == sorted(satu["old_result_ids"])
    assert plan[0]["source_result_id"] == satu["source_result_id"]


def test_ticket_id_tak_dikenal_dilewati_tanpa_error(db):
    from qc_core.db import crud

    assert crud.reprocess_plan_for_tickets(db, ["TIDAKADA123"]) == []


def test_daftar_kosong_menghasilkan_rencana_kosong(db):
    from qc_core.db import crud

    assert crud.reprocess_plan_for_tickets(db, []) == []


# --------------------------------------------------------------------------
# Melewati tiket yang jobnya sudah berjalan
# --------------------------------------------------------------------------

def _clear_running_jobs(db):
    """Netralkan job yang sedang berjalan di data NYATA, di dalam transaksi test.

    Tanpa ini test tidak deterministik: saat berkas ini ditulis ada 247 job
    berjalan, jadi tiket mana pun yang dipungut dari tabel berpeluang besar sudah
    ditandai sibuk oleh dunia luar. Perubahannya ikut ter-rollback.
    """
    from qc_core.db.models import ReprocessJob

    db.query(ReprocessJob).filter(ReprocessJob.status == "running").update(
        {"status": "done"}, synchronize_session=False)
    db.flush()


def _queue_ticket(db, ticket_id):
    """Tandai sebuah tiket sedang direproses, di dalam transaksi test."""
    from qc_core.db.models import ReprocessJob, ReprocessJobItem

    job = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], scope="ticket",
                       status="running", total_tickets=1, created_by_username="pytest")
    db.add(job)
    db.flush()
    db.add(ReprocessJobItem(job_id=job.id, ticket_id=ticket_id, campaign="Cashline",
                            old_result_ids=[], status="pending"))
    db.flush()


def test_tiket_yang_sedang_direproses_dilewati_dari_rencana(db, admin_user):
    """Alasannya bukan sopan santun: dua job pada tiket yang sama akan membekukan
    daftar row lama yang beririsan, dan yang kalah cepat mencoba menghapus row
    yang sudah tidak ada."""
    from api.routers import reprocess

    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    plan, skipped = reprocess._plan_for_filtered(db, admin_user, {})
    assert tid not in [p["ticket_id"] for p in plan]
    assert skipped >= 1


def test_tiket_bebas_tetap_masuk_rencana(db, admin_user):
    """Yang dilewati hanya yang bentrok — sisanya tetap dikerjakan."""
    from api.routers import reprocess

    tids = _existing_ticket_ids(db, 2)
    _clear_running_jobs(db)
    _queue_ticket(db, tids[0])
    plan, skipped = reprocess._plan_for_filtered(db, admin_user, {})
    nama = [p["ticket_id"] for p in plan]
    assert tids[0] not in nama
    assert tids[1] in nama
    assert skipped == 1


def test_rencana_mengikuti_filter_yang_diberikan(db, admin_user):
    """Rencana = tiket yang cocok filter, bukan seluruh isi tabel."""
    from api.routers import reprocess

    camp = _some_campaign(db)
    plan, _ = reprocess._plan_for_filtered(db, admin_user, {"campaign": camp})
    semua, _ = reprocess._plan_for_filtered(db, admin_user, {})
    assert len(plan) <= len(semua)
    assert all((p["campaign"] or "").strip().casefold() == camp.strip().casefold() for p in plan)


def test_hitungan_dilewati_nol_saat_tidak_ada_yang_bentrok(db, admin_user):
    from api.routers import reprocess

    _clear_running_jobs(db)
    _, skipped = reprocess._plan_for_filtered(db, admin_user, {})
    assert skipped == 0


# --------------------------------------------------------------------------
# Endpoint
#
# Job yang dibuat di sini ikut ter-rollback (fixture memakai SAVEPOINT), dan
# pengiriman task Celery DIGANTI — kalau tidak, menjalankan test berarti membayar
# ratusan panggilan LLM sungguhan.
# --------------------------------------------------------------------------

@pytest.fixture()
def no_celery(monkeypatch):
    """Cegat pengiriman task; kembalikan daftar task yang HENDAK dikirim."""
    from api.celery_client import celery_app

    sent = []
    monkeypatch.setattr(celery_app, "send_task",
                        lambda name, args=None, **kw: sent.append((name, args)))
    return sent


def _filter_body(**over):
    from api.schemas.reprocess import ReprocessFilterRequest

    return ReprocessFilterRequest(**over)


def test_preview_melaporkan_matched_skipped_dan_will_process(db, admin_user):
    from api.routers import reprocess

    _clear_running_jobs(db)
    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    res = reprocess.reprocess_filter_preview(body=_filter_body(), db=db, current_user=admin_user)
    assert res.skipped == 1
    assert res.will_process == res.matched - res.skipped
    assert res.matched >= 1


def test_preview_mengikuti_filter_campaign(db, admin_user):
    from api.routers import reprocess

    _clear_running_jobs(db)
    camp = _some_campaign(db)
    tersaring = reprocess.reprocess_filter_preview(
        body=_filter_body(campaign=camp), db=db, current_user=admin_user)
    semua = reprocess.reprocess_filter_preview(body=_filter_body(), db=db, current_user=admin_user)
    assert tersaring.matched <= semua.matched
    assert tersaring.campaigns == [camp] or all(
        c.strip().casefold() == camp.strip().casefold() for c in tersaring.campaigns)


def test_preview_tidak_membuat_job(db, admin_user):
    """Membuka modal konfirmasi tidak boleh mengeluarkan biaya apa pun."""
    from api.routers import reprocess
    from qc_core.db.models import ReprocessJob

    sebelum = db.query(ReprocessJob).count()
    reprocess.reprocess_filter_preview(body=_filter_body(), db=db, current_user=admin_user)
    assert db.query(ReprocessJob).count() == sebelum


def test_post_membuat_job_dan_mengirim_satu_task_per_tiket(db, admin_user, no_celery):
    from api.routers import reprocess

    _clear_running_jobs(db)
    res = reprocess.reprocess_filtered(body=_filter_body(), db=db, current_user=admin_user)
    assert res.status == "running"
    assert res.total_tickets == len(no_celery)
    assert all(n == "worker.tasks.reprocess_ticket.reprocess_ticket" for n, _ in no_celery)


def test_post_melewati_tiket_yang_sedang_direproses(db, admin_user, no_celery):
    from api.routers import reprocess

    _clear_running_jobs(db)
    tid = _existing_ticket_ids(db, 1)[0]
    _queue_ticket(db, tid)
    res = reprocess.reprocess_filtered(body=_filter_body(), db=db, current_user=admin_user)
    assert tid not in [it.ticket_id for it in res.items]


def test_post_menolak_kalau_job_massal_berjalan(db, admin_user, no_celery):
    """Dua job massal berarti ongkos LLM berlipat dan row lama yang beririsan."""
    import uuid as _uuid

    from fastapi import HTTPException

    from api.routers import reprocess
    from qc_core.db.models import ReprocessJob

    _clear_running_jobs(db)
    db.add(ReprocessJob(id=_uuid.uuid4(), campaigns=["Cashline"], scope="campaign",
                        status="running", total_tickets=1, created_by_username="pytest"))
    db.flush()
    with pytest.raises(HTTPException) as exc:
        reprocess.reprocess_filtered(body=_filter_body(), db=db, current_user=admin_user)
    assert exc.value.status_code == 409
    assert no_celery == []


def test_post_menolak_filter_yang_tidak_cocok_apa_pun(db, admin_user, no_celery):
    from fastapi import HTTPException

    from api.routers import reprocess

    with pytest.raises(HTTPException) as exc:
        reprocess.reprocess_filtered(
            body=_filter_body(ticket_id="TIDAKADA123"), db=db, current_user=admin_user)
    assert exc.value.status_code == 404
    assert no_celery == []


def test_post_menolak_campaign_di_luar_cakupan_role(db, admin_user, no_celery):
    """Cakupan diwarisi dari _resolve_filtered_results, jadi hasilnya kosong -> 404,
    bukan diam-diam melebar ke campaign lain."""
    from fastapi import HTTPException

    from api.routers import reprocess

    with pytest.raises(HTTPException):
        reprocess.reprocess_filtered(
            body=_filter_body(campaign="Campaign Yang Tidak Ada 12345"),
            db=db, current_user=admin_user)
    assert no_celery == []
