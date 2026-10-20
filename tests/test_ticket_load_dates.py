"""Tabel ``ticket_load_dates`` + akses crud (20 Oktober 2026).

Memakai fixture ``ticket_load_dates_table`` (tabel dibuat di transaksi yang di-rollback).
"""
from datetime import date

from db import crud


def test_upsert_lalu_baca_urut_naik(db, ticket_load_dates_table):
    n = crud.upsert_ticket_load_dates(
        db, [("ZZLD1", date(2026, 10, 15), "CashLine NTB"), ("ZZLD1", date(2026, 10, 10), None)]
    )
    assert n == 2
    assert crud.load_dates_by_ticket(db, ["ZZLD1"]) == {
        "ZZLD1": [date(2026, 10, 10), date(2026, 10, 15)]
    }


def test_upsert_idempoten(db, ticket_load_dates_table):
    row = ("ZZLD1", date(2026, 10, 10), "A")
    crud.upsert_ticket_load_dates(db, [row])
    crud.upsert_ticket_load_dates(db, [("ZZLD1", date(2026, 10, 10), "B")])
    assert crud.load_dates_by_ticket(db, ["ZZLD1"]) == {"ZZLD1": [date(2026, 10, 10)]}
    got = db.query(ticket_load_dates_table).filter_by(ticket_id="ZZLD1").all()
    assert len(got) == 1 and got[0].campaign == "B"


def test_ticket_id_di_strip(db, ticket_load_dates_table):
    crud.upsert_ticket_load_dates(db, [(" ZZLD2 ", date(2026, 10, 10), None), ("  ", date(2026, 10, 10), None)])
    assert crud.load_dates_by_ticket(db, ["ZZLD2"]) == {"ZZLD2": [date(2026, 10, 10)]}
    assert crud.load_dates_by_ticket(db, [" ZZLD2 "]) == {"ZZLD2": [date(2026, 10, 10)]}


def test_tanpa_baris_tidak_muncul(db, ticket_load_dates_table):
    assert crud.load_dates_by_ticket(db, ["ZZLD-TIDAK-ADA"]) == {}


def test_input_kosong_tanpa_query():
    # Tanpa sesi DB: kalau fungsi ini sampai membuat query, ``None.query`` akan error.
    assert crud.load_dates_by_ticket(None, []) == {}


def test_duplikat_dalam_satu_batch(db, ticket_load_dates_table):
    n = crud.upsert_ticket_load_dates(
        db,
        [("ZZLD3", date(2026, 10, 10), "A"), (" ZZLD3", date(2026, 10, 10), "B")],
    )
    assert n == 1
    got = db.query(ticket_load_dates_table).filter_by(ticket_id="ZZLD3").all()
    assert len(got) == 1 and got[0].campaign == "B"
