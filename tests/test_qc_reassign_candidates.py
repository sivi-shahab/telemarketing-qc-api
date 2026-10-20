"""Pemilihan tiket QC nonaktif yang dibagi ulang (``crud.qc_reassign_candidates``,
19 Oktober 2026).

Aturannya: QC yang dinonaktifkan HARI INI sebelum slot aktif, tiket yang di-assign
kepadanya HARI INI, dan belum ada pengajuan Manual Status / tanda cek manual.

Semua baris test memakai tahun 2000 dan username acak; transaksi selalu di-rollback.
Sejak Edit User (20 Oktober 2026) user yang pindah role dari QC (``left_qc_at`` hari
ini, role bukan ``qc``) ikut jadi kandidat dengan source ``qc_ganti_role``.
Dilewati bila kolom ``users.deactivated_at`` (0068) / ``users.left_qc_at`` (0070) belum ada.
"""
import uuid
from datetime import datetime, timedelta

import pytest

SINCE = datetime(2000, 1, 1, 17, 0)      # 00.00 WIB 2 Jan 2000
SLOT = SINCE + timedelta(hours=8)          # 08.00 WIB
TODAY = SINCE + timedelta(hours=2)


@pytest.fixture()
def dbc(db):
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(db.get_bind()).get_columns("users")}
    if "deactivated_at" not in cols:
        pytest.skip("kolom users.deactivated_at (migrasi 0068) belum ada")
    if "left_qc_at" not in cols:
        pytest.skip("kolom users.left_qc_at (migrasi 0070) belum ada")
    return db


def _qc(db, *, active=False, deactivated_at=TODAY, role="qc", left_qc_at=None):
    from db.models import User

    u = User(username="t_" + uuid.uuid4().hex[:10], email=f"{uuid.uuid4().hex[:8]}@x.test",
             hashed_password="x", role=role, is_active=active, deactivated_at=deactivated_at,
             left_qc_at=left_qc_at)
    db.add(u)
    db.flush()
    return u.username


def _ticket(db, qc, assigned_at=TODAY, *, request=False, check=False):
    from db.models import QcAssignment, QcManualCheck, QcStatusRequest, Result

    tid = uuid.uuid4().hex[:10]
    r = Result(id=uuid.uuid4(), campaign="Cashline", status="done",
               source_files=[f"{tid}_a.pdf"], uploaded_at=assigned_at)
    db.add(r)
    db.add(QcAssignment(ticket_id=tid, qc_username=qc, assigned_at=assigned_at))
    db.flush()
    if request:
        db.add(QcStatusRequest(result_id=r.id, requested_status="PASS", reason="x"))
    if check:
        db.add(QcManualCheck(result_id=r.id, checked_by_username=qc))
    db.flush()
    return tid


def _cand(db):
    from db import crud

    return {t: (q, src) for t, q, src in crud.qc_reassign_candidates(db, since=SINCE, slot_start=SLOT)}


def test_tiket_hari_ini_yang_belum_dikerjakan_dibagi_ulang(dbc):
    qc = _qc(dbc)
    open_ = _ticket(dbc, qc)
    diajukan = _ticket(dbc, qc, request=True)
    dicek = _ticket(dbc, qc, check=True)
    kemarin = _ticket(dbc, qc, assigned_at=SINCE - timedelta(hours=3))

    got = _cand(dbc)

    assert got.get(open_) == (qc, "qc_nonaktif")
    for tid in (diajukan, dicek, kemarin):
        assert tid not in got


def test_qc_yang_tidak_memenuhi_syarat_tidak_disentuh(dbc):
    aktif = _ticket(dbc, _qc(dbc, active=True, deactivated_at=None))
    nonaktif_kemarin = _ticket(dbc, _qc(dbc, deactivated_at=SINCE - timedelta(hours=1)))
    nonaktif_slot_ini = _ticket(dbc, _qc(dbc, deactivated_at=SLOT + timedelta(minutes=5)))
    tanpa_waktu = _ticket(dbc, _qc(dbc, deactivated_at=None))
    bukan_qc = _ticket(dbc, _qc(dbc, role="team_leader_qc"))

    got = _cand(dbc)

    for tid in (aktif, nonaktif_kemarin, nonaktif_slot_ini, tanpa_waktu, bukan_qc):
        assert tid not in got


def test_qc_ganti_role_hari_ini_dibagi_ulang(dbc):
    tl = _qc(dbc, active=True, deactivated_at=None, role="team_leader_qc", left_qc_at=TODAY)
    tid = _ticket(dbc, tl)
    assert _cand(dbc).get(tid) == (tl, "qc_ganti_role")


def test_ganti_role_sesudah_slot_belum_dibagi(dbc):
    tl = _qc(dbc, active=True, deactivated_at=None, role="team_leader_qc",
             left_qc_at=SLOT + timedelta(minutes=1))
    assert _ticket(dbc, tl) not in _cand(dbc)


def test_ganti_role_kembali_ke_qc_tidak_dibagi(dbc):
    qc = _qc(dbc, active=True, deactivated_at=None, role="qc", left_qc_at=TODAY)
    assert _ticket(dbc, qc) not in _cand(dbc)


def test_nonaktif_dan_ganti_role_sekaligus_dihitung_nonaktif(dbc):
    # role bukan qc + nonaktif: aturan nonaktif butuh role qc, jadi satu-satunya jalur
    # adalah ganti role; user role=qc nonaktif yang punya left_qc_at tetap nonaktif.
    qc = _qc(dbc, role="qc", left_qc_at=TODAY)
    tid = _ticket(dbc, qc)
    assert _cand(dbc).get(tid) == (qc, "qc_nonaktif")


def test_reassign_memindahkan_dan_mencatat_event(dbc):
    from db import crud
    from db.models import QcAssignment, QcAssignmentEvent

    lama, baru = _qc(dbc), _qc(dbc, active=True, deactivated_at=None)
    tid = _ticket(dbc, lama)

    assert crud.reassign_tickets_to_qc(dbc, [(tid, baru)], assigned_by_username="scheduler") == 1

    row = dbc.query(QcAssignment).filter(QcAssignment.ticket_id == tid).one()
    assert row.qc_username == baru
    ev = dbc.query(QcAssignmentEvent).filter(QcAssignmentEvent.ticket_id == tid).one()
    assert (ev.action, ev.previous_qc_username, ev.qc_username, ev.source) == (
        "reassign", lama, baru, "qc_nonaktif")
