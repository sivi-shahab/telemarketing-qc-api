"""Kill job reproses yang belum selesai (khusus role ``admin``).

"Batalkan" (``/reprocess_job/{id}/cancel``) hanya melewati item ``pending`` dan
membiarkan item ``processing`` jalan terus. Itu benar selama worker-nya hidup,
tetapi item ``processing`` yang worker-nya mati/hang tidak pernah kedaluwarsa
(lihat ``crud._reprocess_item_active_clause``): tiketnya terkunci selamanya —
tombol Reprocess & Delete mati, dan job massal baru ditolak 409.

Kill menutup job itu SEKARANG JUGA:

* ``pending``    -> ``skipped``
* ``processing`` -> ``failed`` (row BARU yang setengah jadi dibuang, row LAMA utuh)
* job            -> ``cancelled`` + ``finished_at``

Test DB memakai transaksi yang selalu di-rollback; tidak ada baris yang tertinggal.
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from db import crud


def _job(db, *, status="running", scope="ticket", age_hours=0.0):
    from db.models import ReprocessJob

    job = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], scope=scope,
                       status=status, total_tickets=0, created_by_username="pytest",
                       created_at=datetime.now() - timedelta(hours=age_hours))
    db.add(job)
    db.flush()
    return job


def _item(db, job, *, status, ticket_id=None, old_ids=(), new_result_id=None):
    from db.models import ReprocessJobItem

    item = ReprocessJobItem(job_id=job.id,
                            ticket_id=ticket_id or f"pytest-kill-{uuid.uuid4().hex[:8]}",
                            campaign="Cashline", old_result_ids=list(old_ids),
                            status=status, new_result_id=new_result_id,
                            started_at=datetime.now() if status == "processing" else None)
    db.add(item)
    job.total_tickets = (job.total_tickets or 0) + 1
    db.flush()
    return item


def _result(db, ticket_id):
    return crud.create_result(db, campaign="Cashline",
                              source_files=[f"{ticket_id}_20260925.pdf"],
                              num_calls=1, transcript_path=None)


# --------------------------------------------------------------------------
# crud.kill_reprocess_job
# --------------------------------------------------------------------------

def test_kill_menutup_job_dan_semua_item_yang_belum_selesai(db):
    job = _job(db)
    pending = _item(db, job, status="pending")
    processing = _item(db, job, status="processing")
    done = _item(db, job, status="done")

    killed = crud.kill_reprocess_job(db, str(job.id), "admin1")

    # Yang dikembalikan hanya item ``processing`` — hanya itu yang punya task Celery
    # untuk dihentikan; item ``pending`` cukup ditandai.
    assert killed == [processing.id]
    db.expire_all()
    assert crud.get_reprocess_item(db, pending.id).status == "skipped"
    p = crud.get_reprocess_item(db, processing.id)
    assert p.status == "failed"
    assert "admin1" in p.error_message
    assert p.finished_at is not None
    assert crud.get_reprocess_item(db, done.id).status == "done"
    job = crud.get_reprocess_job(db, str(job.id))
    assert job.status == "cancelled"
    assert job.finished_at is not None


def test_kill_membuang_row_baru_dan_mempertahankan_row_lama(db):
    tid = f"pytest-kill-{uuid.uuid4().hex[:8]}"
    old = _result(db, tid)
    new = _result(db, tid)
    job = _job(db)
    item = _item(db, job, status="processing", ticket_id=tid,
                 old_ids=[str(old.id)], new_result_id=new.id)

    crud.kill_reprocess_job(db, str(job.id), "admin1")

    db.expire_all()
    assert crud.get_result(db, str(new.id)) is None
    assert crud.get_result(db, str(old.id)) is not None
    assert crud.get_reprocess_item(db, item.id).new_result_id is None


def test_tiket_tidak_lagi_terkunci_setelah_kill(db):
    job = _job(db)
    item = _item(db, job, status="processing")
    assert crud.active_reprocess_item_for_ticket(db, item.ticket_id) is not None

    crud.kill_reprocess_job(db, str(job.id), "admin1")

    assert crud.active_reprocess_item_for_ticket(db, item.ticket_id) is None


def test_kill_job_dibatalkan_yang_itemnya_masih_processing(db):
    """"Batalkan" meninggalkan item ``processing``; Kill harus bisa menyusulnya."""
    job = _job(db, status="cancelled")
    item = _item(db, job, status="processing")

    assert crud.kill_reprocess_job(db, str(job.id), "admin1") == [item.id]
    db.expire_all()
    assert crud.get_reprocess_job(db, str(job.id)).status == "cancelled"
    assert crud.get_reprocess_item(db, item.id).status == "failed"
    assert crud.get_reprocess_job(db, str(job.id)).finished_at is not None


def test_open_jobs_memuat_job_satu_tiket_dan_yang_tersangkut(db):
    fresh = _job(db, scope="ticket")
    _item(db, fresh, status="processing")
    stale = _job(db, scope="campaign", age_hours=48)
    _item(db, stale, status="pending")
    finished = _job(db, status="done")
    _item(db, finished, status="done")
    finished.finished_at = datetime.now()
    db.flush()

    ids = {str(j.id) for j in crud.list_open_reprocess_jobs(db)}

    assert str(fresh.id) in ids
    assert str(stale.id) in ids
    assert str(finished.id) not in ids


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------

@pytest.fixture()
def no_revoke(monkeypatch):
    """Cegat pencarian & penghentian task Celery; kembalikan item yang HENDAK di-revoke."""
    from api.routers import reprocess

    revoked = []
    monkeypatch.setattr(reprocess, "_revoke_item_tasks",
                        lambda item_ids: revoked.extend(item_ids) or len(item_ids))
    return revoked


def test_endpoint_kill_menolak_selain_role_admin(db, no_revoke):
    from api.routers.reprocess import kill_reprocess_job

    job = _job(db)
    _item(db, job, status="processing")
    for role in ("demo", "spq_head", "qc"):
        with pytest.raises(HTTPException) as exc:
            kill_reprocess_job(str(job.id), db=db,
                               current_user=SimpleNamespace(role=role, username="x"))
        assert exc.value.status_code == 403
    assert no_revoke == []


def test_endpoint_kill_menghentikan_task_item_yang_processing(db, admin_user, no_revoke):
    from api.routers.reprocess import kill_reprocess_job

    job = _job(db)
    processing = _item(db, job, status="processing")
    _item(db, job, status="pending")

    res = kill_reprocess_job(str(job.id), db=db, current_user=admin_user)

    assert res.status == "cancelled"
    assert res.counts.processing == 0 and res.counts.pending == 0
    assert no_revoke == [processing.id]


def test_endpoint_kill_job_yang_sudah_selesai_409(db, admin_user, no_revoke):
    from api.routers.reprocess import kill_reprocess_job

    job = _job(db, status="done")
    _item(db, job, status="done")
    job.finished_at = datetime.now()
    db.flush()

    with pytest.raises(HTTPException) as exc:
        kill_reprocess_job(str(job.id), db=db, current_user=admin_user)
    assert exc.value.status_code == 409


def test_endpoint_open_jobs_hanya_admin(db, admin_user):
    from api.routers.reprocess import list_open_reprocess_jobs

    job = _job(db)
    _item(db, job, status="processing")

    res = list_open_reprocess_jobs(db=db, current_user=admin_user)
    assert str(job.id) in {j.job_id for j in res.jobs}
    opened = next(j for j in res.jobs if j.job_id == str(job.id))
    assert [i.status for i in opened.items] == ["processing"]

    with pytest.raises(HTTPException) as exc:
        list_open_reprocess_jobs(db=db, current_user=SimpleNamespace(role="demo"))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------------
# Kill per tiket (tombol Kill di menu Results)
# --------------------------------------------------------------------------

def test_kill_tiket_hanya_menghentikan_tiket_itu_dalam_job_massal(db):
    """Job massal lain tetap jalan: hanya item tiket yang di-kill yang ditutup."""
    job = _job(db, scope="campaign")
    target = _item(db, job, status="processing")
    other_processing = _item(db, job, status="processing")
    other_pending = _item(db, job, status="pending")

    killed = crud.kill_reprocess_ticket(db, target.ticket_id, "admin1")

    assert killed == [target.id]
    db.expire_all()
    t = crud.get_reprocess_item(db, target.id)
    assert t.status == "failed" and "admin1" in t.error_message
    assert crud.get_reprocess_item(db, other_processing.id).status == "processing"
    assert crud.get_reprocess_item(db, other_pending.id).status == "pending"
    j = crud.get_reprocess_job(db, str(job.id))
    assert j.status == "running" and j.finished_at is None


def test_kill_tiket_menutup_job_satu_tiket_sebagai_cancelled(db):
    tid = f"pytest-kill-{uuid.uuid4().hex[:8]}"
    old = _result(db, tid)
    new = _result(db, tid)
    job = _job(db, scope="ticket")
    item = _item(db, job, status="processing", ticket_id=tid,
                 old_ids=[str(old.id)], new_result_id=new.id)

    assert crud.kill_reprocess_ticket(db, tid, "admin1") == [item.id]

    db.expire_all()
    j = crud.get_reprocess_job(db, str(job.id))
    assert j.status == "cancelled" and j.finished_at is not None
    assert crud.get_result(db, str(new.id)) is None
    assert crud.get_result(db, str(old.id)) is not None
    assert crud.active_reprocess_item_for_ticket(db, tid) is None


def test_kill_tiket_pending_dilewati(db):
    job = _job(db, scope="ticket")
    item = _item(db, job, status="pending")

    assert crud.kill_reprocess_ticket(db, item.ticket_id, "admin1") == []
    db.expire_all()
    assert crud.get_reprocess_item(db, item.id).status == "skipped"
    assert crud.get_reprocess_job(db, str(job.id)).status == "cancelled"


def test_endpoint_kill_tiket(db, admin_user, no_revoke):
    from api.routers.reprocess import kill_reprocess_single_ticket

    job = _job(db, scope="ticket")
    item = _item(db, job, status="processing")

    res = kill_reprocess_single_ticket(ticket_id=item.ticket_id, db=db, current_user=admin_user)

    assert res.killed == 1
    assert no_revoke == [item.id]

    with pytest.raises(HTTPException) as exc:  # tidak ada lagi yang aktif
        kill_reprocess_single_ticket(ticket_id=item.ticket_id, db=db, current_user=admin_user)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        kill_reprocess_single_ticket(ticket_id=item.ticket_id, db=db,
                                     current_user=SimpleNamespace(role="demo", username="x"))
    assert exc.value.status_code == 403
