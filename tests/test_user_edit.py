"""Edit User (`PATCH /auth/users/{id}`, 20 Oktober 2026).

Sesi DB diganti stub supaya yang diuji aturan endpoint-nya: urutan cek (404 ->
422 -> role -> bentrok), field yang tercatat di riwayat, dan satu transaksi
(commit sekali, rollback bila penulisan ulang NIP gagal).
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import permissions as P
from api import rbac
from api.routers import auth as auth_router
from api.routers.auth import update_user
from api.schemas.auth import UserUpdate
from db import crud
from db.models import Role, User, UserChangeEvent

COLLECTION = frozenset({"collection", "complaint handling"})


@pytest.fixture(autouse=True)
def _admin_by_default(monkeypatch):
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: True)
    monkeypatch.setattr(auth_router, "_user_list_item", lambda db, u, campaigns=None: u)
    monkeypatch.setattr(auth_router, "hash_password", lambda p: "HASH:" + p)


@pytest.fixture
def renames(monkeypatch):
    calls = []
    monkeypatch.setattr(crud, "rename_username", lambda db, old, new: calls.append((old, new)) or {})
    return calls


@pytest.fixture
def tl_qc(monkeypatch):
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: False)
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: u.campaigns)
    monkeypatch.setattr(rbac, "collection_campaigns_from_env", lambda: COLLECTION)


class _Query:
    def __init__(self, db, model):
        self.db, self.model = db, model

    def filter(self, *_a, **_k):
        return self

    def first(self):
        if self.model is Role:
            return object() if self.db.role_exists else None
        self.db.user_lookups += 1
        return self.db.user if self.db.user_lookups == 1 else self.db.clash


class _Session:
    def __init__(self, user, clash=None, role_exists=True):
        self.user, self.clash, self.role_exists = user, clash, role_exists
        self.user_lookups = 0
        self.added = []
        self.commits = self.rollbacks = 0

    def query(self, model):
        return _Query(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _obj):
        pass

    def flush(self):
        pass


def _user(uid=7, role="qc", name=None, campaigns=("Telemarketing",)):
    return SimpleNamespace(id=uid, username=f"qc{uid}", name=name, email=f"qc{uid}@x",
                           role=role, hashed_password="OLD", left_qc_at=None,
                           campaigns=list(campaigns))


ACTOR = SimpleNamespace(id=1, username="admin1", role="admin")


def _patch(db, uid=7, actor=ACTOR, **body):
    return update_user(uid, UserUpdate(**body), db=db, current_user=actor)


def _events(db):
    return [e for e in db.added if isinstance(e, UserChangeEvent)]


def test_admin_ubah_nama_email_tercatat_per_field():
    db = _Session(_user())
    out = _patch(db, name=" Budi ", email="budi@x")
    assert out.name == "Budi" and out.email == "budi@x"
    evs = {e.field: e for e in _events(db)}
    assert set(evs) == {"name", "email"} and db.commits == 1
    assert (evs["name"].old_value, evs["name"].new_value) == (None, "Budi")
    assert evs["email"].old_value == "qc7@x"
    assert evs["email"].actor_username == "admin1" and evs["email"].actor_role == "admin"
    assert evs["email"].actor_user_id == 1 and evs["email"].user_id == 7


def test_ganti_nip_memanggil_rename_dan_mencatat(renames):
    db = _Session(_user())
    _patch(db, username="21000001")
    assert renames == [("qc7", "21000001")] and db.user.username == "21000001"
    (ev,) = _events(db)
    assert (ev.field, ev.old_value, ev.new_value) == ("username", "qc7", "21000001")
    assert ev.target_username == "21000001" and db.commits == 1


def test_ganti_password_dihash_tanpa_nilai_di_riwayat():
    db = _Session(_user())
    _patch(db, password="rahasia")
    assert db.user.hashed_password == "HASH:rahasia"
    (ev,) = _events(db)
    assert ev.field == "password" and ev.old_value is None and ev.new_value is None


def test_password_kosong_tidak_berubah():
    db = _Session(_user())
    _patch(db, password="")
    assert db.user.hashed_password == "OLD" and db.commits == 0 and not db.added


def test_tanpa_perubahan_tidak_commit():
    db = _Session(_user(name="Budi"))
    _patch(db, username="qc7", name="Budi", email="qc7@x", role="qc")
    assert db.commits == 0 and not db.added


def test_nama_kosong_dan_none_dianggap_sama():
    db = _Session(_user(name=None))
    _patch(db, name="  ")
    assert db.commits == 0


def test_tl_qc_kirim_role_sama_tetap_boleh(tl_qc):
    db = _Session(_user())
    _patch(db, role="QC", email="baru@x")
    assert db.commits == 1 and [e.field for e in _events(db)] == ["email"]


def test_tl_qc_ganti_role_403(tl_qc):
    db = _Session(_user())
    with pytest.raises(HTTPException) as exc:
        _patch(db, role="team_leader_qc")
    assert exc.value.status_code == 403
    assert exc.value.detail == "Hanya Admin yang dapat mengubah role" and db.commits == 0


@pytest.mark.parametrize("target", [
    _user(campaigns=["Collection"]),
    _user(role="team_leader_qc"),
    _user(role="sales_agent", campaigns=["Cashline"]),
])
def test_tl_qc_target_bukan_qc_telemarketing_404(tl_qc, target):
    db = _Session(target)
    with pytest.raises(HTTPException) as exc:
        _patch(db, email="x@x")
    assert exc.value.status_code == 404 and exc.value.detail == "User tidak ditemukan"
    assert db.commits == 0


def test_user_tidak_ada_404():
    with pytest.raises(HTTPException) as exc:
        _patch(_Session(None), email="x@x")
    assert exc.value.status_code == 404


def test_username_email_kosong_422():
    with pytest.raises(HTTPException) as exc:
        _patch(_Session(_user()), username="  ")
    assert exc.value.status_code == 422
    assert exc.value.detail == "Username dan email tidak boleh kosong"


def test_admin_tidak_bisa_ganti_role_sendiri():
    db = _Session(_user(uid=1, role="admin"))
    with pytest.raises(HTTPException) as exc:
        _patch(db, uid=1, role="qc")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Tidak dapat mengubah role akun sendiri" and db.commits == 0


def test_role_tidak_dikenal_422():
    db = _Session(_user(), role_exists=False)
    with pytest.raises(HTTPException) as exc:
        _patch(db, role="bukan_role")
    assert exc.value.status_code == 422 and exc.value.detail == "Role 'bukan_role' tidak dikenal"


def test_qc_jadi_tl_mengisi_left_qc_at():
    db = _Session(_user())
    _patch(db, role="team_leader_qc")
    assert db.user.role == "team_leader_qc" and db.user.left_qc_at is not None
    assert [(e.field, e.old_value, e.new_value) for e in _events(db)] == [("role", "qc", "team_leader_qc")]


def test_kembali_ke_qc_mengosongkan_left_qc_at():
    u = _user(role="team_leader_qc")
    u.left_qc_at = object()
    db = _Session(u)
    _patch(db, role="qc")
    assert u.role == "qc" and u.left_qc_at is None


def test_username_bentrok_409(renames):
    db = _Session(_user(), clash=SimpleNamespace(id=9))
    with pytest.raises(HTTPException) as exc:
        _patch(db, username="21000001")
    assert exc.value.status_code == 409
    assert exc.value.detail == "Username atau email sudah digunakan"
    assert db.commits == 0 and renames == []


def test_ganti_kapitalisasi_nip_sendiri_bukan_bentrok(renames):
    # Pengecekan bentrok mengecualikan user ini (User.id != user_id): clash=None.
    u = _user()
    u.username = "abc123"
    db = _Session(u)
    _patch(db, username="ABC123")
    assert renames == [("abc123", "ABC123")] and db.commits == 1


def test_gagal_rename_tidak_commit(monkeypatch):
    def boom(db, old, new):
        raise RuntimeError("rename gagal")

    monkeypatch.setattr(crud, "rename_username", boom)
    db = _Session(_user())
    with pytest.raises(RuntimeError):
        _patch(db, username="21000001")
    assert db.commits == 0 and db.rollbacks == 1


def test_permission_qc_user_edit_di_default_tl_qc():
    assert P.QC_USER_EDIT == "qc.user.edit"
    assert P.QC_USER_EDIT in P.DEFAULT_ROLES["team_leader_qc"]["permissions"]
    assert P.QC_USER_EDIT not in P.DEFAULT_ROLES["qc"]["permissions"]
    assert P.QC_USER_EDIT in P.ALL_PERMISSIONS
    assert P.QC_USER_EDIT not in P.ADMIN_ONLY_PERMISSIONS
