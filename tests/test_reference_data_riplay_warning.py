"""RIPLAY yang belum diunggah harus berbunyi, bukan diam.

Regresi yang dijaga: tanpa ``riplay_extraction``, blok TNC PRODUCT REFERENCE DATA
terkirim ke LLM berisi null semua. Akibatnya kolom **TnC Product** kosong DAN langkah
"CEK ENVELOPE — LANGKAH WAJIB" di prompt tidak pernah tereksekusi — nilai TMS di luar
ketentuan produk (tenor 6 bulan padahal hanya 12/24/36, biaya admin salah tier) lolos
tanpa tercatat, baik di ``reason`` maupun sebagai error code B03.

Kegagalan itu SUNYI: tidak ada error, tidak ada log, tidak ada penanda di hasil. Satu-
satunya gejalanya adalah kolom kosong di layar, dan itulah sebabnya kondisi ini bertahan
berbulan-bulan tanpa ketahuan (lihat issue.md 18 September 2026).

RIPLAY sendiri memang OPSIONAL — campaign tanpa RIPLAY tetap sah dan tetap harus bisa
diproses. Jadi yang diminta di sini warning, bukan exception.
"""
import pytest

from compliance import reference_data as rd


@pytest.fixture
def no_db_rows(monkeypatch):
    """Tiket tanpa baris acuan sama sekali — menyingkirkan ketergantungan DB.

    Jalur reference data memang dirancang tetap jalan tanpa baris acuan (setiap baris
    yang hilang jadi null + warning), jadi ini bentuk paling ringkas untuk menguji
    warning-nya tanpa menyentuh Postgres.
    """
    monkeypatch.setattr(rd.crud, "get_tms_cashline_by_result_id", lambda db, cid: None)
    monkeypatch.setattr(rd.crud, "get_ascend_custp_by_result_id", lambda db, cid: None)


def _warnings(riplay_extraction):
    _text, warnings, _raw = rd.build_reference_data(
        "TIKET-UJI", db=None, riplay_extraction=riplay_extraction
    )
    return warnings


def _riplay_warnings(warnings):
    return [w for w in warnings if "riplay" in w.lower()]


def test_missing_riplay_emits_warning(no_db_rows):
    """Tanpa riplay_extraction, harus ada tepat satu warning yang menyebutkannya."""
    hits = _riplay_warnings(_warnings(None))
    assert len(hits) == 1, f"harus tepat satu warning RIPLAY, dapat: {hits}"


def test_warning_names_both_consequences(no_db_rows):
    """Warning-nya harus menyebut AKIBATNYA, bukan sekadar 'riplay kosong'.

    Yang membaca log ini orang yang sedang menyelidiki kolom kosong atau error code
    yang tidak muncul. Menyebut dua akibatnya membuat log ini menjawab pertanyaannya
    langsung, tanpa harus menelusuri kode lebih dulu.
    """
    warn = _riplay_warnings(_warnings(None))[0].lower()
    assert "tnc product" in warn
    assert "envelope" in warn


def test_empty_dict_counts_as_missing(no_db_rows):
    """``{}`` sama saja dengan NULL.

    ``build_tnc_product_reference`` memakai ``if not extraction``, jadi dict kosong
    menghasilkan blok null yang sama persis. Warning-nya harus ikut konsisten, bukan
    hanya mengecek ``is None``.
    """
    assert len(_riplay_warnings(_warnings({}))) == 1


def test_present_riplay_stays_silent(no_db_rows):
    """RIPLAY terisi = tidak ada warning. Jangan berisik saat semuanya benar."""
    extraction = {"limit_pencairan": {"minimum": "Rp 2.000.000", "maksimum": "Rp 200.000.000"}}
    assert _riplay_warnings(_warnings(extraction)) == []


def test_missing_riplay_is_not_an_error(no_db_rows):
    """Campaign tanpa RIPLAY tetap harus bisa diproses — warning, BUKAN exception.

    Kalau ini di-raise seperti prompt/scorecard/KB yang kosong, semua campaign yang
    memang tidak punya RIPLAY ikut mati.
    """
    text, _warnings_, _raw = rd.build_reference_data(
        "TIKET-UJI", db=None, riplay_extraction=None
    )
    assert "=== TNC PRODUCT REFERENCE DATA ===" in text
