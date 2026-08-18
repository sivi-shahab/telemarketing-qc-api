"""Konfigurasi RIPLAY: setting-nya harus ada, dan error-nya jangan menyamar.

Regresi yang dijaga: kolom **TnC Product** di detail evaluasi selalu "—" karena
tidak ada satu pun campaign yang punya ``riplay_extraction`` — dan itu tidak bisa
diperbaiki lewat menu Upload Campaign, sebab ``_extract_and_gate_riplay`` membaca
empat setting yang tidak pernah dideklarasikan di ``Settings``:

    settings.riplay_model / riplay_max_pages / riplay_render_scale
    settings.riplay_min_similarity

Keempatnya sudah ada di ``.env.example`` tapi tidak di kelas ``Settings``, jadi
``settings.riplay_model`` melempar ``AttributeError`` DI DALAM blok ``try`` dan
tertangkap ``except Exception`` — pengguna melihat **502 "Ekstraksi RIPLAY gagal
dihubungi"**, seolah penyedia LLM tak bisa dihubungi, padahal ini murni salah
konfigurasi aplikasi sendiri.
"""
import pytest
from fastapi import HTTPException

from api.dependencies import Settings
from api.routers import campaign as campaign_router
from compliance import riplay as riplay_lib


# --------------------------------------------------------------------------
# 1. Setting-nya harus ada di kelas Settings
# --------------------------------------------------------------------------

def test_settings_declares_riplay_fields():
    """Keempat setting RIPLAY harus terbaca dari objek Settings."""
    s = Settings()
    assert hasattr(s, "riplay_model")
    assert hasattr(s, "riplay_max_pages")
    assert hasattr(s, "riplay_render_scale")
    assert hasattr(s, "riplay_min_similarity")


def test_riplay_defaults_match_env_example():
    """Default-nya sama dengan yang didokumentasikan di .env.example."""
    s = Settings()
    assert s.riplay_model == ""  # kosong = ikut LLM_MODEL
    assert s.riplay_max_pages == riplay_lib.DEFAULT_MAX_PAGES == 20
    assert s.riplay_render_scale == riplay_lib.DEFAULT_RENDER_SCALE == 2.0
    assert s.riplay_min_similarity == 50.0


# --------------------------------------------------------------------------
# 2. Error konfigurasi vs error penyedia — jangan tertukar
# --------------------------------------------------------------------------

class _BrokenSettings:
    """Settings tanpa atribut riplay_* — meniru bug konfigurasi."""
    llm_model = "gpt-5-mini"
    llm_temperature = 1.0


@pytest.fixture
def no_llm(monkeypatch):
    """Pastikan tidak ada panggilan LLM sungguhan dari test ini."""
    monkeypatch.setattr(campaign_router, "get_llm_client", lambda: object())


def test_config_error_is_not_reported_as_bad_gateway(monkeypatch, no_llm):
    """Salah konfigurasi harus terlihat sebagai salah konfigurasi.

    Menyamarkannya jadi 502 "gagal dihubungi" membuat orang mengejar jaringan dan
    kuota LLM, padahal masalahnya ada di ``Settings`` aplikasi sendiri.
    """
    monkeypatch.setattr(campaign_router, "get_settings", lambda: _BrokenSettings())
    monkeypatch.setattr(riplay_lib, "extract_riplay",
                        lambda *a, **k: pytest.fail("tidak boleh sampai memanggil LLM"))

    with pytest.raises(Exception) as exc:
        campaign_router._extract_and_gate_riplay(b"%PDF-1.4", "Cashline")

    assert not (isinstance(exc.value, HTTPException) and exc.value.status_code == 502), (
        "kesalahan konfigurasi tidak boleh dilaporkan sebagai 502 'gagal dihubungi'"
    )


def test_provider_failure_still_502(monkeypatch, no_llm):
    """Kegagalan penyedia LLM yang SUNGGUHAN tetap 502 — jangan ikut tersempitkan."""
    def _boom(*a, **k):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(campaign_router, "get_settings", lambda: Settings())
    monkeypatch.setattr(riplay_lib, "extract_riplay", _boom)

    with pytest.raises(HTTPException) as exc:
        campaign_router._extract_and_gate_riplay(b"%PDF-1.4", "Cashline")
    assert exc.value.status_code == 502


def test_unparseable_riplay_is_422(monkeypatch, no_llm):
    """PDF yang tidak terbaca modelnya = 422, bukan 502."""
    def _bad_json(*a, **k):
        raise ValueError("LLM did not return parseable JSON")

    monkeypatch.setattr(campaign_router, "get_settings", lambda: Settings())
    monkeypatch.setattr(riplay_lib, "extract_riplay", _bad_json)

    with pytest.raises(HTTPException) as exc:
        campaign_router._extract_and_gate_riplay(b"%PDF-1.4", "Cashline")
    assert exc.value.status_code == 422


def test_product_name_gate_rejects_wrong_riplay(monkeypatch, no_llm):
    """RIPLAY produk lain ditolak 422 supaya KB tidak ketimpa nilai produk lain."""
    monkeypatch.setattr(campaign_router, "get_settings", lambda: Settings())
    monkeypatch.setattr(riplay_lib, "extract_riplay",
                        lambda *a, **k: {"nama_produk": "Kartu Kredit Mega Travel"})

    with pytest.raises(HTTPException) as exc:
        campaign_router._extract_and_gate_riplay(b"%PDF-1.4", "Cashline")
    assert exc.value.status_code == 422
    assert "tidak cocok" in str(exc.value.detail)
