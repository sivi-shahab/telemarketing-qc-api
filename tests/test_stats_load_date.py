"""Statistics memakai ``load_date`` App C TERAKHIR sebagai tanggal tiket (20 Oktober 2026).

Pasangan ``test_results_filter_load_date.py``: filter tanggal & grafik Statistics
harus memilih tiket dan tanggal yang SAMA dengan menu Results. Tiket tanpa baris di
``ticket_load_dates`` memakai aturan lama (Tanggal Agree -> generated_at -> WIB
uploaded_at). Tenggat H+2 (``_submit_time_map``) TETAP Tanggal Agree.

``crud.cashline_agent_index`` di-stub: indeks aslinya membaca seluruh result prod dan
memanggil DWH untuk cid tanpa agent_id — lambat dan tidak deterministik.
"""
import uuid
from datetime import date, datetime

import pytest

from compliance import stats_aggregate as sa
from db import crud
from db.models import QcAssignment, Result

CAMPAIGN = "ZZ-TEST-STATS-LOAD-DATE"


def d(day):
    return date(2026, 10, day)


@pytest.fixture()
def index(monkeypatch):
    """``{ticket_id: submit_time}`` yang dibaca ``crud.cashline_agent_index``."""
    submit = {}
    monkeypatch.setattr(
        crud, "cashline_agent_index",
        lambda db: {t: {"agent_id": "zzagent", "submit_time": s} for t, s in submit.items()},
    )
    return submit


def _mk(db, index, ticket, submit=None, loads=(), status="done",
        generated_at=datetime(2026, 9, 1, 8, 0)):
    r = Result(
        id=uuid.uuid4(),
        campaign=CAMPAIGN,
        source_files=[f"{ticket}_20260101120000.pdf"],
        status=status,
        generated_at=generated_at,
        uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
    )
    db.add(r)
    if submit:
        index[ticket] = submit
    if loads:
        crud.upsert_ticket_load_dates(db, [(ticket, d(x), "X") for x in loads])
    db.flush()
    return r


def _spy_scanned(monkeypatch):
    """Tangkap result id yang dipindai — batch lookup appeal dipanggil tepat sesudah
    penyaringan tanggal di setiap jalur Statistics."""
    seen = []
    real = crud.error_code_appeals_for_results

    def spy(db_, ids):
        seen.append(set(ids))
        return real(db_, ids)

    monkeypatch.setattr(crud, "error_code_appeals_for_results", spy)
    return seen


def test_ticketdates_single_dan_window():
    td = sa.TicketDates((d(10), d(15)), d(1))
    assert td.single() == d(15)
    assert td.in_window(d(12), d(17))
    assert sa.TicketDates((), d(14)).in_window(d(12), d(17))
    multi = sa.TicketDates((d(14), d(16), d(19)), None)
    assert multi.single() == d(19)
    assert not multi.in_window(d(12), d(17))
    assert not sa.TicketDates((), None).in_window(None, None)
    assert sa.TicketDates((d(12),), None).in_window(d(12), None)
    assert sa.TicketDates((d(12),), None).in_window(None, d(12))


def test_failure_reasons_filter_load_terakhir(db, index, monkeypatch):
    # Semua tiket "evaluable" supaya ``total_submissions`` = jumlah tiket di jendela.
    monkeypatch.setattr(sa, "_adjusted_evaluation", lambda *a, **k: {})
    seen = _spy_scanned(monkeypatch)
    a = _mk(db, index, "ZZSLD1", submit="2026-10-10 09:00:00", loads=(15,))  # masuk
    b = _mk(db, index, "ZZSLD2", submit="2026-10-15 09:00:00")               # masuk (aturan lama)
    _mk(db, index, "ZZSLD3", submit="2026-10-14 09:00:00", loads=(10,))      # keluar
    c = _mk(db, index, "ZZSLD4", submit="2026-10-14 09:00:00", loads=(14, 19))  # keluar
    out = sa.compute_failure_reasons(db, campaign=CAMPAIGN, date_start=d(12), date_end=d(17))
    assert out["total_submissions"] == 2
    assert seen[-1] == {str(a.id), str(b.id)}
    # Sub-tab Hierarki Based: jendela yang sama memilih tiket yang sama.
    sa.compute_failure_reasons_hierarchy(
        db, campaign=CAMPAIGN, date_start=d(12), date_end=d(17))
    assert seen[-1] == {str(a.id), str(b.id)}
    # Load terakhir 19 Okt -> hanya ZZSLD4 di jendela 18-19.
    sa.compute_failure_reasons_hierarchy(
        db, campaign=CAMPAIGN, date_start=d(18), date_end=d(19))
    assert seen[-1] == {str(c.id)}


