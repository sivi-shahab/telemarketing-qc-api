"""Penyesuaian capability untuk login yang dibatasi ke campaign collection.

Campaign collection (penagihan) tidak mengenal alur Assign Ticket -> Manual Check
-> Pending Check: tiketnya tidak di-assign ke QC perorangan dan tidak ada banding.
Sebaliknya sisi collection justru perlu memasukkan bahan sendiri lewat Upload
Audio / Upload Transcript.

Yang diuji di sini adalah SYARATNYA, bukan sekadar hasilnya: role ``qc``,
``spq_head`` dan ``team_leader_qc`` dipakai BERSAMA oleh login Cashline maupun
Collection, jadi penyesuaian ini harus bergantung pada campaign efektif si ORANG
dan tidak boleh menyentuh siapa pun di luar collection. Mencabut capability-nya
dari role akan mematikan menu itu untuk Cashline juga.
"""
import pytest

from api import permissions as P
from api import rbac


COLLECTION = frozenset({"collection"})


# --------------------------------------------------------------------------
# collection_adjusted_permissions — syarat berlakunya
# --------------------------------------------------------------------------

def test_menu_alur_assign_dicabut_untuk_campaign_collection():
    out = rbac.collection_adjusted_permissions(
        {P.MENU_RESULTS, P.MENU_ASSIGN_TICKET, P.MENU_MANUAL_CHECK,
         P.MENU_PENDING_CHECK},
        ["Collection"],
        COLLECTION,
    )
    assert out == set(P.COLLECTION_ADDED_PERMISSIONS)


def test_menu_results_dicabut_karena_sudah_ada_collection_results():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS, P.MENU_STATS}, ["Collection"], COLLECTION)
    assert P.MENU_RESULTS not in out
    assert P.MENU_COLLECTION_RESULTS in out
    assert P.MENU_STATS in out


def test_login_campuran_tetap_punya_menu_results():
    before = {P.MENU_RESULTS}
    assert rbac.collection_adjusted_permissions(before, ["Collection", "Cashline"], COLLECTION) == before


def test_aksi_di_balik_menu_yang_dicabut_ikut_hilang():
    """Menu hilang tapi endpoint-nya terbuka = gate yang bisa ditembus ketik URL."""
    out = rbac.collection_adjusted_permissions(
        {P.QC_ASSIGNMENT_WRITE, P.QC_MANUAL_CHECK_APPROVE},
        ["Collection"],
        COLLECTION,
    )
    assert P.QC_ASSIGNMENT_WRITE not in out
    assert P.QC_MANUAL_CHECK_APPROVE not in out


def test_upload_audio_dan_transkrip_ditambahkan():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS}, ["Collection"], COLLECTION)
    assert P.MENU_UPLOAD_AUDIO in out
    assert P.MENU_UPLOAD_TRANSCRIPT in out
    assert P.AUDIO_UPLOAD in out
    assert P.TRANSCRIPT_UPLOAD in out


def test_nama_campaign_dicocokkan_tanpa_peduli_spasi_dan_kapital():
    out = rbac.collection_adjusted_permissions(
        {P.MENU_ASSIGN_TICKET}, ["  COLLECTION "], COLLECTION,
    )
    assert P.MENU_ASSIGN_TICKET not in out


def test_login_tanpa_batas_campaign_tidak_disentuh():
    """``None`` = tidak dibatasi. Admin & SPQ Head pusat ada di sini."""
    before = {P.MENU_ASSIGN_TICKET, P.MENU_MANUAL_CHECK}
    assert rbac.collection_adjusted_permissions(before, None, COLLECTION) == before


def test_login_cashline_tidak_disentuh():
    before = {P.MENU_ASSIGN_TICKET, P.MENU_MANUAL_CHECK}
    assert rbac.collection_adjusted_permissions(before, ["Cashline"], COLLECTION) == before


def test_login_campuran_collection_dan_cashline_tidak_disentuh():
    """Masih memegang tiket Cashline, jadi alur assign/banding-nya masih dipakai."""
    before = {P.MENU_ASSIGN_TICKET, P.MENU_MANUAL_CHECK}
    out = rbac.collection_adjusted_permissions(before, ["Collection", "Cashline"], COLLECTION)
    assert out == before


def test_batas_campaign_kosong_tidak_disentuh():
    """List kosong = dibatasi ke TIDAK ADA campaign, bukan ke collection."""
    before = {P.MENU_ASSIGN_TICKET}
    assert rbac.collection_adjusted_permissions(before, [], COLLECTION) == before


def test_tanpa_konfigurasi_collection_fitur_ini_mati():
    """``COLLECTION_CAMPAIGNS`` kosong = perilaku lama, persis seperti rollback."""
    before = {P.MENU_ASSIGN_TICKET}
    out = rbac.collection_adjusted_permissions(before, ["Collection"], frozenset())
    assert out == before


