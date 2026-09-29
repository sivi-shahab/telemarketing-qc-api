"""Tombol Nonaktifkan/Aktifkan QC di Manage User (`PATCH /auth/users/{id}/active`).

Dinonaktifkan = keluar dari pool pembagian tiket (`qc_assignment.py` memfilter
`User.is_active`) tanpa menghapus akun. Sesi DB diganti stub supaya yang diuji
hanya aturan endpoint-nya: akun sendiri ditolak, user tak dikenal 404, sisanya
flag ditulis dan di-commit.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers.auth import set_user_active


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


def _user(uid, active=True):
    return SimpleNamespace(id=uid, username=f"qc{uid}", name=None, email=f"qc{uid}@x",
                           role="qc", is_active=active, created_at=None)


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