def test_timeseries_bucket_load_terakhir(db, index):
    _mk(db, index, "ZZSLD5", submit="2026-10-13 09:00:00", loads=(14, 16))
    out = sa.compute_ai_status_timeseries(
        db, ["ZZSLD5"], None, "daily", "2026-10-12", "2026-10-17")
    filled = {b["key"]: b["submissions"] for b in out["buckets"] if b["submissions"]}
    assert filled == {"2026-10-16": 1}


def test_timeseries_anchor_load_terakhir(db, index):
    _mk(db, index, "ZZSLD6", submit="2026-10-01 09:00:00", loads=(5, 19))
    out = sa.compute_ai_status_timeseries(db, ["ZZSLD6"], None, "daily", None, None)
    assert out["end"] == "2026-10-19"


def test_submit_time_map_tidak_berubah(db, index):
    r = _mk(db, index, "ZZSLD7", submit="2026-10-10 11:52:32", loads=(15,))
    assert sa._submit_time_map(db, [r]) == {r.id: "2026-10-10 11:52:32"}


def test_ticket_chart_dates_load_terakhir(db, index):
    _mk(db, index, "ZZSLD8", submit="2026-10-01 09:00:00", loads=(10, 15))
    _mk(db, index, "ZZSLD9", submit="2026-10-03 09:00:00")
    _mk(db, index, "ZZSLDA", generated_at=datetime(2026, 10, 4, 22, 58))
    assert sa.ticket_chart_dates(db, ["ZZSLD8", "ZZSLD9", "ZZSLDA"]) == {
        "ZZSLD8": d(15), "ZZSLD9": d(3), "ZZSLDA": d(4),
    }


def test_qc_productivity_filter_load_terakhir(db, index):
    _mk(db, index, "ZZSLDB", submit="2026-10-01 09:00:00", loads=(10, 15))
    _mk(db, index, "ZZSLDC", submit="2026-10-14 09:00:00", loads=(14, 19))
    db.add_all([
        QcAssignment(ticket_id="ZZSLDB", qc_username="zzqc-load-1"),
        QcAssignment(ticket_id="ZZSLDC", qc_username="zzqc-load-2"),
    ])
    db.flush()
    rows = {
        r["qc_username"]: r["assigned"]
        for r in crud.qc_performance_rows(
            db, campaign=CAMPAIGN, date_start=d(12), date_end=d(17))
    }
    assert rows["zzqc-load-1"] == 1
    assert rows["zzqc-load-2"] == 0


def test_stats_snapshot_filter_load_terakhir(db, index, monkeypatch):
    """Tab Failure Rate (pohon Hierarki) memakai jendela yang sama — tiket yang
    dipindai ditangkap dari batch lookup appeal tepat setelah penyaringan."""
    seen = _spy_scanned(monkeypatch)
    a = _mk(db, index, "ZZSLDD", submit="2026-10-10 09:00:00", loads=(15,))
    _mk(db, index, "ZZSLDE", submit="2026-10-14 09:00:00", loads=(14, 19))
    b = _mk(db, index, "ZZSLDF", submit="2026-10-14 09:00:00")
    sa.compute_stats_snapshot(
        db, customer_ids=["ZZSLDD", "ZZSLDE", "ZZSLDF"], roster_uids=set(),
        date_start=d(12), date_end=d(17))
    assert seen[0] == {str(a.id), str(b.id)}


def test_signature_ikut_ticket_load_dates(db):
    """Load_date baru menggeser tanggal tiket -> snapshot harus gugur. Upsert ulang
    baris yang sama (hanya synced_at berubah) TIDAK boleh menggugurkannya."""
    crud.upsert_ticket_load_dates(db, [("ZZSLDG", d(15), "X")])
    db.flush()
    before = crud._stats_signature(db)
    crud.upsert_ticket_load_dates(db, [("ZZSLDG", d(15), "X")])
    db.flush()
    assert crud._stats_signature(db) == before
    crud.upsert_ticket_load_dates(db, [("ZZSLDG", d(16), "X")])
    db.flush()
    assert crud._stats_signature(db) != before