def test_himpunan_masukan_tidak_diubah():
    """Set-nya milik cache role di ``_load_all`` — mengubahnya merusak semua user."""
    before = {P.MENU_ASSIGN_TICKET, P.MENU_RESULTS}
    rbac.collection_adjusted_permissions(before, ["Collection"], COLLECTION)
    assert before == {P.MENU_ASSIGN_TICKET, P.MENU_RESULTS}


# --------------------------------------------------------------------------
# permissions_for — sambungannya ke user sungguhan
# --------------------------------------------------------------------------

@pytest.fixture()
def collection_env(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")


def _user_with_campaign(db, campaign):
    """User baru dengan role ``qc`` dan satu batas campaign. Ikut rollback fixture."""
    from db.models import User, UserCampaign

    suffix = f"{campaign.lower()}-rbac-test"
    user = User(
        username=f"uji-{suffix}",
        email=f"uji-{suffix}@example.invalid",
        hashed_password="x",
        role="qc",
    )
    db.add(user)
    db.flush()
    db.add(UserCampaign(user_id=user.id, campaign=campaign))
    db.flush()
    return user


def test_permissions_for_user_collection_kehilangan_menu_alur_assign(db, collection_env):
    user = _user_with_campaign(db, "Collection")
    perms = rbac.permissions_for(db, user)

    assert P.MENU_MANUAL_CHECK not in perms
    assert P.MENU_PENDING_CHECK not in perms
    assert P.MENU_UPLOAD_AUDIO in perms
    assert P.MENU_UPLOAD_TRANSCRIPT in perms
    # Menu Results ikut dicabut sejak 17 September 2026 (069a13f): tempat poin
    # scorecard login Collection adalah Collection Results.
    assert P.MENU_RESULTS not in perms
    assert P.MENU_COLLECTION_RESULTS in perms
    # Yang tersisa tetap utuh — ini penyesuaian, bukan pencabutan menyeluruh.
    assert P.MENU_STATS in perms


def test_permissions_for_user_cashline_role_sama_tidak_berubah(db, collection_env):
    """Role ``qc`` yang sama dipakai kedua sisi; Cashline harus persis seperti dulu."""
    user = _user_with_campaign(db, "Cashline")
    perms = rbac.permissions_for(db, user)

    assert P.MENU_MANUAL_CHECK in perms
    assert P.MENU_PENDING_CHECK in perms
    assert P.MENU_UPLOAD_AUDIO not in perms
    assert P.MENU_UPLOAD_TRANSCRIPT not in perms


# --------------------------------------------------------------------------
# MENU_COLLECTION_RESULTS — menu hasil audit berbobot Collection
# --------------------------------------------------------------------------

def test_menu_collection_results_ditambahkan_untuk_login_collection():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS}, ["Collection"], COLLECTION)
    assert P.MENU_COLLECTION_RESULTS in out


def test_menu_collection_results_tidak_bocor_ke_cashline():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS}, ["Cashline"], COLLECTION)
    assert P.MENU_COLLECTION_RESULTS not in out


def test_menu_collection_results_tidak_pernah_diberikan_statis_ke_admin():
    """Diberikan saat request oleh ``permissions_for``; kalau ikut statis di role
    admin, menunya tetap muncul walau ``COLLECTION_CAMPAIGNS`` kosong."""
    assert P.MENU_COLLECTION_RESULTS not in P._ADMIN_PERMISSIONS
    assert P.MENU_COLLECTION_RESULTS not in P.DEFAULT_ROLES["admin"]["permissions"]
    assert P.MENU_COLLECTION_RESULTS not in P.DEFAULT_ROLES["demo"]["permissions"]


def test_menu_collection_results_punya_label_manage_role():
    labels = {code for _group, rows in P.PERMISSION_GROUPS for code, _label in rows}
    assert P.MENU_COLLECTION_RESULTS in labels


def test_menu_collection_results_admin_only():
    """Harus tetap ADMIN_ONLY (berbeda dari sibling Upload Audio/Transcript di
    COLLECTION_ADDED_PERMISSIONS, yang dilepas 23 September 2026) supaya tidak bisa disimpan langsung ke role bersama (qc,
    team_leader_qc, spq_head) lewat Manage Role — satu-satunya jalan capability
    ini boleh muncul di luar role admin-like adalah penyesuaian per-request di
    ``collection_adjusted_permissions`` untuk login yang efektif Collection."""
    assert P.MENU_COLLECTION_RESULTS in P.ADMIN_ONLY_PERMISSIONS


def test_menu_collection_results_tetap_di_collection_added():
    assert P.MENU_COLLECTION_RESULTS in P.COLLECTION_ADDED_PERMISSIONS


