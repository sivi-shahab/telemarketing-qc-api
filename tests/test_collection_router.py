"""Menu Collection: query daftar dan endpoint-nya.

Bagian DB memakai fixture ``db`` (transaksi yang selalu di-rollback, skip bila DB
tidak terjangkau). Bagian router memanggil fungsi route langsung tanpa DB, dengan
``monkeypatch`` atas dependensinya."""
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from db import crud
from db.models import Result, ResultData
from compliance.collection_report import REPORT_TYPE
from api.routers import collection as col


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


def test_list_collection_results_filter_tanggal_pakai_wib(db):
    """Tanpa ``reference_data`` (jalur Collection sengaja tidak punya itu) dan tanpa
    ``generated_at``, filter tanggal jatuh ke fallback terakhir: ``uploaded_at``
    dikonversi WIB (UTC+7) — BUKAN tanggal UTC mentahnya. 2026-09-16 18:30 UTC adalah
    2026-09-17 01:30 WIB, jadi hasilnya harus lolos filter tanggal 2026-09-17 dan
    TIDAK lolos filter 2026-09-16, membuktikan konversinya benar-benar terjadi."""
    dekat_batas = _seed(db, "ZZTestCollection", uploaded_at=datetime(2026, 9, 16, 18, 30))
    di_luar_rentang = _seed(db, "ZZTestCollection", uploaded_at=datetime(2026, 9, 14, 10, 0))

    rows, total = crud.list_collection_results(
        db, campaigns=["ZZTestCollection"],
        date_start=date(2026, 9, 17), date_end=date(2026, 9, 17), limit=100,
    )
    assert total == 1
    assert str(rows[0][0].id) == str(dekat_batas.id)
    assert str(di_luar_rentang.id) not in {str(r[0].id) for r in rows}

    # Tanggal UTC mentahnya (16 September) TIDAK boleh menangkap baris ini — kalau
    # tertangkap berarti fallback memakai uploaded_at UTC, bukan WIB.
    rows_utc, total_utc = crud.list_collection_results(
        db, campaigns=["ZZTestCollection"],
        date_start=date(2026, 9, 16), date_end=date(2026, 9, 16), limit=100,
    )
    assert str(dekat_batas.id) not in {str(r[0].id) for r in rows_utc}


def _user():
    return SimpleNamespace(role="qc", username="u1")


def test_allowed_campaigns_irisan_env_dan_cakupan(monkeypatch):
    monkeypatch.setattr(col, "collection_campaigns_from_env", lambda: frozenset({"collection", "koleksi"}))
    monkeypatch.setattr(col, "effective_campaigns_for", lambda db, u: ["Collection", "Cashline"])
    assert col._allowed_campaigns(None, _user()) == ["collection"]


def test_allowed_campaigns_tanpa_pembatasan_memakai_seluruh_env(monkeypatch):
    monkeypatch.setattr(col, "collection_campaigns_from_env", lambda: frozenset({"collection"}))
    monkeypatch.setattr(col, "effective_campaigns_for", lambda db, u: None)
    assert col._allowed_campaigns(None, _user()) == ["collection"]


def test_list_ditolak_tanpa_capability(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: False)
    with pytest.raises(HTTPException) as exc:
        col.list_collection_results(db=None, current_user=_user())
    assert exc.value.status_code == 403


def test_detail_campaign_bukan_collection_404(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(col.crud, "get_result", lambda db, rid: SimpleNamespace(
        id=rid, campaign="Cashline", status="done", source_files=[], uploaded_at=None,
        completed_at=None, processing_sec=None, error_message=None, current_stage=None))
    monkeypatch.setattr(col, "ensure_can_view_result", lambda db, u, r: None)
    monkeypatch.setattr(col, "_allowed_campaigns", lambda db, u: ["collection"])
    with pytest.raises(HTTPException) as exc:
        col.get_collection_result("r1", db=None, current_user=_user())
    assert exc.value.status_code == 404


def test_detail_done_mengembalikan_laporan_ternormalisasi(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(col.crud, "get_result", lambda db, rid: SimpleNamespace(
        id=rid, campaign="Collection", status="done", source_files=["1_a.pdf"], uploaded_at=None,
        completed_at=None, processing_sec=3.2, error_message=None, current_stage="tandai_selesai"))
    monkeypatch.setattr(col, "ensure_can_view_result", lambda db, u, r: None)
    monkeypatch.setattr(col, "_allowed_campaigns", lambda db, u: ["collection"])
    monkeypatch.setattr(col.crud, "get_result_data", lambda db, rid: SimpleNamespace(
        result_json={"report_type": "collection_weighted",
                     "evaluation": {"scorecard_result": [{"weight": 4, "status": "PASS"}]}}))
    out = col.get_collection_result("r1", db=None, current_user=_user())
    assert out["report"]["ai_score_phase_2"] == 4
    assert out["report"]["ai_status"] == "PASS"
    assert out["source_files"] == ["1_a.pdf"]
