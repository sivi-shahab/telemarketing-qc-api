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
    assert out == {P.MENU_RESULTS} | set(P.COLLECTION_ADDED_PERMISSIONS)


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
    # Yang tersisa tetap utuh — ini penyesuaian, bukan pencabutan menyeluruh.
    assert P.MENU_RESULTS in perms


def test_permissions_for_user_cashline_role_sama_tidak_berubah(db, collection_env):
    """Role ``qc`` yang sama dipakai kedua sisi; Cashline harus persis seperti dulu."""
    user = _user_with_campaign(db, "Cashline")
    perms = rbac.permissions_for(db, user)

    assert P.MENU_MANUAL_CHECK in perms
    assert P.MENU_PENDING_CHECK in perms
    assert P.MENU_UPLOAD_AUDIO not in perms
    assert P.MENU_UPLOAD_TRANSCRIPT not in perms
