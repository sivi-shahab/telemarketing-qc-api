"""Jejak audit assignment QC (``qc_assignment_events``, 12 Oktober 2026).

``qc_assignments`` adalah tabel STATE: re-assign menimpa barisnya dan "Lepas"
menghapusnya, sehingga tidak ada cara mengetahui siapa pernah memegang tiket,
siapa yang memindahkan / melepasnya, dan kapan. Setiap jalur tulis assignment
kini menambahkan satu baris event di transaksi yang SAMA — append-only, tidak
pernah di-update atau dihapus.

Diuji di SQLite in-memory: kedua tabel hanya memakai tipe kolom biasa.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import crud
from db.models import Base, QcAssignment, QcAssignmentEvent


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[QcAssignment.__table__, QcAssignmentEvent.__table__]
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _events(db):
    rows = db.query(QcAssignmentEvent).order_by(QcAssignmentEvent.id).all()
    return [
        (e.ticket_id, e.action, e.qc_username, e.previous_qc_username, e.actor_username, e.source)
        for e in rows
    ]


def test_assign_lalu_reassign_tercatat_dua_event(db):
    crud.assign_ticket_to_qc(db, "t1", "qc_a", assigned_by_username="tl")
    crud.assign_ticket_to_qc(db, "t1", "qc_b", assigned_by_username="spq")

    assert _events(db) == [
        ("t1", "assign", "qc_a", None, "tl", "manual"),
        ("t1", "reassign", "qc_b", "qc_a", "spq", "manual"),
    ]


def test_assign_ke_qc_yang_sama_tidak_mencatat_event(db):
    crud.assign_ticket_to_qc(db, "t1", "qc_a", assigned_by_username="tl")
    crud.assign_ticket_to_qc(db, "t1", "qc_a", assigned_by_username="tl")

    assert len(_events(db)) == 1


def test_lepas_satu_tiket(db):
    crud.assign_ticket_to_qc(db, "t1", "qc_a", assigned_by_username="tl")
    assert crud.unassign_ticket(db, "t1", actor_username="spq") is True

    assert _events(db)[-1] == ("t1", "unassign", None, "qc_a", "spq", "lepas")


def test_lepas_tiket_yang_tidak_di_assign_tidak_mencatat(db):
    assert crud.unassign_ticket(db, "t1", actor_username="spq") is False
    assert _events(db) == []


def test_bulk_assign_mencatat_per_tiket_dengan_source(db):
    crud.assign_ticket_to_qc(db, "t0", "qc_a", assigned_by_username="tl")
    n = crud.bulk_assign_tickets_to_qc(
        db, [("t0", "qc_b"), ("t1", "qc_a"), ("t2", "qc_b")],
        assigned_by_username="scheduler", source="scheduler",
    )

    assert n == 2
    # t0 sudah dipegang -> dilewati, tidak dicatat.
    assert _events(db)[1:] == [
        ("t1", "assign", "qc_a", None, "scheduler", "scheduler"),
        ("t2", "assign", "qc_b", None, "scheduler", "scheduler"),
    ]


def test_bulk_unassign_mencatat_pemegang_sebelumnya(db):
    for tid, qc in (("t1", "qc_a"), ("t2", "qc_b"), ("t3", "qc_a")):
        crud.assign_ticket_to_qc(db, tid, qc, assigned_by_username="tl")

    n = crud.bulk_unassign_tickets(db, ["t1", "t2"], actor_username="spq")

    assert n == 2
    assert sorted(_events(db)[3:]) == [
        ("t1", "unassign", None, "qc_a", "spq", "lepas_semua"),
        ("t2", "unassign", None, "qc_b", "spq", "lepas_semua"),
    ]
    assert [a.ticket_id for a in db.query(QcAssignment).all()] == ["t3"]


def test_unassign_milik_qc_mencatat_source_user_deleted(db):
    crud.assign_ticket_to_qc(db, "t1", "qc_a", assigned_by_username="tl")
    crud.assign_ticket_to_qc(db, "t2", "qc_b", assigned_by_username="tl")

    crud.unassign_tickets_of_qc(db, "qc_a", actor_username="spq", source="user_deleted")
    db.commit()

    assert _events(db)[-1] == ("t1", "unassign", None, "qc_a", "spq", "user_deleted")
    assert [a.ticket_id for a in db.query(QcAssignment).all()] == ["t2"]


# --- GET /qc_assignment/events (riwayat di tab Log QC) -------------------------

from datetime import date, datetime

from api.routers import qc_assignment as qa


def test_batas_hari_wib_dalam_utc():
    start, end = qa._wib_day_bounds_utc(date(2026, 10, 12), date(2026, 10, 12))
    assert start == datetime(2026, 10, 11, 17, 0)
    assert end == datetime(2026, 10, 12, 17, 0)
    assert qa._wib_day_bounds_utc(None, None) == (None, None)


def _event(db, tid, action, at, qc=None, prev=None, actor="tl", source="manual"):
    crud.record_assignment_event(
        db, tid, action, qc_username=qc, previous_qc_username=prev,
        actor_username=actor, source=source, at=at,
    )


def _list(monkeypatch, db, scope=None, **kw):
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: scope)
    monkeypatch.setattr(qa, "_user_names", lambda db, names: {"qc_a": "QC A"})
    params = {"date_start": None, "date_end": None, "ticket_id": None}
    params.update(kw)
    return qa.assignment_events(**params, db=db, current_user=object())


def test_riwayat_per_tanggal_wib_terbaru_dulu(monkeypatch, db):
    _event(db, "t1", "assign", datetime(2026, 10, 11, 16, 59), qc="qc_a")       # 11 Okt 23:59 WIB
    _event(db, "t1", "reassign", datetime(2026, 10, 11, 17, 0), qc="qc_b", prev="qc_a")  # 12 Okt 00:00 WIB
    _event(db, "t1", "unassign", datetime(2026, 10, 12, 9, 0), prev="qc_b", source="lepas")
    db.commit()

    out = _list(monkeypatch, db, date_start="2026-10-12", date_end="2026-10-12")

    assert [e["action"] for e in out["events"]] == ["unassign", "reassign"]
    re = out["events"][1]
    assert re["previous_qc_username"] == "qc_a" and re["previous_qc_name"] == "QC A"
    assert re["qc_username"] == "qc_b" and re["qc_name"] == "qc_b"
    assert re["created_at"].endswith("Z")


def test_riwayat_mengikuti_cakupan_dan_filter_tiket(monkeypatch, db):
    now = datetime(2026, 10, 12, 3, 0)
    _event(db, "t1", "assign", now, qc="qc_a")
    _event(db, "t2", "assign", now, qc="qc_a")
    db.commit()

    assert [e["ticket_id"] for e in _list(monkeypatch, db, scope={"t2"})["events"]] == ["t2"]
    assert [e["ticket_id"] for e in _list(monkeypatch, db, ticket_id=" t1 ")["events"]] == ["t1"]
