"""Unit test compliance.collection_report — port Python dari
qc-collection/src/server/weightedReport.ts.

Dua aturan yang dijaga: (1) setiap field yang dibaca dashboard selalu ada dengan
tipe yang benar; (2) tidak ada verdict yang dikarang.
"""
from datetime import datetime
from types import SimpleNamespace

from compliance.collection_report import (
    PASSING_GRADE_RATIO,
    REPORT_TYPE,
    apply_configured_weights,
    build_collection_result_json,
    collection_list_row,
    is_collection_result_json,
    normalize_stored_report,
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


def test_build_result_json_menandai_jenis_laporan():
    report = normalize_weighted_report({"scorecard_result": [_item("A", 5, "SESUAI")]})
    out = build_collection_result_json(
        result_id="r1", campaign="Collection", source_files=["123_a.pdf"], report=report,
        processed_at="2026-09-17T10:00:00+00:00", processing_sec=12.345)
    assert out["report_type"] == REPORT_TYPE
    assert out["evaluation"] is report
    assert out["num_calls"] == 1
    assert out["processing_sec"] == 12.35
    assert "reference_data" not in out  # jalur Collection tidak membaca TMS/Ascend
    assert is_collection_result_json(out)
    assert not is_collection_result_json({"evaluation": {}})
    assert not is_collection_result_json(None)


def test_list_row_membaca_ulang_lewat_normalizer():
    result = SimpleNamespace(id="r1", campaign="Collection", source_files=["777_x.pdf"],
                             status="done", uploaded_at=datetime(2026, 9, 17, 3, 0),
                             completed_at=None)
    rj = {"report_type": REPORT_TYPE, "evaluation": {
        "agent_name": "Tiwi", "scorecard_result": [_item("A", 10, "SESUAI")],
        "critical_compliance_check": {"status": "fail"}, "error_codes": ["E01"]}}
    row = collection_list_row(result, rj)
    assert row["ticket_id"] == "777"
    assert row["agent_name"] == "Tiwi"
    assert (row["score"], row["maximum_score"], row["ai_status"]) == (10, 10, "PASS")
    # status di-upper-case normalizer, jadi "fail" huruf kecil terbaca FAIL
    assert row["critical_status"] == "FAIL"
    assert row["error_code_count"] == 1


def test_list_row_tanpa_result_json_masih_bisa_dirender():
    result = SimpleNamespace(id="r2", campaign="Collection", source_files=[], status="processing",
                             uploaded_at=None, completed_at=None)
    row = collection_list_row(result, None)
    assert row["status"] == "processing"
    assert row["score"] is None
    assert row["ai_status"] is None
    assert row["ticket_id"] is None


# --------------------------------------------------------------------------
# Jalur BACA: maksimum yang tersimpan tidak boleh hilang saat dinormalisasi ulang
# --------------------------------------------------------------------------

def _laporan_terpotong():
    """Balasan terpotong: hanya 1 item (bobot 10) yang dijawab dari scorecard 150.
    Saat ditulis worker, maksimumnya 150 dan hasilnya FAIL (10 < 135)."""
    return normalize_weighted_report(
        {"scorecard_result": [_item("A1", 10, "SESUAI")]}, configured_maximum=150)


def test_normalize_stored_report_memakai_maximum_score_tersimpan():
    stored = _laporan_terpotong()
    assert stored["maximum_score"] == 150 and stored["ai_status"] == "FAIL"

    again = normalize_stored_report(stored)
    assert again["maximum_score"] == 150
    assert again["passing_grade"] == 135
    # Tanpa maksimum tersimpan, penyebutnya menyusut ke 10 dan FAIL berubah PASS.
    assert again["ai_status"] == "FAIL"


def test_normalize_stored_report_maximum_tidak_valid_jatuh_ke_jumlah_item():
    for bad in (None, 0, -5, "150", True, float("nan")):
        ev = {"maximum_score": bad, "scorecard_result": [_item("A1", 10, "SESUAI")]}
        r = normalize_stored_report(ev)
        assert r["maximum_score"] == 10, bad
        assert r["ai_status"] == "PASS", bad


def test_normalize_stored_report_input_bukan_dict():
    assert normalize_stored_report(None)["maximum_score"] == 0


def test_list_row_memakai_maximum_score_tersimpan():
    rj = {"report_type": REPORT_TYPE, "evaluation": _laporan_terpotong()}
    row = collection_list_row(SimpleNamespace(
        id="r1", campaign="Collection", source_files=["T1_a.pdf"], status="done",
        uploaded_at=None, completed_at=None), rj)
    assert row["maximum_score"] == 150
    assert row["ai_status"] == "FAIL"


# --------------------------------------------------------------------------
# Bobot & item_score dari model tidak dipercaya
# --------------------------------------------------------------------------

def test_item_score_dijepit_ke_rentang_nol_sampai_bobot():
    r = normalize_weighted_report({"scorecard_result": [
        _item("A1", 5, "SESUAI", item_score=50),
        _item("A2", 5, "BELUM_SESUAI", item_score=-3),
        _item("A3", 5, "SESUAI", item_score=2.5),
    ]})
    assert [i["item_score"] for i in r["scorecard_result"]] == [5, 0, 2.5]
    assert r["ai_score_phase_2"] == 7.5


def test_apply_configured_weights_menimpa_bobot_model_per_item_code():
    raw = {"call_id": "x", "scorecard_result": [
        _item("A1", 99, "SESUAI"), _item("A2", 1, "SESUAI"), _item("ZZ", 7, "SESUAI"),
        "bukan dict",
    ]}
    config = '[{"item_code": "A1", "weight": 4}, {"item_code": "A2", "weight": 6}, {"item_code": "B1", "weight": 3}]'
    out = apply_configured_weights(raw, config)
    weights = [i["weight"] for i in out["scorecard_result"] if isinstance(i, dict)]
    # ZZ tidak ada di konfigurasi -> bobot model dipertahankan.
    assert weights == [4, 6, 7]
    assert out["call_id"] == "x"
    # Masukan tidak diubah di tempat.
    assert raw["scorecard_result"][0]["weight"] == 99

    report = normalize_weighted_report(out, configured_maximum=13)
    assert report["ai_score_phase_2"] == 17  # 4 + 6 + 7


def test_apply_configured_weights_konfigurasi_tidak_terbaca_tidak_mengubah_apa_pun():
    raw = {"scorecard_result": [_item("A1", 9, "SESUAI")]}
    for bad in (None, "", "bukan json", '{"a": 1}', '[{"item_code": "A1", "weight": "4"}]'):
        assert apply_configured_weights(raw, bad)["scorecard_result"][0]["weight"] == 9, bad
    assert apply_configured_weights(None, '[{"item_code": "A1", "weight": 4}]') is None


# --- Scorecard berkasus v01 (standard_penagihan 30 + etika_penagihan 120) ---------

from pathlib import Path

_V01 = (Path(__file__).resolve().parent.parent
        / "campaigns" / "collection_v01" / "scorecrad_collections_v01.txt").read_text()

# Verdict model untuk tiket 8ae14916 (7 Okt 2026): pihak ketiga, SC_COL_2_2 bocor.
_TIKET_8AE = {
    "SC_COL_1_1": "SESUAI", "SC_COL_1_2": "SESUAI", "SC_COL_1_3": "BELUM_SESUAI",
    "SC_COL_1_4": "TIDAK_DINILAI", "SC_COL_1_5": "TIDAK_DINILAI", "SC_COL_2_1": "BELUM_SESUAI",
    "SC_COL_3_1": "TIDAK_DINILAI", "SC_COL_3_2": "TIDAK_DINILAI", "SC_COL_3_3": "TIDAK_DINILAI",
    "SC_COL_3_4": "TIDAK_DINILAI", "SC_COL_7_2": "TIDAK_DINILAI", "SC_COL_8_1": "TIDAK_DINILAI",
    "SC_COL_2_2": "BELUM_SESUAI", "SC_COL_2_3": "TIDAK_DINILAI", "SC_COL_4_1": "SESUAI",
    "SC_COL_4_2": "SESUAI", "SC_COL_4_3": "SESUAI", "SC_COL_4_4": "SESUAI",
    "SC_COL_4_5": "SESUAI", "SC_COL_4_6": "SESUAI",
}


def _v01_report(verdicts, **overrides):
    # Model tidak mengirim bobot/kasus yang benar — konfigurasi yang menentukan.
    raw = {"scorecard_result": [{"item_code": c, "weight": 99, "status": s, "tolerable": "NO"
                                 if c in ("SC_COL_1_4", "SC_COL_2_1", "SC_COL_3_3") else "YES"}
                                for c, s in verdicts.items()],
           "case_summary": [{"case": "etika_penagihan", "case_points": 120}], **overrides}
    raw = apply_configured_weights(raw, _V01)
    return normalize_weighted_report(raw, configured_maximum=scorecard_maximum(_V01))


def _semua(status):
    return {c: status for c in _TIKET_8AE}


def test_v01_scorecard_maximum_dan_kasus_dari_konfigurasi():
    assert scorecard_maximum(_V01) == 150
    raw = apply_configured_weights({"scorecard_result": [{"item_code": "SC_COL_4_1"},
                                                         {"item_code": "SC_COL_1_5"}]}, _V01)
    assert raw["scorecard_result"] == [
        {"item_code": "SC_COL_4_1", "weight": 20, "case": "etika_penagihan", "optional": False},
        {"item_code": "SC_COL_1_5", "weight": 1, "case": "standard_penagihan", "optional": True},
    ]


def test_v01_semua_sesuai_lulus_dengan_bonus_penuh():
    r = _v01_report(_semua("SESUAI"))
    assert r["maximum_score"] == 150
    assert r["base_maximum_score"] == 122
    assert r["passing_grade"] == 109.8
    assert r["ai_score_phase_2"] == 150
    assert r["ai_status"] == "PASS"
    assert [(c["case"], c["max_points"], c["mandatory_weight"], c["case_points"], c["case_result"])
            for c in r["case_summary"]] == [
        ("standard_penagihan", 30, 11, 30, "PASS"),
        ("etika_penagihan", 120, 111, 120, "PASS"),
    ]


def test_v01_item_opsional_tidak_dinilai_tidak_mengurangi_skor():
    verdicts = _semua("SESUAI")
    for c in ("SC_COL_1_4", "SC_COL_1_5", "SC_COL_3_1", "SC_COL_3_2", "SC_COL_3_3",
              "SC_COL_3_4", "SC_COL_7_2", "SC_COL_8_1", "SC_COL_2_3"):
        verdicts[c] = "TIDAK_DINILAI"
    r = _v01_report(verdicts)
    assert r["ai_score_phase_2"] == 122
    assert r["ai_status"] == "PASS"
    standard, etika = r["case_summary"]
    assert (standard["mandatory_earned"], standard["optional_earned"], standard["case_points"]) == (11, 0, 11)
    assert etika["case_points"] == 111


def test_v01_gerbang_etika_menolkan_skor_akhir_tiket_8ae14916():
    r = _v01_report(_TIKET_8AE)
    standard, etika = r["case_summary"]
    assert (standard["case_points"], standard["max_points"], standard["case_result"]) == (2, 30, "FAIL")
    assert (etika["case_points"], etika["max_points"], etika["case_result"]) == (97, 120, "FAIL")
    assert r["ai_score_phase_2"] == 0
    assert r["ai_status"] == "FAIL"


def test_v01_opsional_salah_sebut_tidak_menggagalkan_standard_tapi_tanpa_bonus():
    verdicts = _semua("SESUAI")
    verdicts["SC_COL_3_3"] = "BELUM_SESUAI"   # opsional, non-tolerable
    standard = _v01_report(verdicts)["case_summary"][0]
    assert standard["case_result"] == "PASS"
    assert standard["optional_earned"] == 15


def test_v01_dibaca_ulang_tetap_sama():
    r = _v01_report(_TIKET_8AE)
    again = normalize_stored_report(r)
    assert again["case_summary"] == r["case_summary"]
    assert (again["ai_score_phase_2"], again["passing_grade"]) == (0, 109.8)


def test_v01_list_row_memuat_kolom_standard_dan_etika():
    result = SimpleNamespace(id="r1", campaign="Collection", source_files=["T1_a.pdf"],
                             status="done", uploaded_at=None, completed_at=None)
    row = collection_list_row(result, build_collection_result_json(
        result_id="r1", campaign="Collection", source_files=["T1_a.pdf"],
        report=_v01_report(_TIKET_8AE), processed_at="x", processing_sec=1))
    assert (row["standard_score"], row["standard_maximum"], row["standard_status"]) == (2, 30, "FAIL")
    assert (row["etika_score"], row["etika_maximum"], row["etika_status"]) == (97, 120, "FAIL")
    assert row["score"] == 0


def test_laporan_datar_lama_tanpa_kolom_kasus():
    r = normalize_weighted_report({"scorecard_result": [_item("A", 10, "SESUAI")]})
    assert r["case_summary"] == [] and r["base_maximum_score"] is None
    assert "case" not in r["scorecard_result"][0]
