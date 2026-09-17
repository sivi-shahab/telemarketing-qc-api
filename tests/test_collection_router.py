"""Menu Collection: query daftar dan endpoint-nya.

Bagian DB memakai fixture ``db`` (transaksi yang selalu di-rollback, skip bila DB
tidak terjangkau)."""
import uuid
from datetime import datetime

from db import crud
from db.models import Result, ResultData
from compliance.collection_report import REPORT_TYPE


def _seed(db, campaign, status="done", evaluation=None, uploaded_at=None):
    r = Result(id=uuid.uuid4(), campaign=campaign, status=status,
               source_files=[f"{uuid.uuid4().hex[:8]}_call.pdf"],
               uploaded_at=uploaded_at or datetime(2026, 9, 17, 3, 0))
    db.add(r)
    db.flush()
    if evaluation is not None:
        db.add(ResultData(result_id=r.id, result_json={"report_type": REPORT_TYPE, "evaluation": evaluation}))
        db.flush()
    return r


def _passing_eval():
    return {"scorecard_result": [{"weight": 10, "status": "SESUAI", "item_code": "A"}]}


def _failing_eval():
    return {"scorecard_result": [{"weight": 10, "status": "BELUM_SESUAI", "item_code": "A"}]}


def test_list_results_bisa_mengecualikan_campaign(db):
    kol = _seed(db, "ZZTestCollection")
    cash = _seed(db, "ZZTestCashline")
    ids = {str(r.id) for r in crud.list_results(db, limit=1_000_000, exclude_campaigns=["zztestcollection"])[0]}
    assert str(cash.id) in ids
    assert str(kol.id) not in ids


def test_list_collection_results_hanya_campaign_yang_diminta(db):
    kol = _seed(db, "ZZTestCollection", evaluation=_passing_eval())
    _seed(db, "ZZTestCashline")
    rows, total = crud.list_collection_results(db, campaigns=["ZZTestCollection"], limit=100)
    assert total == 1
    assert str(rows[0][0].id) == str(kol.id)
    assert rows[0][1]["report_type"] == REPORT_TYPE


def test_list_collection_results_filter_ai_status(db):
    lulus = _seed(db, "ZZTestCollection", evaluation=_passing_eval())
    _seed(db, "ZZTestCollection", evaluation=_failing_eval())
    rows, total = crud.list_collection_results(db, campaigns=["ZZTestCollection"], ai_status="PASS")
    assert total == 1 and str(rows[0][0].id) == str(lulus.id)


def test_list_collection_results_daftar_campaign_kosong(db):
    assert crud.list_collection_results(db, campaigns=[]) == ([], 0)
