"""Perencana migrasi user monolit -> App B (``scripts/migrate_users_from_monolith.py``).

Yang diuji di sini KHUSUS bagian murni-nya: dari isi kedua database, baris mana
yang boleh masuk, mana yang dilewati, dan kenapa. Bagian yang menyentuh DB
sengaja tidak ikut — keputusan salahnya justru ada di aturan penyaringan ini,
dan aturan itu bisa diuji tanpa Postgres sama sekali.

Konteksnya: DB monolit (``bankqc``) menyimpan 29 user, App B (``da.dashboard``)
sudah berisi akun admin yang dipakai sekarang. Migrasinya harus bisa dijalankan
ulang tanpa menggandakan apa pun, dan tidak boleh menimpa akun yang sudah ada.
"""
import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "migrate_users_from_monolith",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate_users_from_monolith.py",
)
mig = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mig)


TARGET_ROLES = {"admin", "spq_head", "qc", "team_leader", "sales_agent", "team_leader_qc"}


def _src(uid, username, role="qc", email=None, **kw):
    row = {
        "id": uid,
        "username": username,
        "email": email or f"{username}@bankmega.com",
        "hashed_password": f"$2b$12$hash-{username}",
        "role": role,
        "is_active": True,
        "created_at": None,
        "created_by": None,
        "name": username.upper(),
    }
    row.update(kw)
    return row


def _plan(source_users, source_scopes=(), target_users=(), created_by="22050660"):
    return mig.build_plan(
        source_users=list(source_users),
        source_scopes=list(source_scopes),
        target_users=list(target_users),
        target_role_keys=TARGET_ROLES,
        created_by_username=created_by,
    )


# --------------------------------------------------------------------------
# Siapa yang ikut, siapa yang tidak
# --------------------------------------------------------------------------

def test_user_biasa_ikut_migrasi_dengan_hash_password_apa_adanya():
    """Password lama harus tetap berlaku: hash-nya disalin, bukan di-reset."""
    plan = _plan([_src(5, "H21120266")])

    assert [u["username"] for u in plan.inserts] == ["H21120266"]
    assert plan.inserts[0]["hashed_password"] == "$2b$12$hash-H21120266"
    assert plan.skipped == []


def test_akun_admin_sumber_dilewati():
    """Admin App B sudah ada dan lebih baru; admin monolit tidak ikut."""
    plan = _plan([_src(22, "admin", role="admin"), _src(5, "H21120266")])

    assert [u["username"] for u in plan.inserts] == ["H21120266"]
    assert [(s.username, "admin" in s.reason.lower()) for s in plan.skipped] == [("admin", True)]


def test_username_yang_sudah_ada_di_target_dilewati():
    """Idempoten: dijalankan dua kali tidak menggandakan siapa pun."""
    target = [{"id": 3, "username": "21101604", "email": "dandi.sakti@bankmega.com", "role": "admin"}]
    plan = _plan([_src(32, "21101604", role="spq_head", email="dandi.sakti@bankmega.com")], target_users=target)

    assert plan.inserts == []
    assert len(plan.skipped) == 1


def test_email_yang_sudah_ada_di_target_dilewati_walau_username_beda():
    """``users.email`` UNIQUE — tanpa penjagaan ini, insert-nya gagal di tengah jalan."""
    target = [{"id": 3, "username": "lama", "email": "dandi.sakti@bankmega.com", "role": "admin"}]
    plan = _plan([_src(32, "21101604", email="dandi.sakti@bankmega.com")], target_users=target)

    assert plan.inserts == []
    assert "email" in plan.skipped[0].reason.lower()


def test_role_yang_tidak_dikenal_target_dilewati_bukan_diloloskan():
    """Gagal tertutup: user tanpa role sah di target tidak boleh masuk diam-diam."""
    plan = _plan([_src(9, "orang", role="peran_hantu")])

    assert plan.inserts == []
    assert "peran_hantu" in plan.skipped[0].reason


# --------------------------------------------------------------------------
# Scope campaign
# --------------------------------------------------------------------------

def test_scope_campaign_ikut_pemiliknya_lewat_username():
    """ID sumber tidak dibawa, jadi scope dipetakan lewat username, bukan user_id."""
    plan = _plan(
        [_src(5, "H21120266"), _src(33, "12068393", role="spq_head")],
        source_scopes=[{"user_id": 5, "campaign": "Cashline"}, {"user_id": 33, "campaign": "Collection"}],
    )

    assert {u["username"]: u["campaigns"] for u in plan.inserts} == {
        "H21120266": ["Cashline"],
        "12068393": ["Collection"],
    }


def test_scope_milik_user_yang_dilewati_tidak_ikut_masuk():
    """Kalau orangnya tidak dipindah, scope-nya juga tidak — kalau tidak, ``user_id``-nya menggantung."""
    target = [{"id": 3, "username": "21101604", "email": "dandi.sakti@bankmega.com", "role": "admin"}]
    plan = _plan(
        [_src(32, "21101604", email="dandi.sakti@bankmega.com")],
        source_scopes=[{"user_id": 32, "campaign": "Collection"}],
        target_users=target,
    )

    assert plan.inserts == []
    assert plan.total_scopes == 0


def test_scope_kembar_hanya_dihitung_sekali():
    plan = _plan(
        [_src(5, "H21120266")],
        source_scopes=[{"user_id": 5, "campaign": "Cashline"}, {"user_id": 5, "campaign": "Cashline"}],
    )

    assert plan.inserts[0]["campaigns"] == ["Cashline"]


# --------------------------------------------------------------------------
# created_by
# --------------------------------------------------------------------------

def test_created_by_diarahkan_ke_admin_target():
    """``created_by`` sumber menunjuk admin monolit yang tidak ikut pindah; kalau
    dibiarkan apa adanya, angkanya menunjuk orang yang salah di App B."""
    target = [{"id": 2, "username": "22050660", "email": "sivi.shahab@bankmega.com", "role": "admin"}]
    plan = _plan([_src(23, "18121250", created_by=22)], target_users=target)

    assert plan.created_by_id == 2
    assert plan.inserts[0]["created_by"] == 2


def test_created_by_kosong_kalau_admin_target_tidak_ketemu():
    """Lebih baik NULL daripada menunjuk id asal-asalan — dan harus terlihat di peringatan."""
    plan = _plan([_src(23, "18121250", created_by=22)], target_users=[])

    assert plan.created_by_id is None
    assert plan.inserts[0]["created_by"] is None
    assert any("22050660" in w for w in plan.warnings)


def test_created_by_sumber_yang_kosong_tetap_kosong():
    """User tanpa pembuat di monolit tidak tiba-tiba jadi buatan admin."""
    target = [{"id": 2, "username": "22050660", "email": "sivi.shahab@bankmega.com", "role": "admin"}]
    plan = _plan([_src(3, "agent01", role="sales_agent", created_by=None)], target_users=target)

    assert plan.inserts[0]["created_by"] is None


# --------------------------------------------------------------------------
# ID sumber
# --------------------------------------------------------------------------

def test_id_sumber_tidak_dibawa():
    """Target sudah memakai id 2 dan 3; biarkan sequence-nya yang menerbitkan id."""
    plan = _plan([_src(35, "12111459")])

    assert "id" not in plan.inserts[0]
