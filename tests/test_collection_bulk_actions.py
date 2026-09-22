"""Reprocess All / Delete All menu Collection Results.

Tiketnya dipilih lewat ``crud.list_collection_results`` — filter & cakupan yang
SAMA dengan daftar ``GET /collection/results`` — bukan ``/list_results`` (yang
justru mengecualikan campaign Collection). Angka di modal harus sama dengan baris
yang benar-benar diproses/dihapus.

Fixture ``db`` = SAVEPOINT + rollback, jadi baris yang dihapus di sini kembali lagi.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers import collection as col
from api.schemas.reprocess import CollectionFilterRequest
from compliance.collection_report import REPORT_TYPE
from db import crud
from db.models import ReprocessJob, ReprocessJobItem, Result, ResultData

KOL = "ZZTestCollection"
USER = SimpleNamespace(username="pytest", role="admin")


def _seed(db, campaign=KOL, passing=True, tid=None):
    tid = tid or f"zz{uuid.uuid4().hex[:8]}"
    r = Result(id=uuid.uuid4(), campaign=campaign, status="done",
               source_files=[f"{tid}_20260917100000.pdf"],
               uploaded_at=datetime(2026, 9, 17, 3, 0))
    db.add(r)
    db.flush()
    status = "SESUAI" if passing else "BELUM_SESUAI"
    db.add(ResultData(result_id=r.id, result_json={
        "report_type": REPORT_TYPE,
        "evaluation": {"scorecard_result": [{"weight": 10, "status": status, "item_code": "A"}]},
    }))
    db.flush()
    return tid


@pytest.fixture()
def scope(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(col, "_view_scope", lambda db, u: {"campaigns": [KOL.casefold()]})


@pytest.fixture()
def no_celery(monkeypatch):
    from api.celery_client import celery_app

    sent = []
    monkeypatch.setattr(celery_app, "send_task",
                        lambda name, args=None, **kw: sent.append((name, args)))
    return sent


def _clear_running_jobs(db):
    db.query(ReprocessJob).filter(ReprocessJob.status == "running").update(
        {"status": "done"}, synchronize_session=False)
    db.query(ReprocessJobItem).filter(
        ReprocessJobItem.status.in_(["pending", "processing"])
    ).update({"status": "done"}, synchronize_session=False)
    db.flush()


def _queue_ticket(db, tid):
    job = ReprocessJob(id=uuid.uuid4(), campaigns=[KOL], scope="ticket", status="running",
                       total_tickets=1, created_by_username="pytest")
    db.add(job)
    db.flush()
    db.add(ReprocessJobItem(job_id=job.id, ticket_id=tid, campaign=KOL,
                            old_result_ids=[], status="pending"))
    db.flush()


def _body(**kw):
    return CollectionFilterRequest(**kw)


def test_preview_hanya_tiket_collection_yang_cocok_filter(db, scope):
    _clear_running_jobs(db)
    lulus = _seed(db, passing=True)
    _seed(db, passing=False)
    _seed(db, campaign="ZZTestCashline")

    semua = col.collection_reprocess_filter_preview(body=_body(), db=db, current_user=USER)
    assert semua.will_process == 2 and semua.skipped == 0
    assert semua.campaigns == [KOL]

    pas = col.collection_reprocess_filter_preview(body=_body(ai_status="PASS"), db=db, current_user=USER)
    assert pas.will_process == 1

    tids, _skip, _c = col._tickets_for_filter(db, USER, _body(ai_status="PASS"))
    assert tids == [lulus]


def test_tiket_yang_sedang_direproses_dilewati(db, scope):
    _clear_running_jobs(db)
    sibuk = _seed(db)
    _seed(db)
    _queue_ticket(db, sibuk)

    res = col.collection_delete_tickets_preview(body=_body(), db=db, current_user=USER)
    assert (res.matched, res.skipped, res.will_delete) == (2, 1, 1)


def test_delete_all_hanya_menghapus_yang_cocok(db, scope):
    _clear_running_jobs(db)
    gagal = _seed(db, passing=False)
    lulus = _seed(db, passing=True)
    cash = _seed(db, campaign="ZZTestCashline")

    res = col.collection_delete_tickets_filtered(body=_body(ai_status="FAIL"), db=db, current_user=USER)
    assert (res.tickets, res.deleted) == (1, 1)

    sisa = {r.source_files[0].split("_", 1)[0] for r in db.query(Result).filter(
        Result.campaign.in_([KOL, "ZZTestCashline"])).all()}
    assert gagal not in sisa
    assert {lulus, cash} <= sisa


def test_delete_all_tanpa_tiket_404(db, scope):
    with pytest.raises(HTTPException) as e:
        col.collection_delete_tickets_filtered(body=_body(ticket_id="tidak-ada-zz"), db=db, current_user=USER)
    assert e.value.status_code == 404


def test_reprocess_all_membuat_job_satu_task_per_tiket(db, scope, no_celery):
    _clear_running_jobs(db)
    _seed(db)
    _seed(db)

    res = col.collection_reprocess_filtered(body=_body(), db=db, current_user=USER)
    assert res.total_tickets == 2 == len(no_celery)
    assert res.campaigns == [KOL]
    assert crud.get_reprocess_job(db, res.job_id).scope == "campaign"


def test_reprocess_all_ditolak_saat_job_massal_berjalan(db, scope, no_celery):
    _clear_running_jobs(db)
    _seed(db)
    # Job massal hanya memblokir selama masih punya item aktif
    # (lihat crud.running_reprocess_job).
    job = ReprocessJob(id=uuid.uuid4(), campaigns=[KOL], scope="campaign", status="running",
                       total_tickets=1, created_by_username="pytest")
    db.add(job)
    db.flush()
    db.add(ReprocessJobItem(job_id=job.id, ticket_id="zz-lain", campaign=KOL,
                            old_result_ids=[], status="pending"))
    db.flush()

    with pytest.raises(HTTPException) as e:
        col.collection_reprocess_filtered(body=_body(), db=db, current_user=USER)
    assert e.value.status_code == 409
    assert no_celery == []


def test_daftar_menandai_reprocess_active(db, scope):
    _clear_running_jobs(db)
    sibuk = _seed(db)
    bebas = _seed(db)
    _queue_ticket(db, sibuk)

    res = col.list_collection_results(status=None, ai_status=None, ticket_id=None,
                                      date_start=None, date_end=None, page=1, limit=100,
                                      db=db, current_user=USER)
    flags = {i["ticket_id"]: i["reprocess_active"] for i in res["items"]}
    assert flags[sibuk] is True and flags[bebas] is False


def test_tanpa_menu_collection_ditolak(db, monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: False)
    with pytest.raises(HTTPException) as e:
        col.collection_delete_tickets_preview(body=_body(), db=db, current_user=USER)
    assert e.value.status_code == 403
