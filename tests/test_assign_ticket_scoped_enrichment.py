"""Menu Assign Ticket memungut data lokal HANYA untuk ticket yang tampil.

Sebelumnya halaman itu menarik ``/list_results`` halaman demi halaman tanpa filter
(sampai 10.000 baris) dan ``/qc_assignments`` seluruh tabel, lalu membuang hampir
semuanya — padahal tabelnya cuma menampilkan tiket H-1. Kedua endpoint sekarang
menerima ``ticket_ids``.
"""
import uuid
from datetime import datetime

import pytest

from api.routers import qc_assignment as qa
from api.routers import stats as st
from db import crud
from db.models import Result

# Route ini dipanggil sebagai fungsi Python biasa, jadi default ``Query(...)``-nya
# tidak pernah diselesaikan FastAPI — nilai yang ikut dihitung (page/limit, flag
# menu antrean) harus disebut sendiri.
_DEFAULTS = dict(page=1, limit=20, banding_pending=False, manual_status_pending=False)


def test_list_results_ticket_ids_yang_tidak_ada_mengembalikan_nol(db, admin_user):
    out = st.list_results(ticket_ids="ZZ-TIDAK-ADA-TICKET-INI", db=db, current_user=admin_user, **_DEFAULTS)
    assert out.total == 0
    assert out.items == []


def test_list_results_ticket_ids_dipisah_koma(db, admin_user):
    """Dua id palsu tetap nol — yang diuji: string CSV tidak dianggap SATU id."""
    out = st.list_results(ticket_ids="ZZ-PALSU-A,ZZ-PALSU-B", db=db, current_user=admin_user, **_DEFAULTS)
    assert out.total == 0


def test_list_results_tanpa_ticket_ids_tidak_terbatasi(db, admin_user):
    """Parameter baru tidak boleh mengubah perilaku pemanggil lama."""
    out = st.list_results(db=db, current_user=admin_user, **_DEFAULTS)
    assert out.total >= 0
    assert isinstance(out.items, list)


@pytest.fixture()
def assignments(db, admin_user):
    from db.models import User

    qc = db.query(User).filter(User.role == "qc", User.is_active == True).first()  # noqa: E712
    if qc is None:
        pytest.skip("tidak ada user role qc di database")
    for t in ("ZZASSIGNA", "ZZASSIGNB"):
        crud.assign_ticket_to_qc(db, t, qc.username, assigned_by_username=admin_user.username)
    db.flush()
    return ("ZZASSIGNA", "ZZASSIGNB")


def test_qc_assignments_dibatasi_ke_ticket_ids(db, admin_user, assignments):
    a, b = assignments
    rows = qa.list_assignments(ticket_ids=a, db=db, current_user=admin_user)
    ids = {r["ticket_id"] for r in rows}
    assert a in ids
    assert b not in ids


def test_qc_assignments_tanpa_ticket_ids_tetap_lengkap(db, admin_user, assignments):
    a, b = assignments
    ids = {r["ticket_id"] for r in qa.list_assignments(ticket_ids=None, db=db, current_user=admin_user)}
    assert {a, b} <= ids


def test_qc_assignments_ticket_ids_kosong_bukan_berarti_semua(db, admin_user, assignments):
    """String kosong = tidak ada id yang diminta, bukan "tanpa batas"."""
    rows = qa.list_assignments(ticket_ids="", db=db, current_user=admin_user)
    assert rows == []
