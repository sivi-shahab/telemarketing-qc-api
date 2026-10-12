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
