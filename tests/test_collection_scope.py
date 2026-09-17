"""Cakupan tiket Collection: daftar, detail, dan PDF transkrip harus SEPAKAT.

Sebelumnya daftar hanya menyaring campaign, sedangkan detail & PDF memakai aturan
Cashline (``ensure_can_view_result``): QC Collection (``qc_assigned``, tanpa alur
Assign Ticket) melihat tiketnya di daftar tetapi ditolak 403 di setiap detail/PDF,
dan login sales justru melihat seluruh baris Collection di daftar.

Bagian DB memakai fixture ``db`` (transaksi yang selalu di-rollback) dengan user
dan tiket sungguhan — sengaja tanpa monkeypatch gerbang cakupan, karena justru
monkeypatch itulah yang dulu menyembunyikan bug ini.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import qc_scope
from api.routers import collection as col
from api.routers import transcript as tr
from compliance.collection_report import REPORT_TYPE
from db.models import Result, ResultData, User, UserCampaign

CAMPAIGN = "ZZScopeCollection"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", f"{CAMPAIGN}, ZZScopeLain")


def _user(db, role, campaigns=()):
    tag = uuid.uuid4().hex[:8]
    user = User(username=f"uji-scope-{tag}", email=f"uji-scope-{tag}@example.invalid",
                hashed_password="x", role=role)
    db.add(user)
    db.flush()
    for c in campaigns:
        db.add(UserCampaign(user_id=user.id, campaign=c))
    db.flush()
    return user


def _result(db, campaign=CAMPAIGN, uploaded_by_role=None):
    r = Result(id=uuid.uuid4(), campaign=campaign, status="done",
               source_files=[f"ZZ{uuid.uuid4().hex[:8]}_call.pdf"],
               uploaded_at=datetime(2026, 9, 17, 3, 0), uploaded_by_role=uploaded_by_role)
    db.add(r)
    db.flush()
    db.add(ResultData(result_id=r.id, result_json={
        "report_type": REPORT_TYPE,
        "evaluation": {"scorecard_result": [{"weight": 10, "status": "SESUAI", "item_code": "A"}]},
    }))
    db.flush()
    return r


def _list(db, user):
    out = col.list_collection_results(
        status=None, ai_status=None, ticket_id=None, date_start=None, date_end=None,
        page=1, limit=100, db=db, current_user=user)
    return {row["result_id"] for row in out["items"]}


def _pdf_gate(db, user, result):
    """Status gerbang /transcript_pdf tanpa MinIO: nama berkas sengaja bukan milik
    result, jadi 404 "bukan bagian" = gerbang cakupan SUDAH dilewati."""
    try:
        tr.transcript_pdf(str(result.id), filename="bukan-berkas-ini.pdf", db=db, current_user=user)
    except HTTPException as exc:
        if exc.status_code == 404 and "bukan bagian" in str(exc.detail):
            return "lolos"
        return exc.status_code
    return "lolos"


# --------------------------------------------------------------------------
# QC Collection (qc_assigned, user_campaigns = [Collection])
# --------------------------------------------------------------------------

def test_qc_collection_daftar_detail_dan_pdf_sepakat(db, env):
    qc = _user(db, "qc", [CAMPAIGN])
    r = _result(db)

    assert str(r.id) in _list(db, qc)
    detail = col.get_collection_result(str(r.id), db=db, current_user=qc)
    assert detail["result_id"] == str(r.id)
    assert detail["report"]["ai_status"] == "PASS"
    assert _pdf_gate(db, qc, r) == "lolos"
    assert qc_scope.collection_can_view(db, qc, r) is True


def test_qc_collection_tidak_melihat_upload_qc_support(db, env):
    qc = _user(db, "qc", [CAMPAIGN])
    r = _result(db, uploaded_by_role="qc_support")
    assert str(r.id) not in _list(db, qc)
    with pytest.raises(HTTPException) as exc:
        col.get_collection_result(str(r.id), db=db, current_user=qc)
    assert exc.value.status_code == 403
    assert _pdf_gate(db, qc, r) == 403


def test_detail_tiket_cashline_404_bukan_403(db, env):
    qc = _user(db, "qc", [CAMPAIGN])
    cash = _result(db, campaign="ZZScopeCashline")
    with pytest.raises(HTTPException) as exc:
        col.get_collection_result(str(cash.id), db=db, current_user=qc)
    assert exc.value.status_code == 404


def test_pdf_tiket_cashline_tetap_aturan_lama(db, env):
    """Tiket non-Collection tetap lewat ``ensure_can_view_result``: QC tanpa
    assignment ditolak seperti sebelumnya."""
    qc = _user(db, "qc", ["ZZScopeCashline"])
    cash = _result(db, campaign="ZZScopeCashline")
    assert _pdf_gate(db, qc, cash) == 403


# --------------------------------------------------------------------------
# Cakupan lain
# --------------------------------------------------------------------------

def test_cakupan_all_tanpa_batas_campaign_melihat_collection(db, env):
    tlqc = _user(db, "team_leader_qc")
    r = _result(db)
    support = _result(db, uploaded_by_role="qc_support")
    ids = _list(db, tlqc)
    assert str(r.id) in ids and str(support.id) not in ids
    assert col.get_collection_result(str(r.id), db=db, current_user=tlqc)["result_id"] == str(r.id)
    assert _pdf_gate(db, tlqc, r) == "lolos"


def test_qc_support_hanya_melihat_upload_qc_support(db, env):
    user = _user(db, "qc_support", [CAMPAIGN])
    own = _result(db, uploaded_by_role="qc_support")
    other = _result(db)
    assert qc_scope.collection_can_view(db, user, own) is True
    assert qc_scope.collection_can_view(db, user, other) is False
    assert _pdf_gate(db, user, own) == "lolos"
    assert _pdf_gate(db, user, other) == 403
    scope = qc_scope.collection_view_scope(db, user)
    assert scope == {"campaigns": [CAMPAIGN.casefold()], "uploaded_by_role": "qc_support"}


@pytest.mark.parametrize("role", ["sales_agent", "team_leader", "area_manager"])
def test_cakupan_sales_tidak_melihat_collection(db, env, role, monkeypatch):
    # Roster sales tidak relevan: cakupan sales ditolak sebelum campaign dibaca.
    import sales_lookup
    monkeypatch.setattr(sales_lookup, "roster_campaigns_for", lambda db, u, s: [CAMPAIGN])
    user = _user(db, role, [CAMPAIGN])
    r = _result(db)
    assert qc_scope.collection_view_scope(db, user) is None
    assert qc_scope.collection_can_view(db, user, r) is False
    assert _pdf_gate(db, user, r) == 403
    # Daftar lewat crud dengan cakupan yang ditolak = kosong.
    scope = col._view_scope(db, user)
    assert scope["campaigns"] == []


# --------------------------------------------------------------------------
# Unit (tanpa DB)
# --------------------------------------------------------------------------

def _patch_scope(monkeypatch, *, env_value, scope, effective):
    from api import rbac
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", env_value)
    monkeypatch.setattr(rbac, "data_scope_for", lambda db, u: scope)
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: effective)


def _fake(campaign=CAMPAIGN, uploaded_by_role=None):
    return SimpleNamespace(campaign=campaign, uploaded_by_role=uploaded_by_role,
                           source_files=["T1_a.pdf"])


def test_env_kosong_tidak_ada_yang_terlihat(monkeypatch):
    _patch_scope(monkeypatch, env_value="", scope="all", effective=None)
    assert qc_scope.collection_view_scope(None, object()) is None
    assert qc_scope.collection_can_view(None, object(), _fake()) is False


def test_batas_campaign_kosong_tidak_ada_yang_terlihat(monkeypatch):
    _patch_scope(monkeypatch, env_value=CAMPAIGN, scope="qc_assigned", effective=[])
    assert qc_scope.collection_view_scope(None, object())["campaigns"] == []
    assert qc_scope.collection_can_view(None, object(), _fake()) is False


def test_batas_campaign_diiris_dengan_env(monkeypatch):
    _patch_scope(monkeypatch, env_value=f"{CAMPAIGN},Lain", scope="all",
                 effective=[" zzscopecollection ", "Cashline"])
    assert qc_scope.collection_view_scope(None, object()) == {
        "campaigns": [CAMPAIGN.casefold()], "exclude_uploaded_by_role": "qc_support"}


def test_cakupan_tak_dikenal_ditolak(monkeypatch):
    _patch_scope(monkeypatch, env_value=CAMPAIGN, scope="cakupan_baru", effective=None)
    assert qc_scope.collection_can_view(None, object(), _fake()) is False