# --------------------------------------------------------------------------
# permissions_for — MENU_COLLECTION_RESULTS dihitung saat request
# --------------------------------------------------------------------------

def _fake_role(monkeypatch, *, permissions, scope, effective):
    monkeypatch.setattr(rbac, "_role_def", lambda db, key: {
        "permissions": set(permissions), "data_scope": scope, "campaigns": []})
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: effective)


_USER = object()


class _FakeUser:
    """Beda dengan ``_USER`` (``object()``): ``permissions_for`` sekarang butuh
    ``role`` sungguhan untuk memeriksa ``ADMIN_LIKE_ROLES``."""

    def __init__(self, role):
        self.role = role


@pytest.mark.parametrize("role_key", ["team_leader_qc", "spq_head", "telesales_head"])
def test_role_non_admin_tanpa_batas_campaign_tidak_mendapat_menu(monkeypatch, collection_env, role_key):
    """Keputusan 17 September 2026: login non-Admin tanpa batas campaign
    (``effective_campaigns_for`` None, mis. SPQ Head / TL QC pusat) tidak lagi
    melihat Collection Results — sebelumnya test ini mengharapkan sebaliknya."""
    role = P.DEFAULT_ROLES[role_key]
    _fake_role(monkeypatch, permissions=role["permissions"], scope=role["data_scope"], effective=None)
    assert P.MENU_COLLECTION_RESULTS not in rbac.permissions_for(None, _FakeUser(role_key))


@pytest.mark.parametrize("role_key", ["admin", "demo"])
def test_role_admin_like_tanpa_batas_campaign_mendapat_menu(monkeypatch, collection_env, role_key):
    """Admin & demo (``ADMIN_LIKE_ROLES``) tetap mendapat menu tanpa perlu
    di-assign campaign Collection secara eksplisit."""
    role = P.DEFAULT_ROLES[role_key]
    _fake_role(monkeypatch, permissions=role["permissions"], scope=role["data_scope"], effective=None)
    assert P.MENU_COLLECTION_RESULTS in rbac.permissions_for(None, _FakeUser(role_key))


def test_env_kosong_tidak_ada_menu_bahkan_untuk_admin(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    # Termasuk bila capability-nya (masih) tersimpan di baris role DB.
    _fake_role(monkeypatch, permissions=set(P._ADMIN_PERMISSIONS) | {P.MENU_COLLECTION_RESULTS},
               scope=P.SCOPE_ALL, effective=None)
    assert P.MENU_COLLECTION_RESULTS not in rbac.permissions_for(None, _USER)


@pytest.mark.parametrize("scope", [P.SCOPE_SALES_AM, P.SCOPE_SALES_TL, P.SCOPE_SALES_AGENT])
def test_cakupan_sales_tidak_mendapat_menu(monkeypatch, collection_env, scope):
    _fake_role(monkeypatch, permissions={P.MENU_RESULTS}, scope=scope, effective=["Collection"])
    assert P.MENU_COLLECTION_RESULTS not in rbac.permissions_for(None, _USER)


def test_batas_campaign_beririsan_dengan_collection_mendapat_menu(monkeypatch, collection_env):
    """Campuran Collection + Cashline: alur assign tetap, menu Collection ada."""
    _fake_role(monkeypatch, permissions={P.MENU_RESULTS, P.MENU_ASSIGN_TICKET},
               scope=P.SCOPE_QC_ASSIGNED, effective=["Cashline", " COLLECTION "])
    perms = rbac.permissions_for(None, _USER)
    assert P.MENU_COLLECTION_RESULTS in perms
    assert P.MENU_ASSIGN_TICKET in perms


@pytest.mark.parametrize("effective", [["Cashline"], []])
def test_batas_campaign_tanpa_collection_tidak_mendapat_menu(monkeypatch, collection_env, effective):
    _fake_role(monkeypatch, permissions={P.MENU_RESULTS, P.MENU_COLLECTION_RESULTS},
               scope=P.SCOPE_ALL, effective=effective)
    assert P.MENU_COLLECTION_RESULTS not in rbac.permissions_for(None, _USER)


def test_permissions_for_tidak_mengubah_set_cache_role(monkeypatch, collection_env):
    cached = {P.MENU_RESULTS}
    monkeypatch.setattr(rbac, "_role_def", lambda db, key: {
        "permissions": cached, "data_scope": P.SCOPE_ALL, "campaigns": []})
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, u: None)
    rbac.permissions_for(None, _USER)
    assert cached == {P.MENU_RESULTS}


