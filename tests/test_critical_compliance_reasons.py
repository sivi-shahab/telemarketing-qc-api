"""Alasan per item Critical Compliance Check.

Model tidak mengirim ``reason`` untuk item critical check, jadi sampai 18 September
2026 item PASS tampil "—" di kolom Alasan. Alasan PASS kini diambil dari item
scorecard ber-``item_code`` sama, yang selalu membawa ``reason`` dari model.
"""

from compliance.error_codes import annotate_critical_compliance_reasons


def _ev(ccc_items, scorecard):
    return {
        "critical_compliance_check": {"status": "PASS", "checked_items": ccc_items},
        "scorecard_result": scorecard,
    }


def _reasons(ev):
    out = annotate_critical_compliance_reasons(ev)
    return {it["item_code"]: it["reason"] for it in out["critical_compliance_check"]["checked_items"]}


def test_pass_mengambil_alasan_dari_item_scorecard_yang_sama():
    ev = _ev(
        [{"item_code": "SC_CL_4", "requirement": "Agent menanyakan kesediaan waktu nasabah", "status": "PASS"}],
        [{"item_code": "SC_CL_4", "status": "SESUAI", "reason": "Agent meminta waktu sebentar kepada nasabah."}],
    )
    assert _reasons(ev) == {"SC_CL_4": "Agent meminta waktu sebentar kepada nasabah."}


def test_pass_tanpa_pasangan_scorecard_tetap_none():
    ev = _ev([{"item_code": "SC_CL_4", "requirement": "x", "status": "PASS"}], [])
    assert _reasons(ev) == {"SC_CL_4": None}


def test_pass_dengan_reason_scorecard_kosong_tetap_none():
    ev = _ev(
        [{"item_code": "SC_CL_4", "requirement": "x", "status": "PASS"}],
        [{"item_code": "SC_CL_4", "status": "SESUAI", "reason": "   "}],
    )
    assert _reasons(ev) == {"SC_CL_4": None}


def test_fail_tetap_memakai_kalimat_sebab_bukan_reason_scorecard():
    ev = _ev(
        [{"item_code": "SC_CL_4", "requirement": "Agent menanyakan kesediaan waktu nasabah", "status": "FAIL"}],
        [{"item_code": "SC_CL_4", "status": "BELUM_SESUAI", "reason": "alasan scorecard"}],
    )
    assert _reasons(ev) == {"SC_CL_4": "Agent tidak menanyakan kesediaan waktu nasabah"}
