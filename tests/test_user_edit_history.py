"""Riwayat perubahan user (`GET /auth/users/history`, 20 Oktober 2026).

Sesi DB diganti stub yang merekam kriteria filter/urutan/limit; yang diuji aturan
endpoint-nya: urutan terbaru dulu, cakupan TL QC (user yang SAAT INI QC Telemarketing,
disaring sebelum limit), filter user_id, nama sasaran satu query, dan password tanpa nilai.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from api import rbac
from api.routers import auth as auth_router
from api.routers.auth import user_change_history
from api.schemas.auth import UserChangeEventItem
from db.models import User, UserChangeEvent

COLLECTION = frozenset({"collection", "complaint handling"})
ACTOR = SimpleNamespace(id=1, username="admin1", role="admin")


@pytest.fixture(autouse=True)
def _admin_by_default(monkeypatch):
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: True)


@pytest.fixture
def tl_qc(monkeypatch):
    monkeypatch.setattr(auth_router, "_can_manage_all_users", lambda db, u: False)
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: u.campaigns)
    monkeypatch.setattr(rbac, "collection_campaigns_from_env", lambda: COLLECTION)


def _sql(c):
    return str(c.compile(compile_kwargs={"literal_binds": True}))


class _Query:
    def __init__(self, db, model):
        self.db, self.model = db, model
        self.criteria, self.order, self.lim = [], [], None

    def filter(self, *c):
        self.criteria += [_sql(x) for x in c]
        return self

    def order_by(self, *o):
        self.order += [_sql(x) for x in o]
        return self

    def limit(self, n):
        self.lim = n
        return self

    def all(self):
        self.db.log.append((self.model, self))
        return self.db.rows[self.model]


class _Session:
    def __init__(self, events=(), users=()):
        self.rows = {UserChangeEvent: list(events), User: list(users)}
        self.log = []

    def query(self, model):
        return _Query(self, model)

    def ran(self, model):
        return [q for m, q in self.log if m is model]


def _ev(i, uid=7, field="name", old=None, new="Budi", ts=None):
    return SimpleNamespace(id=i, user_id=uid, target_username=f"qc{uid}", field=field,
                           old_value=old, new_value=new, actor_username="admin1",
                           actor_role="admin", created_at=ts or datetime(2026, 10, 20, 9, i))


def _user(uid, role="qc", name=None, campaigns=("Telemarketing",)):
    return SimpleNamespace(id=uid, username=f"qc{uid}", name=name, role=role,
                           campaigns=list(campaigns))


def _call(db, **kw):
    kw.setdefault("user_id", None)
    kw.setdefault("limit", 200)
    return user_change_history(db=db, current_user=ACTOR, **kw)


def test_admin_melihat_semua_urut_terbaru():
    db = _Session([_ev(2), _ev(1)], [_user(7, name="Budi")])
    out = _call(db)
    assert [e.id for e in out] == [2, 1] and all(isinstance(e, UserChangeEventItem) for e in out)
    (q,) = db.ran(UserChangeEvent)
    assert q.criteria == [] and q.lim == 200
    assert "created_at DESC" in q.order[0] and "id DESC" in q.order[1]
    assert out[0].target_name == "Budi"
    assert len(db.ran(User)) == 1  # satu query untuk semua nama


def test_nama_sasaran_none_bila_user_sudah_dihapus():
    db = _Session([_ev(1, uid=99)], [])
    assert _call(db)[0].target_name is None


def test_tl_qc_hanya_riwayat_qc_telemarketing(tl_qc):
    qcs = [_user(7), _user(8, campaigns=("Collection",)), _user(9, campaigns=())]
    db = _Session([_ev(1)], qcs)
    _call(db, limit=50)
    q = db.ran(UserChangeEvent)[0]
    assert any("user_id IN (7, 9)" in c for c in q.criteria) and q.lim == 50


def test_tl_qc_tanpa_user_terjangkau_tidak_error(tl_qc):
    db = _Session([], [_user(8, campaigns=("Collection",))])
    assert _call(db) == []


def test_filter_user_id():
    db = _Session([_ev(1)], [_user(7)])
    _call(db, user_id=7)
    (q,) = db.ran(UserChangeEvent)
    assert any("user_id = 7" in c for c in q.criteria)


def test_password_tidak_membawa_nilai():
    db = _Session([_ev(1, field="password", old=None, new=None)], [_user(7)])
    (item,) = _call(db)
    assert item.field == "password" and item.old_value is None and item.new_value is None


def test_history_dideklarasikan_sebelum_route_user_id():
    paths = [r.path for r in auth_router.router.routes]
    assert paths.index("/auth/users/history") < min(
        i for i, p in enumerate(paths) if "{user_id}" in p)