@pytest.mark.parametrize("role,scope,campaigns,expected", [
    ("qc", "cakupan_kustom", ["Collection"], False),
    ("qc", None, ["Collection"], False),
    ("admin", "cakupan_kustom", None, False),
    ("admin", P.SCOPE_ALL, None, True),
    ("demo", P.SCOPE_ALL, None, True),
    ("qc", P.SCOPE_QC_ASSIGNED, ["Collection"], True),
    ("qc_support", P.SCOPE_QC_SUPPORT_OWN, ["Collection"], True),
])
def test_collection_results_visible_hanya_cakupan_yang_dikenal(role, scope, campaigns, expected):
    """Cakupan di luar all/qc_assigned/qc_support_own ditolak
    ``qc_scope.collection_view_scope`` — menunya tidak boleh muncul dengan daftar yang
    pasti kosong."""
    assert rbac.collection_results_visible(role, scope, campaigns, COLLECTION) is expected


def test_reject_collection_only_stats_env_kosong_tanpa_kerja_db(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")

    def _jangan_dipanggil(*a, **kw):
        raise AssertionError("stats_views_for tidak boleh dipanggil saat env kosong")

    monkeypatch.setattr(rbac, "stats_views_for", _jangan_dipanggil)
    assert rbac.reject_collection_only_stats(None, _USER) is None


# --------------------------------------------------------------------------
# stats_views — subset Cashline/Collection untuk menu Stats (/auth/me)
# --------------------------------------------------------------------------

ENV = frozenset({"collection"})
ALL = {P.MENU_STATS}


@pytest.mark.parametrize("role,perms_,scope,campaigns,env,expected", [
    ("admin", ALL, "all", None, ENV, ["cashline", "collection"]),
    ("demo", ALL, "all", None, ENV, ["cashline", "collection"]),
    ("admin", ALL, "all", None, frozenset(), ["cashline"]),
    ("spq_head", ALL, "all", None, ENV, ["cashline"]),
    ("qc", ALL, "qc_assigned", ["Collection"], ENV, ["collection"]),
    ("qc", ALL, "qc_assigned", ["Cashline"], ENV, ["cashline"]),
    ("qc", ALL, "qc_assigned", ["Cashline", " COLLECTION "], ENV, ["cashline", "collection"]),
    ("team_leader", ALL, "sales_tl", ["Cashline", "Collection"], ENV, ["cashline"]),
    ("sales_agent", ALL, "sales_agent", ["Collection"], ENV, []),
    ("qc", ALL, "qc_assigned", [], ENV, []),
    ("qc", set(), "qc_assigned", ["Collection"], ENV, []),
    ("qc", ALL, "qc_assigned", ["Collection"], frozenset(), ["cashline"]),
])
def test_stats_views(role, perms_, scope, campaigns, env, expected):
    assert rbac.stats_views(role, perms_, scope, campaigns, env) == expected


# --------------------------------------------------------------------------
# Upload Audio / Upload Transcript untuk SPQ Head & TL QC (23 September 2026)
# --------------------------------------------------------------------------

_UPLOAD_PERMS = (P.MENU_UPLOAD_AUDIO, P.MENU_UPLOAD_TRANSCRIPT,
                 P.AUDIO_UPLOAD, P.TRANSCRIPT_UPLOAD)


@pytest.mark.parametrize("role", ["spq_head", "team_leader_qc", "admin", "demo"])
def test_upload_audio_transkrip_ada_di_role(role):
    perms = P.DEFAULT_ROLES[role]["permissions"]
    for p in _UPLOAD_PERMS:
        assert p in perms, (role, p)


def test_upload_audio_transkrip_bukan_admin_only():
    """Kalau masih ADMIN_ONLY, menyimpan SPQ Head / TL QC lewat Manage Role akan
    mencabutnya diam-diam (form tidak mengirimnya, dan hanya role admin-like yang
    membawanya dari DB) — atau ditolak 422."""
    for p in _UPLOAD_PERMS:
        assert p not in P.ADMIN_ONLY_PERMISSIONS, p
    # Menu Upload Data lainnya tetap milik Admin.
    for p in (P.MENU_UPLOAD_CAMPAIGN, P.MENU_GET_RESULT,
              P.MENU_UPLOAD_QC_DATABASE,
              P.MENU_REPROCESS_TICKETS):
        assert p in P.ADMIN_ONLY_PERMISSIONS, p


def test_upload_database_sales_tl_qc_tidak_admin_only():
    """Diberikan ke TL QC sejak migrasi 0052; kalau masih ADMIN_ONLY, menyimpan
    role itu lewat Manage Role mencabutnya diam-diam."""
    for p in (P.MENU_UPLOAD_SALES_DATABASE, P.ADMIN_SALES_DATABASE_WRITE):
        assert p not in P.ADMIN_ONLY_PERMISSIONS, p
        assert p in P.DEFAULT_ROLES["team_leader_qc"]["permissions"], p
    assert P.MENU_SALES_DATABASE in P.ADMIN_ONLY_PERMISSIONS
