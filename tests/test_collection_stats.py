"""Stats Collection: agregasi murni atas laporan berbobot tersimpan.

Tanpa DB — ``rows`` adalah pasangan (result, result_json) tiruan.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers import stats as st
from api.routers import stats_collection as sc
from compliance.collection_report import REPORT_TYPE
from compliance.collection_stats import aggregate_collection_stats
from db import crud
from db.models import Result, ResultData, User, UserCampaign


def _res(status="done", generated_at=None, uploaded_at=datetime(2026, 9, 17, 3, 0)):
    return SimpleNamespace(status=status, source_files=["T1_a.pdf"],
                           generated_at=generated_at, uploaded_at=uploaded_at)


def _rep(*, agent="Tiwi", items=None, cats=None, critical=None, codes=None, commit="NOT_STATED", maximum=10):
    ev = {
        "agent_name": agent,
        "maximum_score": maximum,
        "scorecard_result": items if items is not None else [
            {"item_code": "A", "requirement": "salam", "category": "Pembukaan", "weight": 10, "status": "SESUAI"}],
        "category_summary": cats or [],
        "critical_compliance_check": critical or {"status": "PASS", "checked_items": []},
        "error_codes": codes or [],
        "commitment_status": {"status": commit},
    }
    return {"report_type": REPORT_TYPE, "evaluation": ev}


def test_input_kosong_pembagi_nol_none():
    out = aggregate_collection_stats([])
    assert out["kpi"] == {"total": 0, "done": 0, "in_progress": 0, "failed": 0, "with_report": 0,
                          "without_report": 0, "pass": 0, "fail": 0, "pass_rate": None,
                          "avg_score_percent": None}
    assert out["daily"] == [] and out["categories"] == [] and out["agents"] == []
    assert out["critical"] == {"pass": 0, "fail": 0, "unavailable": 0, "items": []}
    assert out["commitment"] == {"COMMITTED_TO_PAY": 0, "PARTIAL_COMMITMENT": 0, "DISPUTE": 0,
                                 "REFUSED": 0, "NOT_STATED": 0}


def test_kpi_status_dan_pass_fail():
    lulus = _rep()
    gagal = _rep(items=[{"item_code": "A", "weight": 10, "status": "BELUM_SESUAI", "category": "Pembukaan"}])
    rows = [(_res(), lulus), (_res(), gagal), (_res("pending"), None), (_res("processing"), None),
            (_res("failed"), None), (_res(), {"evaluation": {}})]
    k = aggregate_collection_stats(rows)["kpi"]
    assert (k["total"], k["done"], k["in_progress"], k["failed"]) == (6, 3, 2, 1)
    assert (k["with_report"], k["without_report"], k["pass"], k["fail"]) == (2, 1, 1, 1)
    assert k["pass_rate"] == 50.0
    assert k["avg_score_percent"] == 50.0


def test_tren_harian_generated_at_lalu_uploaded_wib():
    rows = [
        (_res(generated_at=datetime(2026, 9, 15, 23, 0)), _rep()),
        # 16 Sep 18:30 UTC = 17 Sep 01:30 WIB
        (_res(uploaded_at=datetime(2026, 9, 16, 18, 30)), _rep()),
    ]
    assert aggregate_collection_stats(rows)["daily"] == [
        {"date": "2026-09-15", "pass": 1, "fail": 0},
        {"date": "2026-09-17", "pass": 1, "fail": 0},
    ]


def test_kategori_dan_indikator():
    items = [
        {"item_code": "B", "requirement": "identitas", "category": "Pembukaan", "weight": 5, "status": "BELUM_SESUAI"},
        {"item_code": "A", "requirement": "salam", "category": "Pembukaan", "weight": 5, "status": "SESUAI"},
    ]
    cats = [{"category": "Pembukaan", "total_weight": 10, "earned_score": 5, "category_result": "FAIL"},
            {"category": "Penutup", "total_weight": 4, "earned_score": 4, "category_result": "??"}]
    out = aggregate_collection_stats([(_res(), _rep(items=items, cats=cats)),
                                      (_res(), _rep(items=items[:1], cats=cats[:1]))])
    assert out["categories"] == [
        {"category": "Pembukaan", "reports": 2, "avg_percent": 50.0, "fail": 2, "fail_rate": 100.0, "unavailable": 0},
        {"category": "Penutup", "reports": 1, "avg_percent": 100.0, "fail": 0, "fail_rate": 0.0, "unavailable": 1},
    ]
    assert out["top_failed_indicators"] == [
        {"item_code": "B", "requirement": "identitas", "category": "Pembukaan", "belum_sesuai": 2, "rate": 100.0}]


def test_top_indikator_maksimal_sepuluh_urut_stabil():
    items = [{"item_code": f"I{n:02d}", "requirement": "r", "category": "C", "weight": 1, "status": "BELUM_SESUAI"}
             for n in range(12)]
    top = aggregate_collection_stats([(_res(), _rep(items=items))])["top_failed_indicators"]
    assert [t["item_code"] for t in top] == [f"I{n:02d}" for n in range(10)]


def test_critical_dan_error_code():
    crit_fail = {"status": "FAIL", "checked_items": [
        {"item_code": "K1", "requirement": "tidak mengancam", "status": "FAIL"},
        {"item_code": "K2", "requirement": "identitas", "status": "PASS"}]}
    codes = [{"error_code": "E02", "details_error": ""}, {"error_code": "E02", "details_error": "ancaman"},
             "E01", " - "]
    out = aggregate_collection_stats([
        (_res(), _rep(critical=crit_fail, codes=codes)),
        (_res(), _rep(critical={"verifikasi": True})),   # bentuk datar -> TIDAK_TERSEDIA
        (_res(), _rep()),
    ])
    assert out["critical"] == {"pass": 1, "fail": 1, "unavailable": 1,
                               "items": [{"item_code": "K1", "requirement": "tidak mengancam", "fail": 1}]}
    assert out["error_codes"] == [{"error_code": "E02", "count": 2, "example": "ancaman"},
                                  {"error_code": "E01", "count": 1, "example": ""}]


def test_agent_dikelompokkan_dan_tidak_disebut():
    gagal_items = [{"item_code": "A", "weight": 10, "status": "BELUM_SESUAI", "category": "C"}]
    rows = [(_res(), _rep(agent="Ibu  Tiwi")), (_res(), _rep(agent=" ibu tiwi")),
            (_res(), _rep(agent="Ibu Tiwi", items=gagal_items)), (_res(), _rep(agent=None)),
            (_res(), _rep(agent="Andi"))]
    agents = aggregate_collection_stats(rows)["agents"]
    assert agents[0] == {"agent": "Ibu Tiwi", "tickets": 3, "pass": 2, "fail": 1,
                         "pass_rate": 66.7, "avg_score_percent": 66.7}
    assert [a["agent"] for a in agents[1:]] == ["Andi", "Tidak disebut"]


def test_status_tak_dikenal_masuk_diproses_bucket_kpi_menjumlah():
    rows = [(_res(), _rep()), (_res("pending"), None), (_res("queued"), None), (_res(None), None),
            (_res("failed"), None)]
    k = aggregate_collection_stats(rows)["kpi"]
    assert (k["total"], k["done"], k["in_progress"], k["failed"]) == (5, 1, 3, 1)
    assert k["done"] + k["in_progress"] + k["failed"] == k["total"]


def test_critical_item_code_distrip_kosong_dan_strip_diabaikan():
    crit = {"status": "FAIL", "checked_items": [
        {"item_code": " K1 ", "requirement": "tidak mengancam", "status": "FAIL"},
        {"item_code": "K1", "requirement": "tidak mengancam", "status": "FAIL"},
        {"item_code": "", "requirement": "kosong", "status": "FAIL"},
        {"item_code": " - ", "requirement": "strip", "status": "FAIL"},
        {"requirement": "tanpa kode", "status": "FAIL"},
        {"item_code": None, "requirement": "null", "status": "FAIL"}]}
    out = aggregate_collection_stats([(_res(), _rep(critical=crit))])
    assert out["critical"]["fail"] == 1
    assert out["critical"]["items"] == [{"item_code": "K1", "requirement": "tidak mengancam", "fail": 2}]


def test_komitmen():
    rows = [(_res(), _rep(commit="COMMITTED_TO_PAY")), (_res(), _rep(commit="REFUSED")),
            (_res(), _rep(commit="aneh"))]
    c = aggregate_collection_stats(rows)["commitment"]
    assert (c["COMMITTED_TO_PAY"], c["REFUSED"], c["NOT_STATED"]) == (1, 1, 1)


CAMP = "ZZStatsCollection"


def _seed(db, *, status="done", campaign=CAMP, n_data=1, uploaded_by_role=None,
          uploaded_at=datetime(2026, 9, 17, 3, 0), result_json=None):
    r = Result(id=uuid.uuid4(), campaign=campaign, status=status, uploaded_by_role=uploaded_by_role,
               source_files=[f"ZS{uuid.uuid4().hex[:8]}_call.pdf"], uploaded_at=uploaded_at)
    db.add(r)
    db.flush()
    for _ in range(n_data):
        db.add(ResultData(result_id=r.id, result_json=_rep() if result_json is None else result_json))
    db.flush()
    return r


def test_stats_rows_semua_status_tanpa_duplikat(db):
    a = _seed(db, n_data=2)
    b = _seed(db, status="pending", n_data=0)
    _seed(db, campaign="ZZStatsCashline")
    rows = crud.collection_stats_rows(db, campaigns=[CAMP])
    ids = [str(r.id) for r, _ in rows]
    assert sorted(ids) == sorted([str(a.id), str(b.id)])


def test_stats_rows_sepakat_dengan_daftar(db):
    for _ in range(3):
        _seed(db)
    _seed(db, uploaded_by_role="qc_support")
    kw = {"campaigns": [CAMP], "exclude_uploaded_by_role": "qc_support"}
    rows = crud.collection_stats_rows(db, **kw)
    _, total = crud.list_collection_results(db, limit=100, **kw)
    assert len(rows) == total == 3


def test_stats_rows_filter_tanggal_wib(db):
    _seed(db, uploaded_at=datetime(2026, 9, 16, 18, 30))  # 17 Sep WIB
    from datetime import date
    assert len(crud.collection_stats_rows(db, campaigns=[CAMP], date_start=date(2026, 9, 17),
                                          date_end=date(2026, 9, 17))) == 1
    assert crud.collection_stats_rows(db, campaigns=[CAMP], date_start=date(2026, 9, 16),
                                      date_end=date(2026, 9, 16)) == []


def test_filter_ai_status_daftar_sepakat_dengan_kpi_stats(db):
    """Tiket done tanpa laporan berbobot tidak ikut filter PASS/FAIL daftar Collection
    Results — sama dengan Stats yang menghitungnya sebagai ``without_report``."""
    gagal = _rep(items=[{"item_code": "A", "weight": 10, "status": "BELUM_SESUAI", "category": "Pembukaan"}])
    _seed(db)
    _seed(db, result_json=gagal)
    _seed(db, result_json={"evaluation": {}})  # done, bukan laporan berbobot
    kw = {"campaigns": [CAMP]}
    kpi = aggregate_collection_stats(crud.collection_stats_rows(db, **kw))["kpi"]
    _, fail_total = crud.list_collection_results(db, ai_status="FAIL", limit=100, **kw)
    _, pass_total = crud.list_collection_results(db, ai_status="PASS", limit=100, **kw)
    assert kpi["without_report"] == 1
    assert fail_total == kpi["fail"] == 1
    assert pass_total == kpi["pass"] == 1


def test_stats_rows_campaign_kosong(db):
    assert crud.collection_stats_rows(db, campaigns=[]) == []


# --------------------------------------------------------------------------
# Endpoint GET /stats/collection + gerbang Stats Cashline
# --------------------------------------------------------------------------
# ``_user`` ditiru dari ``tests/test_collection_scope.py`` — user + UserCampaign
# sungguhan, karena ``effective_campaigns_for`` membaca dari tabel itu.

def _user(db, role, campaigns=()):
    tag = uuid.uuid4().hex[:8]
    user = User(username=f"uji-stats-{tag}", email=f"uji-stats-{tag}@example.invalid",
                hashed_password="x", role=role)
    db.add(user)
    db.flush()
    for c in campaigns:
        db.add(UserCampaign(user_id=user.id, campaign=c))
    db.flush()
    return user


@pytest.fixture()
def env_on(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", CAMP)


def _call(db, user, **kw):
    return sc.collection_stats(date_start=kw.get("date_start"), date_end=kw.get("date_end"),
                               campaign=kw.get("campaign"), db=db, current_user=user)


def test_qc_collection_only_sepakat_dengan_daftar(db, env_on):
    user = _user(db, "qc", [CAMP])
    for _ in range(2):
        _seed(db)
    out = _call(db, user)
    from api.routers import collection as col
    listed = col.list_collection_results(status=None, ai_status=None, ticket_id=None, date_start=None,
                                         date_end=None, page=1, limit=100, db=db, current_user=user)
    assert out["kpi"]["total"] == listed["total"] == 2
    assert out["kpi"]["pass"] == 2


def test_login_sales_ditolak(db, env_on):
    user = _user(db, "sales_agent", [CAMP])
    with pytest.raises(HTTPException) as exc:
        _call(db, user)
    assert exc.value.status_code == 403


def test_env_kosong_ditolak(db, monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    with pytest.raises(HTTPException) as exc:
        _call(db, _user(db, "admin"))
    assert exc.value.status_code == 403


def test_campaign_di_luar_cakupan_payload_nol(db, env_on):
    _seed(db)
    out = _call(db, _user(db, "admin"), campaign="ZZLain")
    assert out["kpi"]["total"] == 0


def test_stats_cashline_menolak_collection_only(db, env_on):
    with pytest.raises(HTTPException) as exc:
        st.stats_overview(db=db, current_user=_user(db, "qc", [CAMP]))
    assert exc.value.status_code == 403


def test_stats_cashline_tetap_melayani_admin(db, env_on):
    assert "overview" in st.stats_overview(db=db, current_user=_user(db, "admin"))


# --------------------------------------------------------------------------
# Stats Collection == menu Collection Results (keputusan 17 September 2026)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role,campaigns", [
    ("admin", ()),
    ("demo", ()),
    ("spq_head", ()),  # non-Admin tanpa batas campaign
    ("qc", [CAMP]),  # QC Collection-only
    ("qc", [CAMP, "ZZStatsCashline"]),  # QC campuran
    ("qc", ["ZZStatsCashline"]),  # QC Cashline-only
    ("sales_agent", [CAMP, "ZZStatsCashline"]),  # sales campuran
], ids=["admin", "demo", "spq_head_tanpa_campaign", "qc_collection_only",
        "qc_campuran", "qc_cashline_only", "sales_campuran"])
def test_stats_collection_sepakat_dengan_menu_collection_results(db, env_on, role, campaigns):
    """``stats_views_for`` memberi "collection" persis untuk login yang juga
    mendapat MENU_COLLECTION_RESULTS di ``permissions_for`` — keduanya memakai
    ``collection_results_visible`` yang sama (Task 7)."""
    from api.permissions import MENU_COLLECTION_RESULTS, MENU_STATS
    from api.rbac import permissions_for, stats_views_for

    user = _user(db, role, campaigns)
    perms = permissions_for(db, user)
    assert MENU_STATS in perms
    views = stats_views_for(db, user)
    assert ("collection" in views) == (MENU_COLLECTION_RESULTS in perms)
