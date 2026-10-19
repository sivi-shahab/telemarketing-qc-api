"""Reproses retry data acuan membawa pekerjaan QC ke row baru (19 Oktober 2026).

Kasus 130309XxVf: tiket yang belum pernah dinilai LLM punya pengajuan Manual Status
PASS di 3 dari 7 row duplikat JOB-3. Retry mereproses tiketnya, row lama dihapus, dan
pengajuan itu ikut hilang lewat ON DELETE CASCADE. ``crud.carry_over_qc_work`` kini
memindahkannya lebih dulu.

Baris test memakai tahun 2000 dan id acak; transaksi selalu di-rollback.
"""
import uuid
from datetime import datetime, timedelta

T0 = datetime(2000, 1, 2, 3, 0)


def _row(db, tid):
    from db.models import Result

    r = Result(id=uuid.uuid4(), campaign="Cashline", status="done",
               source_files=[f"{tid}_a.pdf"], uploaded_at=T0)
    db.add(r)
    db.flush()
    return r


def _setup(db):
    """3 row lama (salinan JOB-3) dengan pekerjaan QC kembar + 1 row baru."""
    from db.models import Document, QcManualCheck, QcStatusEvent, QcStatusRequest

    tid = uuid.uuid4().hex[:10]
    olds = [_row(db, tid) for _ in range(3)]
    new = _row(db, tid)
    for i, r in enumerate(olds):
        db.add(QcStatusRequest(result_id=r.id, requested_status="PASS", reason=f"alasan {i}",
                               requested_by_username="qc1", requested_at=T0 + timedelta(minutes=i)))
        # Riwayat yang sama tersalin ke tiap row duplikat.
        db.add(QcStatusEvent(result_id=r.id, event="usul", actor_username="qc1",
                             requested_status="PASS", created_at=T0))
        db.add(QcManualCheck(result_id=r.id, checked_by_username="qc1", created_at=T0))
        db.add(Document(result_id=r.id, doc_type="ktp", object_path="docs/ktp.jpg"))
    db.flush()
    return olds, new


def test_pekerjaan_qc_dibawa_tanpa_berlipat(db):
    from db import crud
    from db.models import Document, QcManualCheck, QcStatusEvent, QcStatusRequest

    olds, new = _setup(db)

    moved = crud.carry_over_qc_work(db, [str(r.id) for r in olds + [new]], str(new.id))

    assert moved == {"status_request": 1, "status_events": 1, "manual_checks": 1, "documents": 1}
    req = db.query(QcStatusRequest).filter(QcStatusRequest.result_id == new.id).one()
    assert (req.requested_status, req.reason) == ("PASS", "alasan 2")  # yang terbaru
    for model in (QcStatusEvent, QcManualCheck, Document):
        assert db.query(model).filter(model.result_id == new.id).count() == 1

    # Setelah row lama dihapus, pekerjaan QC tetap ada di row baru.
    crud.delete_results_by_ids(db, [str(r.id) for r in olds])
    assert db.query(QcStatusRequest).filter(QcStatusRequest.result_id == new.id).count() == 1
    assert db.query(QcStatusEvent).filter(QcStatusEvent.result_id == new.id).count() == 1


def test_pengajuan_row_baru_tidak_ditimpa(db):
    from db import crud
    from db.models import QcStatusRequest

    olds, new = _setup(db)
    db.add(QcStatusRequest(result_id=new.id, requested_status="FAIL", reason="baru"))
    db.flush()

    moved = crud.carry_over_qc_work(db, [str(r.id) for r in olds], str(new.id))

    assert moved["status_request"] == 0
    req = db.query(QcStatusRequest).filter(QcStatusRequest.result_id == new.id).one()
    assert req.requested_status == "FAIL"


def test_tanpa_row_lama_tidak_ada_yang_dipindah(db):
    from db import crud

    _olds, new = _setup(db)
    assert crud.carry_over_qc_work(db, [], str(new.id)) == {
        "status_request": 0, "status_events": 0, "manual_checks": 0, "documents": 0}
