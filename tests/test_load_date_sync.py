"""Sinkron load_date App C -> ``ticket_load_dates`` (20 Oktober 2026).

``fetch_all`` di-monkeypatch — test TIDAK pernah memanggil App C sungguhan. Tabelnya
dibuat fixture ``db`` di dalam transaksi yang di-rollback; ``sync_dates`` meng-commit
per tanggal, tapi commit itu hanya sampai savepoint fixture.
"""
import uuid
from datetime import date

import pytest

from db import crud
from services import load_date_sync, tickets_daily


def _tid():
    return "T" + uuid.uuid4().hex[:10]


def _page(items):
    return {"mode": "load_date", "load_date": None, "items": items,
            "total": len(items), "truncated": False}


def test_sync_menyimpan_semua_baris(db, monkeypatch):
    a, b = _tid(), _tid()
    d = date(2026, 10, 15)
    calls = []

    def fake(**kw):
        calls.append(kw)
        return _page([{"id": a, "load_date": "2026-10-15", "campaign": "Cashline"},
                      {"id": b, "load_date": "2026-10-15"}])

    monkeypatch.setattr(tickets_daily, "fetch_all", fake)
    assert load_date_sync.sync_dates(db, [d]) == {d: 2}
    assert calls == [{"load_date": "2026-10-15", "max_pages": 200}]
    got = crud.load_dates_by_ticket(db, [a, b])
    assert got == {a: [d], b: [d]}


def test_app_c_error_tidak_menghapus(db, monkeypatch):
    old, new = _tid(), _tid()
    d1, d2 = date(2026, 10, 14), date(2026, 10, 15)
    crud.upsert_ticket_load_dates(db, [(old, d1, "Cashline")])
    db.commit()

    def fake(**kw):
        if kw["load_date"] == "2026-10-14":
            raise tickets_daily.TicketsDailyError("App C mati")
        return _page([{"id": new, "load_date": "2026-10-15"}])

    monkeypatch.setattr(tickets_daily, "fetch_all", fake)
    result = load_date_sync.sync_dates(db, [d1, d2])
    assert result == {d2: 1}
    assert crud.load_dates_by_ticket(db, [old, new]) == {old: [d1], new: [d2]}


def test_item_tanpa_id_dibuang(db, monkeypatch):
    ok = _tid()
    monkeypatch.setattr(tickets_daily, "fetch_all", lambda **kw: _page([
        {"id": ok, "load_date": "2026-10-15"},
        {"id": "", "load_date": "2026-10-15"},
        {"load_date": "2026-10-15"},
        {"id": _tid(), "load_date": None},
    ]))
    d = date(2026, 10, 15)
    assert load_date_sync.sync_dates(db, [d]) == {d: 1}


def test_truncated_diberi_peringatan(db, monkeypatch, caplog):
    page = _page([{"id": _tid(), "load_date": "2026-10-15"}])
    page["truncated"] = True
    monkeypatch.setattr(tickets_daily, "fetch_all", lambda **kw: page)
    with caplog.at_level("WARNING"):
        load_date_sync.sync_dates(db, [date(2026, 10, 15)])
    assert any("terpotong" in r.message for r in caplog.records)


def test_recent_dates():
    assert load_date_sync.recent_dates(date(2026, 10, 19), 3) == [
        date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)]


def test_satu_tanggal_rusak_tidak_menghentikan_yang_lain(db, monkeypatch):
    ok1, ok2 = _tid(), _tid()
    d1, d2, d3 = date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)

    def fake(**kw):
        if kw["load_date"] == "2026-10-17":  # tanggal tertua: load_date rusak
            return _page([{"id": _tid(), "load_date": "bukan-tanggal"}])
        return _page([{"id": ok1 if kw["load_date"] == "2026-10-18" else ok2,
                       "load_date": kw["load_date"]}])

    monkeypatch.setattr(tickets_daily, "fetch_all", fake)
    result = load_date_sync.sync_dates(db, [d1, d2, d3])
    assert result == {d2: 1, d3: 1}
    assert d1 not in result
    assert list(result) == [d3, d2]  # terbaru dulu
    assert crud.load_dates_by_ticket(db, [ok1, ok2]) == {ok1: [d2], ok2: [d3]}
