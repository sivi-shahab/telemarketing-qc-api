"""Tiket Collection tidak boleh mengalir ke permukaan Cashline.

Menu Collection Results punya format laporan sendiri. Tanpa pengecualian, tiketnya
ikut tampil di menu Transcripts, masuk antrean Auto Assign (padahal Assign Ticket
dicabut untuk Collection), dan dihitung sebagai tiket Cashline di Statistics.
``COLLECTION_CAMPAIGNS`` kosong harus mempertahankan perilaku lama persis.

Memakai fixture ``db`` (transaksi yang selalu di-rollback).
"""
import uuid
from datetime import datetime

import pytest

from compliance import stats_aggregate as sa
from db import crud
from db.models import Result

COLL = "ZZExclCollection"
CASH = "ZZExclCashline"


def _seed(db, campaign, status="done"):
    r = Result(id=uuid.uuid4(), campaign=campaign, status=status,
               source_files=[f"ZX{uuid.uuid4().hex[:8]}_call.pdf"],
               uploaded_at=datetime.utcnow())
    db.add(r)
    db.flush()
    return r


@pytest.fixture()
def seeded(db):
    return _seed(db, COLL), _seed(db, CASH)


@pytest.fixture()
def env_on(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", f" {COLL.upper()} ")


@pytest.fixture()
def env_off(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")


def _ids(results):
    return {str(r.id) for r in results}


# --- Transcripts -----------------------------------------------------------

def test_crud_list_transcripts_bisa_mengecualikan_campaign(db, seeded):
    kol, cash = seeded
    rows, _ = crud.list_transcripts(db, limit=1_000_000, exclude_campaigns=[COLL])
    ids = {r["result_id"] for r in rows}
    assert str(cash.id) in ids and str(kol.id) not in ids


def _route_list_transcripts(db, user):
    from api.routers import transcript as tr
    out = tr.list_transcripts(status=None, campaign=None, ticket_id=None, ai_status=None,
                              page=1, limit=100, db=db, current_user=user)
    return {i.result_id if hasattr(i, "result_id") else i["result_id"] for i in out.items}


def _all_scope_user(monkeypatch):
    from types import SimpleNamespace
    from api.routers import transcript as tr
    monkeypatch.setattr(tr, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(tr, "data_scope_for", lambda db, u: "all")
    monkeypatch.setattr(tr, "scoped_customer_ids", lambda db, u: None)
    return SimpleNamespace(id=None, role="admin", username="uji")


def test_menu_transcripts_mengecualikan_collection(db, seeded, env_on, monkeypatch):
    kol, cash = seeded
    ids = _route_list_transcripts(db, _all_scope_user(monkeypatch))
    # Halaman pertama diurutkan uploaded_at desc; kedua baris uji paling baru.
    assert str(cash.id) in ids and str(kol.id) not in ids


def test_menu_transcripts_env_kosong_tidak_berubah(db, seeded, env_off, monkeypatch):
    kol, cash = seeded
    ids = _route_list_transcripts(db, _all_scope_user(monkeypatch))
    assert str(cash.id) in ids and str(kol.id) in ids


# --- Auto Assign -----------------------------------------------------------

def _pool(db, monkeypatch):
    from api.routers import qc_assignment as qa
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: None)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: None)
    ticket_ids, _pool = qa._auto_assign_pool(db, object())
    return set(ticket_ids)


def test_pool_auto_assign_mengecualikan_collection(db, seeded, env_on, monkeypatch):
    kol, cash = seeded
    tickets = _pool(db, monkeypatch)
    assert cash.source_files[0].split("_")[0] in tickets
    assert kol.source_files[0].split("_")[0] not in tickets


def test_pool_auto_assign_env_kosong_tidak_berubah(db, seeded, env_off, monkeypatch):
    kol, cash = seeded
    tickets = _pool(db, monkeypatch)
    assert kol.source_files[0].split("_")[0] in tickets


# --- Statistics ------------------------------------------------------------

def test_stats_done_results_query_mengecualikan_collection(db, seeded, env_on):
    kol, cash = seeded
    ids = _ids(sa.done_results_query(db).all())
    assert str(cash.id) in ids and str(kol.id) not in ids
    # Memilih campaign Collection secara eksplisit pun tidak memunculkannya.
    assert sa.done_results_query(db, campaign=COLL).all() == []


def test_stats_done_results_query_env_kosong_tidak_berubah(db, seeded, env_off):
    kol, cash = seeded
    ids = _ids(sa.done_results_query(db).all())
    assert {str(cash.id), str(kol.id)} <= ids


def test_stats_get_stats_dan_harian_mengecualikan_collection(db, env_on, monkeypatch):
    tickets = []
    for campaign in (COLL, COLL, CASH):
        tickets.append(_seed(db, campaign, status="pending"))
    cids = [t.source_files[0].split("_")[0] for t in tickets]

    assert crud.get_stats(db, customer_ids=cids)["pending"] == 1
    days = crud.get_daily_stats(db, customer_ids=cids)
    assert sum(d["pending"] for d in days) == 1

    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    assert crud.get_stats(db, customer_ids=cids)["pending"] == 3
    assert sum(d["pending"] for d in crud.get_daily_stats(db, customer_ids=cids)) == 3


def test_stats_scoped_overview_mengecualikan_collection(db, env_on):
    tickets = [_seed(db, COLL, status="pending"), _seed(db, CASH, status="pending")]
    cids = [t.source_files[0].split("_")[0] for t in tickets]
    assert sa.compute_scoped_overview(db, cids)["total_submissions"] == 1


def test_signature_snapshot_ikut_berubah_saat_env_collection_berubah(db, monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    off = crud._stats_signature(db)
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", COLL)
    on = crud._stats_signature(db)
    assert off != on


# --- Statistics: KPI berscope di compute_stats_snapshot --------------------

def _cid(result):
    return result.source_files[0].split("_", 1)[0]


def test_stats_snapshot_berscope_kpi_mengecualikan_collection(db, env_on):
    """Hitungan status berscope (kartu KPI) harus sepakat dengan daftar done-nya:
    tiket Collection tidak ikut dihitung sebagai tiket Cashline."""
    kol_done = _seed(db, COLL, status="done")
    kol_pending = _seed(db, COLL, status="pending")
    cash = _seed(db, CASH, status="done")
    ov = sa.compute_stats_snapshot(db, customer_ids=[_cid(kol_done), _cid(kol_pending), _cid(cash)])["overview"]
    assert ov["total_submissions"] == 1
    assert ov["done"] == 1
    assert ov["pending"] == 0


def test_stats_snapshot_berscope_env_kosong_tidak_berubah(db, env_off):
    kol = _seed(db, COLL, status="pending")
    cash = _seed(db, CASH, status="done")
    ov = sa.compute_stats_snapshot(db, customer_ids=[_cid(kol), _cid(cash)])["overview"]
    assert ov["total_submissions"] == 2
    assert ov["pending"] == 1 and ov["done"] == 1
