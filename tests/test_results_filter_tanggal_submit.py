"""Filter tanggal Results = Tanggal Submit (26 Oktober 2026).

Tanggal tiket = ``submit_time`` di snapshot ``reference_data.cashline`` evaluasi
terbaru, lalu generated_at, lalu WIB uploaded_at (``crud._series_date_expr``).
``load_date`` App C (dasar 20-26 Oktober) TIDAK lagi dibaca: tanggal itu tidak
tertulis di layar maupun export, sehingga baris export tampak di luar rentang.

Export Tiket memakai rentang yang sama dan menulis SATU baris per Ticket ID dengan
kolom Tanggal Submit, supaya isi file sama dengan tabel Results.
"""
import uuid
from datetime import date, datetime

from db import crud
from db.models import Result, ResultData

CAMPAIGN = "ZZ-TEST-TGL-SUBMIT"


def _mk(db, ticket, submit_time=None, generated_at=datetime(2026, 9, 1, 8, 0),
        uploaded_at=datetime(2020, 1, 1, 0, 0, 0), status="done"):
    r = Result(
        id=uuid.uuid4(),
        campaign=CAMPAIGN,
        source_files=[f"{ticket}_20260101120000.pdf"],
        status=status,
        generated_at=generated_at,
        uploaded_at=uploaded_at,
    )
    db.add(r)
    db.flush()
    if submit_time is not None:
        db.add(ResultData(result_id=r.id, result_json={
            "reference_data": {"cashline": {"submit_time": submit_time}}}))
        db.flush()
    return r


def _total(db, start, end):
    _rows, total = crud.list_results(
        db, campaigns=[CAMPAIGN], date_start=start, date_end=end, page=1, limit=50
    )
    return total


def test_submit_time_menentukan_tanggal(db):
    _mk(db, "ZZTS1", "2026-10-20 12:32:26")
    assert _total(db, date(2026, 10, 20), date(2026, 10, 20)) == 1
    assert _total(db, date(2026, 10, 21), date(2026, 10, 22)) == 0


def test_load_date_diabaikan(db, ticket_load_dates_table):
    _mk(db, "ZZTS2", "2026-10-15 10:00:00")
    crud.upsert_ticket_load_dates(db, [("ZZTS2", date(2026, 10, 20), "X")])
    db.flush()
    assert _total(db, date(2026, 10, 20), date(2026, 10, 20)) == 0
    assert _total(db, date(2026, 10, 15), date(2026, 10, 15)) == 1


def test_tanpa_submit_time_pakai_generated_at(db):
    _mk(db, "ZZTS3", generated_at=datetime(2026, 10, 14, 8, 0))
    _mk(db, "ZZTS4", generated_at=datetime(2026, 10, 10, 8, 0))
    assert _total(db, date(2026, 10, 12), date(2026, 10, 17)) == 1  # hanya ZZTS3


def test_batas_inklusif_dan_satu_sisi(db):
    _mk(db, "ZZTS5", "2026-10-12 23:59:59")
    assert _total(db, date(2026, 10, 12), date(2026, 10, 17)) == 1
    assert _total(db, date(2026, 10, 12), None) == 1
    assert _total(db, None, date(2026, 10, 12)) == 1
    assert _total(db, date(2026, 10, 13), None) == 0


def test_export_tiket_satu_baris_per_tiket_dengan_tanggal_submit(db):
    """Clone JOB-3: dua baris Result untuk satu Ticket ID -> satu baris di file."""
    from compliance.stats_aggregate import compute_ticket_export

    _mk(db, "ZZTS6", "2026-10-20 12:32:26", status="pending",
        uploaded_at=datetime(2026, 10, 20, 5, 0))
    _mk(db, "ZZTS6", "2026-10-20 12:32:26", status="pending",
        uploaded_at=datetime(2026, 10, 20, 6, 0))
    _mk(db, "ZZTS7", generated_at=datetime(2026, 10, 21, 9, 24, 48), status="pending")
    rows, _ = crud.list_results(db, campaigns=[CAMPAIGN], date_start=date(2026, 10, 20),
                                date_end=date(2026, 10, 22), page=1, limit=50)
    assert len(rows) == 3

    data = compute_ticket_export(db, rows)
    assert ("tanggal_submit", "Tanggal Submit") in data["columns"]
    got = [(r["ticket_id"], r["tanggal_submit"]) for r in data["rows"]]
    assert got == [("ZZTS6", "2026-10-20 12:32:26"), ("ZZTS7", "2026-10-21 09:24:48")]


def test_export_tiket_pengajuan_ulang_pakai_tanggal_baris_yang_lolos_filter(db):
    """120559Qt9N (26 Okt 2026): clone 16 Okt ber-snapshot submit 16 Okt, clone
    21 Okt ber-snapshot 21 Okt. Rentang 20-22 hanya meloloskan clone baru; kolom
    Tanggal Submit harus tanggal clone itu, bukan nilai per tiket dari clone lama."""
    from compliance.stats_aggregate import compute_ticket_export

    _mk(db, "ZZTS8", "2026-10-16 16:36:03", status="pending",
        uploaded_at=datetime(2026, 10, 16, 12, 0))
    _mk(db, "ZZTS8", "2026-10-21 07:57:48", status="pending",
        uploaded_at=datetime(2026, 10, 21, 8, 0))
    rows, _ = crud.list_results(db, campaigns=[CAMPAIGN], date_start=date(2026, 10, 20),
                                date_end=date(2026, 10, 22), page=1, limit=50)
    assert len(rows) == 1
    data = compute_ticket_export(db, rows)
    assert [(r["ticket_id"], r["tanggal_submit"]) for r in data["rows"]] == [
        ("ZZTS8", "2026-10-21 07:57:48")]


def test_filter_ticket_date_sama_dengan_list_results(db):
    """Export agregat menyaring lewat helper yang sama dengan ``list_results``."""
    from db.models import Result as R

    _mk(db, "ZZTS9", "2026-10-20 10:00:00")
    _mk(db, "ZZTSA", "2026-10-25 10:00:00")
    q = db.query(R).filter(R.campaign == CAMPAIGN)
    got = {r.source_files[0][:5] for r in crud.filter_ticket_date(
        db, q, date(2026, 10, 20), date(2026, 10, 22)).all()}
    assert got == {"ZZTS9"}
