"""Proxy PDF transkrip App C: ``GET /tickets_daily_pdf/{tiket_id}``.

Regression guard untuk dua cacat yang lahir dari pola yang sama — halaman detail
transkrip menembak App C LANGSUNG DARI BROWSER:

1. ``X-API-Key`` App C ikut ter-inline ke bundle JS (bahkan sebagai nilai bawaan
   di dalam berkas ``.vue``), jadi terbaca siapa pun yang membuka DevTools.
2. Permintaannya tidak pernah melewati App B, sehingga
   ``rbac.effective_campaigns_for`` tidak berlaku: siapa pun yang memegang key itu
   bisa mengunduh PDF tiket campaign mana pun.

Test di sini mengunci perilaku penggantinya: key tinggal di server, dan PDF hanya
keluar bila tiketnya memang ada di dalam cakupan campaign pemanggil.

Pasangannya ``tests/test_campaign_context_scope.py``, yang mengunci hal setara
untuk daftar barisnya (``GET /tickets_daily``).
"""
import pytest
from fastapi import HTTPException

from api.routers import tickets_daily_pdf as tp


PDF_BYTES = b"%PDF-1.4 dummy"

# Baris App C untuk tiket yang diminta. `context` inilah jembatan ke nama campaign
# App B — lihat api/campaign_context.py untuk alasan tidak memakai kode campaign.
UPSTREAM = {
    "mode": "search",
    "load_date": None,
    "items": [
        {"tiket_id": "T-CASH", "campaign": "CLENTB", "context": "cashline"},
        {"tiket_id": "T-NTB", "campaign": "ACT02", "context": "ntb"},
    ],
    "total": 2,
    "truncated": False,
}


@pytest.fixture
def stub_app_c(monkeypatch):
    """App C dipalsukan. ``calls`` merekam apa yang benar-benar ditembak."""
    calls = {"pdf": [], "lookup": []}

    def _fake_fetch_pdf(tiket_id):
        calls["pdf"].append(tiket_id)
        return PDF_BYTES

    def _fake_fetch_all(**kwargs):
        calls["lookup"].append(kwargs)
        return dict(UPSTREAM, items=list(UPSTREAM["items"]))

    monkeypatch.setattr(tp.vs, "fetch_pdf", _fake_fetch_pdf)
    monkeypatch.setattr(tp.tms, "fetch_all", _fake_fetch_all)
    monkeypatch.setenv("CAMPAIGN_CONTEXT_MAP", "Cashline:cashline,Collection:collection")
    return calls


def _call(monkeypatch, scope, tiket_id):
    """Panggil endpoint dengan ``effective_campaigns_for`` dipatok ``scope``."""
    monkeypatch.setattr(tp, "effective_campaigns_for", lambda db, user: scope)
    return tp.get_tickets_daily_pdf(tiket_id=tiket_id, db=object(), current_user=object())


# --------------------------------------------------------------------------
# Cakupan campaign
# --------------------------------------------------------------------------

def test_unrestricted_login_gets_the_pdf(monkeypatch, stub_app_c):
    res = _call(monkeypatch, None, "T-CASH")
    assert res.body == PDF_BYTES
    assert res.media_type == "application/pdf"


def test_unrestricted_login_does_not_pay_for_a_scope_lookup(monkeypatch, stub_app_c):
    """Tidak dibatasi = tidak ada yang perlu dicocokkan; App C cukup ditembak sekali.

    Pencarian tiket di App C berarti belasan request beruntun, jadi jalur yang
    paling sering dipakai (SPQ/admin) tidak boleh ikut menanggungnya.
    """
    _call(monkeypatch, None, "T-CASH")
    assert stub_app_c["lookup"] == []


def test_cashline_login_gets_a_cashline_ticket(monkeypatch, stub_app_c):
    res = _call(monkeypatch, ["Cashline"], "T-CASH")
    assert res.body == PDF_BYTES


def test_cashline_login_cannot_fetch_an_ntb_ticket(monkeypatch, stub_app_c):
    """Inti kebocorannya: PDF di luar cakupan campaign harus ditolak."""
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, ["Cashline"], "T-NTB")
    assert exc.value.status_code == 404
    assert stub_app_c["pdf"] == []  # App C tidak ditembak sama sekali


