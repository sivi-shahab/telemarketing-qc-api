"""Siapa yang mendapat menu OCR Gambar (``menu.ocr_image``).

Admin/Demo memegangnya lewat role. User lain hanya bila campaign efektifnya
tercantum di env ``OCR_IMAGE_CAMPAIGNS`` — dihitung saat request, sama seperti
menu Collection Results, supaya menu DAN endpoint tertutup bersamaan.
"""
from types import SimpleNamespace

from api import permissions as P
from api import rbac


OCR = frozenset({"complaint handling"})


def test_campaign_tercantum_diberi():
    assert rbac.ocr_image_granted(["Complaint Handling"], OCR)


def test_nama_dicocokkan_tanpa_peduli_spasi_dan_kapital():
    assert rbac.ocr_image_granted(["  COMPLAINT handling "], OCR)


def test_campaign_lain_tidak_diberi():
    assert not rbac.ocr_image_granted(["Telemarketing", "Cashline", "Collection"], OCR)


def test_tanpa_batas_campaign_tidak_diberi():
    """``None`` = tidak dibatasi (mis. SPQ Head pusat) — bukan berarti memegang
    Complaint Handling secara eksplisit."""
    assert not rbac.ocr_image_granted(None, OCR)


def test_env_kosong_tidak_diberi():
    assert not rbac.ocr_image_granted(["Complaint Handling"], frozenset())


def test_env_dibaca_tiap_panggilan(monkeypatch):
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", " Complaint Handling , ,X ")
    assert rbac.ocr_image_campaigns_from_env() == frozenset({"complaint handling", "x"})
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "")
    assert rbac.ocr_image_campaigns_from_env() == frozenset()


def test_admin_memegang_lewat_role_dan_admin_only():
    assert P.MENU_OCR_IMAGE == "menu.ocr_image"
    assert P.MENU_OCR_IMAGE in P.ALL_PERMISSIONS
    assert P.MENU_OCR_IMAGE in P.ADMIN_ONLY_PERMISSIONS
    assert P.MENU_OCR_IMAGE in P.DEFAULT_ROLES["admin"]["permissions"]


def _patch_role(monkeypatch, perms, campaigns):
    monkeypatch.setattr(rbac, "_role_def", lambda db, key: {
        "permissions": list(perms), "data_scope": "qc_assigned", "campaigns": [],
    })
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, user: campaigns)
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection,Complaint Handling")


def test_permissions_for_menambahkan_untuk_user_complaint_handling(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE in out


def test_permissions_for_tidak_menambahkan_untuk_user_cashline(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Telemarketing", "Cashline"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE not in out


def test_permissions_for_env_ocr_kosong(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE not in out


def test_permissions_for_saat_collection_mati(monkeypatch):
    """Cabang ``COLLECTION_CAMPAIGNS`` kosong punya return lebih awal — gate OCR
    tetap harus berlaku di sana."""
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE in out
