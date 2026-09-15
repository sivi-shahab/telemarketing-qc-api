"""Usulan Manual Status ikut mengisi antrean menu "Manual Check" (3 September 2026).

Sebelumnya menu itu hanya membaca ``error_code_appeals``, sehingga QC yang mengajukan
perubahan Manual Status tidak pernah melihat tiketnya di sana — padahal itu juga aju
banding yang menunggu keputusan.

Dua aturan yang mudah tergelincir dan karena itu dikunci di sini:

* vonis yang DITETAPKAN LANGSUNG oleh Team Leader QC / SPQ Head (``origin`` selain
  ``qc``) BUKAN aju banding — tidak ada yang menunggu keputusan siapa pun, jadi ia
  tidak boleh memunculkan tiket di antrean;
* bentuk keluarannya harus sama dengan ``_appeal_summary`` supaya menu itu bisa
  menjumlahkan keduanya tanpa tahu asalnya.
"""
import pytest

from api.routers.stats import _appeal_summary, _manual_appeal_summary


class _Req:
    """Baris qc_status_requests secukupnya untuk helper ini."""

    def __init__(self, tl_qc_status="pending", approval_status="pending", origin="qc"):
        self.tl_qc_status = tl_qc_status
        self.approval_status = approval_status
        self.origin = origin


def test_tanpa_usulan_menghasilkan_None():
    assert _manual_appeal_summary(None) is None


def test_vonis_langsung_atasan_bukan_aju_banding():
    """set_langsung oleh TL QC / SPQ Head tidak menunggu keputusan siapa pun."""
    assert _manual_appeal_summary(_Req(origin="set_langsung")) is None
    assert _manual_appeal_summary(_Req(origin="tl_qc")) is None


def test_usulan_qc_menunggu_TL():
    s = _manual_appeal_summary(_Req(tl_qc_status="pending"))
    assert s["total"] == 1
    assert s["pending"] == 1 and s["approved"] == 0 and s["rejected"] == 0
    assert s["tl_pending"] == 1, "menunggu giliran Team Leader QC"
    assert s["spq_pending"] == 0


def test_usulan_yang_di_escalate_menunggu_SPQ():
    s = _manual_appeal_summary(_Req(tl_qc_status="escalated", approval_status="pending"))
    assert s["pending"] == 1
    assert s["tl_pending"] == 0, "giliran TL QC sudah lewat"
    assert s["spq_pending"] == 1


def test_disetujui_TL_tidak_lagi_menunggu_siapa_pun():
    s = _manual_appeal_summary(_Req(tl_qc_status="approved"))
    assert s["approved"] == 1 and s["pending"] == 0
    assert s["tl_pending"] == 0 and s["spq_pending"] == 0


def test_ditolak_TL_tidak_lagi_menunggu_tetapi_tetap_terhitung():
    """Ditolak = sudah diputus, tetapi QC masih perlu menindaklanjutinya."""
    s = _manual_appeal_summary(_Req(tl_qc_status="rejected"))
    assert s["rejected"] == 1 and s["approved"] == 0
    assert s["tl_pending"] == 0 and s["spq_pending"] == 0
    assert s["total"] == 1, "tetap dihitung: total > approved berarti belum tuntas bagi QC"


def test_origin_hilang_dianggap_usulan_qc():
    """Baris lama tanpa kolom origin: bawaannya usulan QC, bukan vonis langsung."""
    class _Lama:
        tl_qc_status = "pending"
        approval_status = "pending"

    assert _manual_appeal_summary(_Lama()) is not None


@pytest.mark.parametrize("kunci", ["total", "pending", "approved", "rejected",
                                   "tl_pending", "spq_pending"])
def test_sebentuk_dengan_appeal_summary(kunci):
    """Menu Manual Check menjumlahkan keduanya, jadi kuncinya harus sama."""
    class _Appeal:
        error_code, item_code = "B10", "SC_CL_4"
        tl_qc_status, approval_status = "pending", "pending"
        qc_reason = reviewed_by_username = requested_by_username = None
        reviewed_at = requested_at = tl_qc_reviewed_at = None

    a = _appeal_summary([_Appeal()])
    m = _manual_appeal_summary(_Req())
    assert kunci in a and kunci in m