def test_collection_login_cannot_fetch_any_of_todays_tickets(monkeypatch, stub_app_c):
    """Per 2026-08-28 App C belum mengirim baris ber-context ``collection``."""
    for tiket in ("T-CASH", "T-NTB"):
        with pytest.raises(HTTPException) as exc:
            _call(monkeypatch, ["Collection"], tiket)
        assert exc.value.status_code == 404


def test_empty_scope_short_circuits_without_calling_app_c(monkeypatch, stub_app_c):
    """Cakupan kosong = tidak melihat apa pun; App C tidak perlu ditembak."""
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, [], "T-CASH")
    assert exc.value.status_code == 404
    assert stub_app_c["pdf"] == [] and stub_app_c["lookup"] == []


# --------------------------------------------------------------------------
# Gagal tertutup
# --------------------------------------------------------------------------

def test_unknown_ticket_is_refused_when_scope_is_active(monkeypatch, stub_app_c):
    """Tiket yang tidak ditemukan DITOLAK, bukan diloloskan.

    Kalau "tidak ketemu" diartikan "tidak apa-apa, teruskan saja", satu pencarian
    yang meleset cukup untuk menembus pembatasan campaign.
    """
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, ["Cashline"], "T-TIDAK-ADA")
    assert exc.value.status_code == 404
    assert stub_app_c["pdf"] == []


def test_ticket_id_is_matched_exactly_not_by_substring(monkeypatch, stub_app_c):
    """App C mencari ``tiket_id`` sebagai SUBSTRING, jadi hasilnya bisa memuat
    tiket lain. Mencocokkan longgar di sini berarti PDF tiket Cashline bisa
    diloloskan untuk permintaan tiket NTB yang namanya kebetulan bertetangga."""
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, ["Cashline"], "T-")
    assert exc.value.status_code == 404


def test_app_c_failure_becomes_502_not_an_empty_pdf(monkeypatch, stub_app_c):
    def _boom(tiket_id):
        raise tp.vs.ViewStreamError("connection refused")

    monkeypatch.setattr(tp.vs, "fetch_pdf", _boom)
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, None, "T-CASH")
    assert exc.value.status_code == 502


# --------------------------------------------------------------------------
# Key tinggal di server
# --------------------------------------------------------------------------

def test_frontend_no_longer_carries_app_c_credentials():
    """Komponen detail tidak boleh lagi memegang kredensial App C.

    Key-nya dulu ditulis sebagai fallback literal di dalam komponen, jadi ikut
    terbawa ke bundle produksi bahkan ketika env var-nya tidak disetel.

    Yang dicek adalah pemakaiannya, bukan sekadar penyebutan namanya: komentar di
    berkas itu memang menjelaskan header apa yang dulu dikirim, dan melarang kata
    itu muncul sama sekali hanya akan membuat penjelasannya dihapus. Nilai key
    aslinya sengaja TIDAK ditulis di sini — menaruhnya di test berarti tetap
    menyimpannya di repo.
    """
    import re
    from pathlib import Path

    import pytest

    # [ADAPTASI] Di monorepo berkas ini satu pohon dengan API. Sejak pemisahan repo
    # ia tinggal di telemarketing-qc-dashboard, jadi di sini tidak ada yang bisa
    # dibaca. Jangan dihapus: kalau repo dashboard di-checkout berdampingan atau
    # di-mount saat CI, pemeriksaannya jalan lagi apa adanya.
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dashboard/src/views/dashboard/TranscriptDetailView.vue",
        root.parent / "telemarketing-qc-dashboard/src/views/dashboard/TranscriptDetailView.vue",
    ]
    src = next((c for c in candidates if c.exists()), None)
    if src is None:
        pytest.skip("pohon dashboard tidak ada di repo api — lihat telemarketing-qc-dashboard")
    text = src.read_text(encoding="utf-8")

    assert not re.search(r"""['"]?X-API-Key['"]?\s*:""", text), "header X-API-Key masih dikirim"
    assert "VITE_TMS_API_KEY" not in text, "komponen masih membaca key App C"
    assert "VITE_TMS_API_URL" not in text, "komponen masih menembak App C langsung"
    assert "/tickets_daily_pdf/" in text, "komponen belum lewat proxy App B"
