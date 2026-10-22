"""Tombol Nonaktifkan/Aktifkan QC di Manage User (`PATCH /auth/users/{id}/active`).

Dinonaktifkan = keluar dari pool pembagian tiket (`qc_assignment.py` memfilter
`User.is_active`) tanpa menghapus akun. Sesi DB diganti stub supaya yang diuji
hanya aturan endpoint-nya: akun sendiri ditolak, user tak dikenal 404, sisanya
flag ditulis dan di-commit.

Team Leader QC (QC_USER_ACTIVE_WRITE tanpa ADMIN_USER_WRITE) hanya menjangkau QC
Telemarketing: QC Collection-only dan role lain dijawab 404.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import permissions as P
from api import rbac
from api.routers import auth as auth_router
from api.routers.auth import set_user_active

COLLECTION = frozenset({"collection", "complaint handling"})


@pytest.fixture(autouse=True)
def _admin_by_default(monkeypatch):
    """Bawaan: aktor = Admin (ADMIN_USER_WRITE). Tes TL QC menimpanya."""
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: True)


@pytest.fixture
def tl_qc(monkeypatch):
    """Aktor tanpa ADMIN_USER_WRITE; campaign efektif sasaran dari ``user.campaigns``."""
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: False)
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: u.campaigns)
    monkeypatch.setattr(rbac, "collection_campaigns_from_env", lambda: COLLECTION)


class _Query:
    def __init__(self, user):
        self._user = user

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self._user


class _Session:
    def __init__(self, user):
        self.user = user
        self.commits = 0

    def query(self, _model):
        return _Query(self.user)

    def commit(self):
        self.commits += 1

    def refresh(self, _obj):
        pass


def _user(uid, active=True, role="qc", campaigns=("Telemarketing", "Cashline")):
    return SimpleNamespace(id=uid, username=f"qc{uid}", name=None, email=f"qc{uid}@x",
                           role=role, is_active=active, created_at=None,
                           campaigns=list(campaigns) if campaigns is not None else None)


def test_nonaktifkan_qc_menulis_flag_dan_commit():
    db = _Session(_user(7, active=True))
    out = set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert out.is_active is False and db.user.is_active is False
    assert db.commits == 1


def test_aktifkan_kembali():
    db = _Session(_user(7, active=False))
    assert set_user_active(7, True, db=db, current_user=SimpleNamespace(id=1)).is_active is True


def test_akun_sendiri_ditolak_tanpa_menyentuh_db():
    db = _Session(_user(1))
    with pytest.raises(HTTPException) as exc:
        set_user_active(1, False, db=db, current_user=SimpleNamespace(id=1))
    assert exc.value.status_code == 400
    assert db.user.is_active is True and db.commits == 0


def test_user_tidak_ada_404():
    with pytest.raises(HTTPException) as exc:
        set_user_active(99, False, db=_Session(None), current_user=SimpleNamespace(id=1))
    assert exc.value.status_code == 404


# --------------------------------------------------------------------------
# Team Leader QC — Kelola QC (QC_USER_ACTIVE_WRITE)
# --------------------------------------------------------------------------

def test_tl_qc_bisa_nonaktifkan_qc_telemarketing(tl_qc):
    db = _Session(_user(7))
    assert set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1)).is_active is False
    assert db.commits == 1


@pytest.mark.parametrize("target", [
    _user(7, campaigns=["Collection"]),
    _user(7, role="team_leader_qc"),
    _user(7, role="spq_head"),
    _user(7, role="sales_agent", campaigns=["Cashline"]),
])
def test_tl_qc_tidak_menjangkau_selain_qc_telemarketing(tl_qc, target):
    db = _Session(target)
    with pytest.raises(HTTPException) as exc:
        set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert exc.value.status_code == 404
    assert target.is_active is True and db.commits == 0


def test_qc_tanpa_batas_campaign_terhitung_telemarketing(tl_qc):
    assert auth_router._is_telemarketing_qc(None, _user(7, campaigns=None)) is True


def test_capability_hanya_untuk_tl_qc_dan_tidak_admin_only():
    assert P.QC_USER_ACTIVE_WRITE in P.DEFAULT_ROLES["team_leader_qc"]["permissions"]
    assert P.QC_USER_ACTIVE_WRITE not in P.DEFAULT_ROLES["qc"]["permissions"]
    assert P.QC_USER_ACTIVE_WRITE not in P.DEFAULT_ROLES["spq_head"]["permissions"]
    assert P.QC_USER_ACTIVE_WRITE not in P.ADMIN_ONLY_PERMISSIONS
    assert P.QC_USER_ACTIVE_WRITE in P.ALL_PERMISSIONS


def test_tl_qc_collection_kehilangan_kelola_qc():
    out = rbac.collection_adjusted_permissions(
        set(P.DEFAULT_ROLES["team_leader_qc"]["permissions"]), ["Collection"], COLLECTION)
    assert P.QC_USER_ACTIVE_WRITE not in out
    out = rbac.collection_adjusted_permissions(
        set(P.DEFAULT_ROLES["team_leader_qc"]["permissions"]), ["Telemarketing", "Cashline"], COLLECTION)
    assert P.QC_USER_ACTIVE_WRITE in out


def test_tl_qc_tidak_bisa_buat_atau_hapus_user():
    """create_user & delete_user tetap di-gate ADMIN_USER_WRITE saja."""
    import inspect
    for fn in (auth_router.create_user, auth_router.delete_user):
        dep = inspect.signature(fn).parameters["current_user"].default.dependency
        assert dep.__qualname__.startswith("require.")
        assert [c.cell_contents for c in dep.__closure__] == [(P.ADMIN_USER_WRITE,)]
    assert P.ADMIN_USER_WRITE not in P.DEFAULT_ROLES["team_leader_qc"]["permissions"]


class _ListQuery:
    def __init__(self, users):
        self.users = users
        self.filtered = False

    def filter(self, *_a, **_k):
        self.filtered = True
        return self

    def order_by(self, *_a):
        return self

    def all(self):
        return self.users


def test_daftar_user_tl_qc_hanya_qc_telemarketing(tl_qc, monkeypatch):
    monkeypatch.setattr(rbac, "role_label_for", lambda db, u: u.role)
    monkeypatch.setattr(rbac, "data_scope_for", lambda db, u: "qc_assigned")
    users = [_user(1), _user(2, campaigns=["Collection"]), _user(3, campaigns=["Complaint Handling", "Collection"])]
    q = _ListQuery(users)
    out = auth_router.list_users(db=SimpleNamespace(query=lambda _m: q), current_user=SimpleNamespace(id=9))
    assert q.filtered  # role == "qc" disaring di SQL
    assert [u.id for u in out] == [1]


# --------------------------------------------------------------------------
# Nonaktif oleh TL QC hanya sampai 00.00 WIB (16 Oktober 2026)
# --------------------------------------------------------------------------
from datetime import datetime

from db import crud


@pytest.mark.parametrize("now_utc, expected_utc", [
    # 16 Okt 10.00 WIB -> 17 Okt 00.00 WIB = 16 Okt 17.00 UTC
    (datetime(2026, 10, 16, 3, 0), datetime(2026, 10, 16, 17, 0)),
    # 16 Okt 23.59 WIB (16.59 UTC) -> masih malam yang sama
    (datetime(2026, 10, 16, 16, 59), datetime(2026, 10, 16, 17, 0)),
    # 17 Okt 00.00 WIB tepat -> malam berikutnya
    (datetime(2026, 10, 16, 17, 0), datetime(2026, 10, 17, 17, 0)),
    # 17 Okt 06.00 WIB (16 Okt 23.00 UTC) -> 18 Okt 00.00 WIB
    (datetime(2026, 10, 16, 23, 0), datetime(2026, 10, 17, 17, 0)),
])
def test_batas_nonaktif_tengah_malam_wib(now_utc, expected_utc):
    assert crud.next_midnight_wib_utc(now_utc) == expected_utc


def test_tl_qc_nonaktif_sampai_tengah_malam_wib(tl_qc, monkeypatch):
    monkeypatch.setattr(crud, "next_midnight_wib_utc", lambda now=None: datetime(2026, 10, 16, 17, 0))
    db = _Session(_user(7))
    out = set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert out.is_active is False
    assert db.user.inactive_until == datetime(2026, 10, 16, 17, 0)
    assert out.inactive_until == datetime(2026, 10, 16, 17, 0)


def test_admin_nonaktif_permanen():
    u = _user(7)
    u.inactive_until = datetime(2026, 10, 16, 17, 0)
    db = _Session(u)
    set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert db.user.inactive_until is None


def test_aktifkan_menghapus_batas(tl_qc):
    u = _user(7, active=False)
    u.inactive_until = datetime(2026, 10, 16, 17, 0)
    db = _Session(u)
    set_user_active(7, True, db=db, current_user=SimpleNamespace(id=1))
    assert db.user.is_active is True and db.user.inactive_until is None


# --------------------------------------------------------------------------
# Semua role bisa dinonaktifkan Admin, kecuali role admin (22 Oktober 2026)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["spq_head", "team_leader_qc", "sales", "demo"])
def test_admin_bisa_nonaktifkan_role_selain_qc(role):
    db = _Session(_user(7, role=role))
    out = set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert out.is_active is False and db.commits == 1


def test_role_admin_tidak_bisa_dinonaktifkan():
    db = _Session(_user(7, role="admin"))
    with pytest.raises(HTTPException) as exc:
        set_user_active(7, False, db=db, current_user=SimpleNamespace(id=1))
    assert exc.value.status_code == 400
    assert db.user.is_active is True and db.commits == 0


def test_role_admin_yang_terlanjur_nonaktif_bisa_diaktifkan():
    db = _Session(_user(7, active=False, role="admin"))
    assert set_user_active(7, True, db=db, current_user=SimpleNamespace(id=1)).is_active is True
