"""Unit test compliance.collection_report — port Python dari
qc-collection/src/server/weightedReport.ts.

Dua aturan yang dijaga: (1) setiap field yang dibaca dashboard selalu ada dengan
tipe yang benar; (2) tidak ada verdict yang dikarang.
"""
from compliance.collection_report import (
    PASSING_GRADE_RATIO,
    normalize_weighted_report,
    scorecard_maximum,
)


def _item(code, weight, status, **extra):
    return {"category": "Pembukaan", "item_code": code, "requirement": f"req {code}",
            "kb_reference": f"KB_{code}", "tolerable": "YES", "weight": weight,
            "status": status, **extra}


def test_input_bukan_dict_menghasilkan_laporan_kosong_yang_gagal():
    r = normalize_weighted_report(None)
    assert r["scorecard_result"] == []
    assert r["maximum_score"] == 0
    assert r["ai_status"] == "FAIL"
    assert r["critical_compliance_check"] == {"status": "TIDAK_TERSEDIA", "checked_items": []}
    assert r["commitment_status"]["status"] == "NOT_STATED"
    assert r["commitment_status"]["evidence"] == {"timestamp": None, "quote": None}


def test_skor_dihitung_ulang_dari_scorecard_bukan_dari_model():
    raw = {"maximum_score": 116, "ai_score_phase_2": 116, "ai_status": "PASS",
           "scorecard_result": [_item("A", 10, "SESUAI"), _item("B", 10, "BELUM_SESUAI")]}
    r = normalize_weighted_report(raw)
    assert r["maximum_score"] == 20
    assert r["ai_score_phase_2"] == 10
    assert r["passing_grade"] == 18
    assert r["ai_status"] == "FAIL"


def test_maksimum_dari_konfigurasi_mengalahkan_jumlah_item_jawaban():
    raw = {"scorecard_result": [_item("A", 10, "SESUAI")]}
    r = normalize_weighted_report(raw, configured_maximum=134)
    assert r["maximum_score"] == 134
    assert r["passing_grade"] == round(134 * PASSING_GRADE_RATIO, 1)


def test_item_score_diturunkan_dari_verdict_bila_model_diam():
    raw = {"scorecard_result": [_item("A", 6, "PASS"), _item("B", 4, "FAIL"), _item("C", 3, "??")]}
    items = normalize_weighted_report(raw)["scorecard_result"]
    assert [(i["status"], i["item_score"]) for i in items] == [
        ("SESUAI", 6), ("BELUM_SESUAI", 0), ("TIDAK_DINILAI", None)]


def test_evidence_string_masuk_reason_bukan_quote():
    raw = {"scorecard_result": [_item("A", 1, "SESUAI", evidence="Agent menyapa")]}
    item = normalize_weighted_report(raw)["scorecard_result"][0]
    assert item["reason"] == "Agent menyapa"
    assert item["evidence"] == {"timestamp": None, "quote": None}


def test_critical_check_bentuk_datar_tidak_diterjemahkan():
    raw = {"critical_compliance_check": {"verifikasi_identitas": False, "kebocoran_data": True}}
    assert normalize_weighted_report(raw)["critical_compliance_check"]["status"] == "TIDAK_TERSEDIA"


def test_verifikasi_data_bentuk_datar_tanpa_verdict_match():
    raw = {"collection_data_verification": {"total_tagihan": 450000}}
    rows = normalize_weighted_report(raw)["collection_data_verification"]
    assert rows == [{"field": "total_tagihan", "reference_value": None, "extracted_value": 450000,
                     "match": "TIDAK_TERSEDIA", "similarity_percent": None, "reason": "",
                     "item_score": None}]


def test_commitment_ada_kesepakatan_dibaca_sebagai_committed():
    raw = {"commitment_status": {"ada_kesepakatan": True, "ringkasan": "janji bayar"}}
    c = normalize_weighted_report(raw)["commitment_status"]
    assert c["status"] == "COMMITTED_TO_PAY"
    assert c["reason"] == "janji bayar"


def test_error_code_daftar_string():
    r = normalize_weighted_report({"error_codes": ["E01", " ", "E02"]})
    assert [e["error_code"] for e in r["error_codes"]] == ["E01", "E02"]
    assert r["error_codes"][0]["trigger_source"]["evidence"] == {"timestamp": None, "quote": None}


def test_category_summary_varian_datar():
    raw = {"category_summary": [{"category": "X", "maximum_score": 8, "score": 5, "category_result": "pass"}]}
    assert normalize_weighted_report(raw)["category_summary"] == [
        {"category": "X", "total_weight": 8, "earned_score": 5, "category_result": "PASS", "fail_reason": None}]


def test_scorecard_maximum():
    assert scorecard_maximum('[{"weight": 4}, {"weight": 6.5}, {"x": 1}]') == 10.5
    assert scorecard_maximum("bukan json") is None
    assert scorecard_maximum('{"weight": 3}') is None
    assert scorecard_maximum("[]") is None
