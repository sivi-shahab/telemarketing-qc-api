"""Saklar Upload Audio / Upload Transcript per user (Manage User, 30 Oktober 2026).

``users.upload_*_enabled``: NULL = ikut role, True/False = menimpa role. Role
``admin`` tidak tunduk pada saklar. Penimpaan dipasang di ``rbac.permissions_for``
sehingga menu (``/auth/me``) dan gate endpoint upload ikut bersamaan.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import permissions as P
from api import rbac
from api.routers import auth as auth_router
from api.routers.auth import set_user_upload_access
from api.schemas.auth import UserUploadAccessUpdate

AUDIO = {P.MENU_UPLOAD_AUDIO, P.AUDIO_UPLOAD}
TRANSCRIPT = {P.MENU_UPLOAD_TRANSCRIPT, P.TRANSCRIPT_UPLOAD}
ROLE_PERMS = {
    "admin": AUDIO | TRANSCRIPT | {P.MENU_RESULTS},
    "team_leader_qc": AUDIO | TRANSCRIPT | {P.MENU_RESULTS},
    "qc": {P.MENU_RESULTS},
}


@pytest.fixture(autouse=True)
def _role_perms(monkeypatch):
    """Hak dari role diambil dari ROLE_PERMS (set yang sama dipakai bersama, seperti
    cache role), tanpa DB dan tanpa OCR Gambar."""
    monkeypatch.setattr(rbac, "_base_permissions_for", lambda db, u: ROLE_PERMS[u.role])
    monkeypatch.setattr(rbac, "ocr_image_campaigns_from_env", lambda: frozenset())
    monkeypatch.setattr(auth_router, "_user_list_item", lambda db, u: u)


def _user(uid=7, role="qc", audio=None, transcript=None):
    return SimpleNamespace(id=uid, username=f"u{uid}", role=role,
                           upload_audio_enabled=audio, upload_transcript_enabled=transcript)


# --------------------------------------------------------------------------
# permissions_for
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["qc", "team_leader_qc"])
def test_null_ikut_role(role):
    out = rbac.permissions_for(None, _user(role=role))
    assert out == ROLE_PERMS[role]


def test_qc_diaktifkan_mendapat_menu_dan_endpoint():
    out = rbac.permissions_for(None, _user(role="qc", audio=True))
    assert AUDIO <= out and not (TRANSCRIPT & out)


def test_tl_qc_dinonaktifkan_kehilangan_keduanya_tanpa_menulari_role():
    out = rbac.permissions_for(None, _user(role="team_leader_qc", audio=False, transcript=False))
    assert not (out & (AUDIO | TRANSCRIPT)) and P.MENU_RESULTS in out
    # Set milik role (cache) tidak ikut berubah.
    assert AUDIO | TRANSCRIPT <= ROLE_PERMS["team_leader_qc"]


def test_admin_mengabaikan_saklar():
    out = rbac.permissions_for(None, _user(role="admin", audio=False, transcript=False))
    assert AUDIO | TRANSCRIPT <= out


def test_upload_access_for():
    assert rbac.upload_access_for(None, _user(role="qc", transcript=True)) == {
        "upload_audio": False, "upload_transcript": True,
    }


# --------------------------------------------------------------------------
# PATCH /auth/users/{id}/upload_access
# --------------------------------------------------------------------------

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
        self.added = []

    def query(self, _model):
        return _Query(self.user)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, _obj):
        pass


ADMIN = SimpleNamespace(id=1, username="admin1", role="admin")


def test_endpoint_menyimpan_saklar_dan_riwayat():
    db = _Session(_user(role="qc"))
    set_user_upload_access(7, UserUploadAccessUpdate(upload_audio=True), db=db, current_user=ADMIN)
    assert db.user.upload_audio_enabled is True
    assert db.user.upload_transcript_enabled is None  # tidak dikirim = tidak disentuh
    assert db.commits == 1
    [ev] = db.added
    assert (ev.field, ev.old_value, ev.new_value) == ("upload_audio", "nonaktif", "aktif")
    assert ev.actor_username == "admin1"


def test_endpoint_tanpa_perubahan_efektif_tidak_menulis_riwayat():
    db = _Session(_user(role="team_leader_qc"))
    set_user_upload_access(
        7, UserUploadAccessUpdate(upload_audio=True, upload_transcript=False), db=db, current_user=ADMIN,
    )
    assert (db.user.upload_audio_enabled, db.user.upload_transcript_enabled) == (True, False)
    assert [e.field for e in db.added] == ["upload_transcript"]


def test_endpoint_menolak_admin():
    db = _Session(_user(role="admin"))
    with pytest.raises(HTTPException) as exc:
        set_user_upload_access(7, UserUploadAccessUpdate(upload_audio=False), db=db, current_user=ADMIN)
    assert exc.value.status_code == 400
    assert db.user.upload_audio_enabled is None and db.commits == 0


def test_endpoint_user_tidak_ada_404():
    with pytest.raises(HTTPException) as exc:
        set_user_upload_access(99, UserUploadAccessUpdate(upload_audio=True), db=_Session(None), current_user=ADMIN)
    assert exc.value.status_code == 404
