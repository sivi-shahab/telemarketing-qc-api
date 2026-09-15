"""Jalan pintas "qc_confirm" sudah dicabut (3 September 2026).

Antara 10 Agustus dan 3 September 2026, penetapan PERTAMA oleh QC yang nilainya SAMA
dengan AI Status berlaku final saat itu juga — alasannya "QC hanya membenarkan
penilaian mesin, tidak ada yang berubah". Praktiknya justru ada yang berubah: kolom
Manual Status tiket ber-AI-Status Qualified sudah menampilkan "Qualified" sebagai nilai
bawaan, sehingga bagi QC layar itu terbaca sebagai "mengubah vonis menjadi Qualified" —
dan vonis itu langsung jadi tanpa satu pun reviewer melihatnya.

Aturannya sekarang satu kalimat: SETIAP vonis QC berjalan QC -> TL QC -> SPQ Head,
tanpa pengecualian. Test ini menjaga supaya jalan pintas itu tidak diam-diam kembali —
gejalanya halus (vonis yang seharusnya menunggu justru sudah final), dan tidak ada
yang error saat itu terjadi.
"""
import pytest

from api.routers import qc_status as qs


class _User:
    username, role = "qc-1", "qc"


class _Result:
    id = "r-1"
    status = "done"


@pytest.fixture()
def submit(monkeypatch):
    """``submit_qc_status_request`` dengan ketergantungan DB/RBAC di-stub.

    ``seen`` menangkap argumen yang diteruskan ke ``upsert_qc_status_request`` — di
    situlah ``origin`` diputuskan.
    """
    seen = {}

    monkeypatch.setattr(qs, "_validate_result", lambda db, rid: _Result())
    monkeypatch.setattr(qs, "ensure_can_view_result", lambda db, u, r: None)
    # Tanpa MANUAL_STATUS_DIRECT -> usulan biasa milik QC.
    monkeypatch.setattr(qs, "has_perm", lambda db, u, p: False)
    monkeypatch.setattr(qs.crud, "upsert_qc_status_request",
                        lambda db, **kw: seen.update(kw) or object())
    monkeypatch.setattr(qs.crud, "finalize_qc_status_request",
                        lambda *a, **k: pytest.fail("vonis QC tidak boleh final saat dibuat"))
    monkeypatch.setattr(qs, "QcStatusRequestInfo", None, raising=False)

    def _call(status_value):
        qs.submit_qc_status_request(
            result_id="r-1", requested_status=status_value, reason="alasan",
            db=None, current_user=_User(),
        )
        return seen

    return _call


def test_vonis_qc_selalu_berorigin_qc(submit):
    """Termasuk PASS, nilai yang paling sering sama dengan AI Status."""
    assert submit("PASS")["origin"] == "qc"


def test_vonis_qc_yang_berbeda_juga_berorigin_qc(submit):
    assert submit("FAIL")["origin"] == "qc"


def test_helper_jalan_pintas_sudah_tidak_ada():
    """Kalau ``_confirms_ai_status`` kembali, jalan pintasnya kemungkinan ikut kembali."""
    assert not hasattr(qs, "_confirms_ai_status")


def test_modul_tidak_lagi_menyetel_origin_qc_confirm():
    import inspect

    src = inspect.getsource(qs)
    assert 'origin = "qc_confirm"' not in src


def test_penanganan_baris_LAMA_qc_confirm_tetap_ada():
    """Pencabutan ini menutup jalan untuk vonis BARU; vonis yang sudah terlanjur
    final harus tetap final, jadi crud masih mengenali origin itu."""
    import inspect

    from db import crud

    assert "qc_confirm" in inspect.getsource(crud.upsert_qc_status_request)
