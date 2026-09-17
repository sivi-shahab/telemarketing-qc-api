# Collection Weighted Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hasil campaign Collection dinilai dengan scorecard berbobot POJK 22/2023 (format `WeightedAuditReport` dari `/data/qc-collection`) dan ditampilkan di halaman terpisah `CollectionView.vue` pada telemarketing-qc-dashboard — tanpa menyentuh data TMS maupun Ascend.

**Architecture:** Worker mendeteksi campaign Collection lewat `COLLECTION_CAMPAIGNS` dan menjalankan jalur pendek: unduh PDF → rangkai transkrip → satu panggilan LLM dengan prompt/scorecard/KB berbobot → normalisasi (port `weightedReport.ts` ke `compliance/collection_report.py`) → simpan ke `result_data` bertanda `report_type: "collection_weighted"`. API menambah router `/collection/results` (daftar + detail) yang hanya membaca tabel `results`/`result_data`, dan mengecualikan campaign Collection dari `/list_results`. Dashboard menambah menu Collection: halaman daftar dengan kerangka tabel yang sama dengan menu lain, halaman detail yang memetakan seksi `WeightedAuditView.tsx` ke komponen Vue, dan panel PDF baru (toolbar, zoom, tab per berkas, layar penuh).

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Celery (api, worker, core vendored), Vue 3 + vue-router + pdfjs-dist 4 (dashboard), pytest, `node --test`.

**Spec:** Rancangan disepakati di percakapan 17 September 2026 (tidak ada berkas spec terpisah). Ringkasnya:
- Hanya mode **berbobot** (`WeightedAuditReport`); mode standar 7 indikator tidak dipakai.
- Worker: jalur Collection **tidak** memanggil `tms_cashline`, DWH/Ascend (`build_reference_data`), riplay, klasifikasi rekaman, pemilik panggilan, MUS, maupun `resync_scores`.
- API: endpoint terpisah, tanpa join TMS/Ascend, tanpa dokumen/SLA/banding/manual check.
- Dashboard: page terpisah, format dashboard (SidebarLayout, filter-bar, table-card, TablePager, token `mega.css`) dipertahankan; isi detail mengikuti `WeightedAuditView.tsx`; tampilan PDF dibuat lebih bagus.

## Global Constraints

- Repo monolit `telemarketing-qc-system` **tidak boleh diubah**. Semua kerja di `telemarketing-qc-api`, `-worker`, `-dashboard`, `-core`.
- Kode core di-vendor: setiap berkas baru/berubah di `core/compliance/` harus identik di `telemarketing-qc-api/core/compliance/`, `telemarketing-qc-worker/core/compliance/`, dan `telemarketing-qc-core/src/qc_core/compliance/` (impor datar `from compliance...` di api/worker, `from qc_core.compliance...` di core). Cek dengan `diff <(sed 's/qc_core\.//g' ../telemarketing-qc-core/src/qc_core/compliance/X) core/compliance/X`.
- Tidak ada verdict yang dikarang: nilai yang tidak terbaca → `TIDAK_TERSEDIA` / `TIDAK_DINILAI` / `SKIPPED_NULL`, **bukan** PASS/FAIL tebakan.
- `PASSING_GRADE_RATIO = 0.9`; skor dihitung ulang dari `scorecard_result`, tidak dibaca dari model.
- `COLLECTION_CAMPAIGNS` kosong = fitur mati total; perilaku Cashline tidak berubah sama sekali.
- Penanda hasil: `result_json["report_type"] == "collection_weighted"`.
- Capability baru: `menu.collection_results` (`MENU_COLLECTION_RESULTS`), ditulis di `api/permissions.py` **dan** `dashboard/src/permissions.js`.
- Berkas router dashboard `src/router/index.js` ada di `.gitignore` — perubahan route harus dicatat dan disalin manual ke tiap environment.
- Teks UI dan komentar kode berbahasa Indonesia, mengikuti gaya repo.
- Commit per task, pesan diakhiri `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Kerja di branch `feat/collection-weighted-results` di tiap repo (jangan langsung di `main`).

**Menjalankan test API** (pytest tidak ada di image produksi; mount kode yang sedang diubah):

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm \
  -v "$PWD/tests:/app/tests:ro" \
  -v "$PWD/core/compliance:/app/compliance:ro" \
  -v "$PWD/core/db:/app/db:ro" \
  -v "$PWD/api:/app/api:ro" \
  --env-file .env --entrypoint sh local/qc-api:latest -c \
  'pip install -q pytest && python -m pytest -q tests/<berkas>.py'
```

Selanjutnya disebut **`RUN_API_TESTS tests/<berkas>.py`**.

---

## File Structure

| Repo | Berkas | Tanggung jawab |
|---|---|---|
| core (×3 salinan) | `compliance/collection_report.py` (baru) | Normalisasi laporan berbobot, hitung skor, rakit `result_json`, ringkas baris daftar |
| api | `tests/test_collection_report.py` (baru) | Test unit modul di atas |
| worker | `worker/tasks/process_transcript.py` (ubah) | Cabang Collection di awal pipeline |
| api | `api/permissions.py`, `tests/test_rbac_collection_permissions.py` (ubah) | Capability `MENU_COLLECTION_RESULTS` |
| api | `core/db/crud.py` (+ salinan worker & core) (ubah) | `exclude_campaigns` di `list_results`, `list_collection_results` |
| api | `api/routers/stats.py` (ubah) | Collection dikecualikan dari menu Results |
| api | `api/routers/collection.py` (baru), `api/main.py` (ubah), `tests/test_collection_router.py` (baru) | Endpoint daftar + detail |
| api | `campaigns/collection_weighted/` (baru) | Prompt/scorecard/KB berbobot yang diunggah via Upload Campaign |
| dashboard | `src/permissions.js`, `src/router/index.js`, `src/components/SidebarMenu.vue` (ubah) | Menu + route + guard |
| dashboard | `src/utils/collectionReport.js`, `src/utils/collectionReport.test.mjs` (baru), `package.json` (ubah) | Helper murni tampilan + test |
| dashboard | `src/views/dashboard/CollectionView.vue` (baru) | Halaman daftar |
| dashboard | `src/utils/pdfRender.js` (ubah), `src/components/collection/CollectionPdfPanel.vue` (baru) | Panel PDF yang lebih bagus |
| dashboard | `src/components/collection/*.vue` (baru), `src/views/dashboard/CollectionDetailView.vue` (baru) | Seksi laporan berbobot + halaman detail |

---

### Task 1: Normalisasi laporan berbobot di core

**Files:**
- Create: `telemarketing-qc-api/core/compliance/collection_report.py`
- Test: `telemarketing-qc-api/tests/test_collection_report.py`
- Sync: `telemarketing-qc-worker/core/compliance/collection_report.py`, `telemarketing-qc-core/src/qc_core/compliance/collection_report.py`

**Interfaces:**
- Produces:
  - `REPORT_TYPE: str = "collection_weighted"`
  - `PASSING_GRADE_RATIO: float = 0.9`
  - `scorecard_maximum(scorecard_text: str) -> float | None`
  - `normalize_weighted_report(value, configured_maximum: float | None = None) -> dict` — dict berbentuk `WeightedAuditReport` (`qc-collection/src/types/qc.ts`)

- [ ] **Step 1: Tulis test yang gagal**

```python
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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `RUN_API_TESTS tests/test_collection_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compliance.collection_report'`

- [ ] **Step 3: Tulis implementasi**

```python
"""Laporan audit BERBOBOT campaign Collection (POJK 22/2023).

Port Python dari ``qc-collection/src/server/weightedReport.ts``. Keluaran LLM
hanya dijamin JSON yang bisa di-parse, tidak pernah berbentuk tertentu — modul ini
memaksanya menjadi ``WeightedAuditReport`` yang aman dirender dashboard.

Dua aturan:
  1. Setiap field yang dibaca dashboard ada sesudahnya, dengan tipe yang benar.
  2. Tidak ada verdict yang dikarang. Bila model tidak memberi PASS/FAIL — atau
     memberinya dalam bentuk yang polaritasnya harus ditebak — hasilnya
     ``TIDAK_TERSEDIA``. Menyatakan panggilan penagihan compliant tanpa bukti lebih
     berbahaya daripada menampilkan celah.

Jalur Collection sengaja TIDAK memakai TMS maupun Ascend: tidak ada nilai acuan,
sehingga ``collection_data_verification`` hanya bisa berisi nilai yang disebut
dalam panggilan.
"""
import json
import math

REPORT_TYPE = "collection_weighted"

# Ambang lulus adalah kebijakan, bukan angka yang boleh berubah tiap panggilan
# model (pernah keluar 87 dari 150 dan 120.6 dari 134 untuk prompt yang sama).
PASSING_GRADE_RATIO = 0.9

UNAVAILABLE = "TIDAK_TERSEDIA"
_PASS_FAIL = {"PASS", "FAIL"}
_COMMITMENT = {"COMMITTED_TO_PAY", "PARTIAL_COMMITMENT", "DISPUTE", "REFUSED", "NOT_STATED"}
_MATCH = {"MATCH", "MISMATCH", "SKIPPED_NULL"}
_SCORECARD = {"SESUAI", "BELUM_SESUAI", "TIDAK_DINILAI"}


def _num(value):
    """Angka hingga (bool bukan angka), selain itu None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _str(value, fallback=""):
    return value if isinstance(value, str) else fallback


def _scalar(value):
    if isinstance(value, bool):
        return "YA" if value else "TIDAK"
    if _num(value) is not None or isinstance(value, str):
        return value
    return None


def _round1(n):
    return round(n * 10) / 10


def _evidence(value):
    # String di sini adalah uraian, bukan kutipan transkrip — tidak boleh sampai ke
    # ``quote``, yang dirender miring dalam tanda kutip seolah diucapkan nasabah.
    if not isinstance(value, dict):
        return {"timestamp": None, "quote": None}
    return {
        "timestamp": value["timestamp"] if isinstance(value.get("timestamp"), str) else None,
        "quote": value["quote"] if isinstance(value.get("quote"), str) else None,
    }


def _commitment(value):
    if not isinstance(value, dict):
        return {"status": "NOT_STATED", "reason": "", "evidence": _evidence(None)}
    declared = _str(value.get("status")).upper()
    if declared in _COMMITMENT:
        status = declared
    elif value.get("ada_kesepakatan") is True:
        status = "COMMITTED_TO_PAY"
    else:
        status = "NOT_STATED"
    reason = value.get("reason") if value.get("reason") is not None else value.get("ringkasan")
    return {"status": status, "reason": _str(reason), "evidence": _evidence(value.get("evidence"))}


def _critical(value):
    unavailable = {"status": UNAVAILABLE, "checked_items": []}
    if not isinstance(value, dict):
        return unavailable
    declared = _str(value.get("status")).upper()
    items = []
    for it in value.get("checked_items") if isinstance(value.get("checked_items"), list) else []:
        if not isinstance(it, dict):
            continue
        st = _str(it.get("status")).upper()
        items.append({
            "item_code": _str(it.get("item_code"), "-"),
            "requirement": _str(it.get("requirement")),
            "status": st if st in _PASS_FAIL else UNAVAILABLE,
        })
    # Bentuk datar {kunci: bool} sengaja TIDAK diterjemahkan: polaritas kuncinya
    # campur (false = syarat terlewat di satu kunci, pelanggaran terhindar di kunci
    # lain). Menebak berarti bisa mencetak PASS di atas kebocoran data sungguhan.
    if declared not in _PASS_FAIL and not items:
        return unavailable
    return {"status": declared if declared in _PASS_FAIL else UNAVAILABLE, "checked_items": items}


def _verification_row(field, source, extracted):
    match = _str(source.get("match")).upper()
    return {
        "field": field,
        "reference_value": _scalar(source.get("reference_value")),
        "extracted_value": _scalar(extracted),
        "match": match if match in _MATCH else UNAVAILABLE,
        "similarity_percent": _num(source.get("similarity_percent")),
        "reason": _str(source.get("reason")),
        "item_score": _num(source.get("item_score")),
    }


def _verification(value):
    if isinstance(value, list):
        return [_verification_row(_str(r.get("field"), "-"), r, r.get("extracted_value"))
                for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        # Bentuk datar: hanya nilai yang disebut agent, tanpa acuan -> tanpa verdict.
        return [_verification_row(k, {}, v) for k, v in value.items()]
    return []


def _categories(value):
    if not isinstance(value, list):
        return []
    out = []
    for c in value:
        if not isinstance(c, dict):
            continue
        res = _str(c.get("category_result")).upper()
        total = c.get("total_weight") if c.get("total_weight") is not None else c.get("maximum_score")
        earned = c.get("earned_score") if c.get("earned_score") is not None else c.get("score")
        out.append({
            "category": _str(c.get("category"), "-"),
            "total_weight": _num(total) or 0,
            "earned_score": _num(earned) or 0,
            "category_result": res if res in _PASS_FAIL else UNAVAILABLE,
            "fail_reason": c["fail_reason"] if isinstance(c.get("fail_reason"), str) else None,
        })
    return out


def _scorecard_status(raw):
    s = _str(raw).upper()
    if s in _SCORECARD:
        return s
    if s in ("PASS", "YA"):
        return "SESUAI"
    if s in ("FAIL", "TIDAK"):
        return "BELUM_SESUAI"
    return "TIDAK_DINILAI"


def _scorecard(value):
    if not isinstance(value, list):
        return []
    out = []
    for it in value:
        if not isinstance(it, dict):
            continue
        status = _scorecard_status(it.get("status"))
        weight = _num(it.get("weight")) or 0
        declared = _num(it.get("item_score"))
        if declared is not None:
            score = declared
        elif status == "SESUAI":
            score = weight
        elif status == "BELUM_SESUAI":
            score = 0
        else:
            score = None
        prose = it["evidence"] if isinstance(it.get("evidence"), str) else ""
        out.append({
            "category": _str(it.get("category"), "-"),
            "item_code": _str(it.get("item_code"), "-"),
            "requirement": _str(it.get("requirement")),
            "kb_reference": _str(it.get("kb_reference")),
            "tolerable": _str(it.get("tolerable"), "YES"),
            "weight": weight,
            "status": status,
            "item_score": score,
            "reason": _str(it.get("reason")) or prose,
            "evidence": _evidence(it.get("evidence")),
        })
    return out


def _error_codes(value):
    if not isinstance(value, list):
        return []
    out = []
    for e in value:
        if isinstance(e, str):
            if e.strip():
                out.append({"error_code": e.strip(), "details_error": "",
                            "trigger_source": {"reason": "", "evidence": _evidence(None)}})
            continue
        if not isinstance(e, dict):
            continue
        src = e.get("trigger_source") if isinstance(e.get("trigger_source"), dict) else {}
        out.append({
            "error_code": _str(e.get("error_code"), "-"),
            "details_error": _str(e.get("details_error")),
            "trigger_source": {"reason": _str(src.get("reason")),
                               "evidence": _evidence(src.get("evidence"))},
        })
    return out


def scorecard_maximum(scorecard_text):
    """Jumlah kolom ``weight`` scorecard campaign (JSON array), atau None."""
    try:
        parsed = json.loads(scorecard_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    total = sum(_num(i.get("weight")) or 0 for i in parsed if isinstance(i, dict))
    return total if total > 0 else None


def normalize_weighted_report(value, configured_maximum=None):
    """Satu gerbang untuk setiap laporan berbobot — saat keluar dari model DAN saat
    dibaca ulang dari ``result_data``, sehingga catatan lama ikut tersembuhkan."""
    raw = value if isinstance(value, dict) else {}
    scorecard = _scorecard(raw.get("scorecard_result"))

    # Skor adalah aritmetika atas scorecard, bukan bacaan dari model: pernah keluar
    # 116/116 PASS padahal 26 item-nya sendiri berjumlah 89 dari 150.
    items_max = sum(i["weight"] for i in scorecard)
    maximum = configured_maximum if configured_maximum and configured_maximum > 0 else items_max
    earned = _round1(sum(i["item_score"] or 0 for i in scorecard))
    passing = _round1(maximum * PASSING_GRADE_RATIO)

    report = {
        "call_id": _str(raw.get("call_id"), "-"),
        "consumer_full_name": raw["consumer_full_name"] if isinstance(raw.get("consumer_full_name"), str) else None,
        "agent_name": raw["agent_name"] if isinstance(raw.get("agent_name"), str) else None,
        "product_type": raw["product_type"] if isinstance(raw.get("product_type"), str) else None,
        "agunan_discussion_status": "INITIATED" if raw.get("agunan_discussion_status") == "INITIATED" else "NOT_INITIATED",
        "commitment_status": _commitment(raw.get("commitment_status")),
        "maximum_score": maximum,
        "passing_grade": passing,
        "ai_score_phase_2": earned,
        # Laporan tanpa apa pun untuk dinilai bukan kelulusan.
        "ai_status": "PASS" if maximum > 0 and earned >= passing else "FAIL",
        "scorecard_result": scorecard,
        "category_summary": _categories(raw.get("category_summary")),
        "critical_compliance_check": _critical(raw.get("critical_compliance_check")),
        "collection_data_verification": _verification(raw.get("collection_data_verification")),
        "error_codes": _error_codes(raw.get("error_codes")),
        "ai_summary": _str(raw.get("ai_summary")),
    }
    for key in ("audio_filename", "generated_at", "banner_warning"):
        if isinstance(raw.get(key), str):
            report[key] = raw[key]
    return report
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `RUN_API_TESTS tests/test_collection_report.py`
Expected: PASS (11 passed)

- [ ] **Step 5: Salin ke worker dan core, verifikasi identik**

```bash
cd /data/scorecard_v2
cp telemarketing-qc-api/core/compliance/collection_report.py telemarketing-qc-worker/core/compliance/
cp telemarketing-qc-api/core/compliance/collection_report.py telemarketing-qc-core/src/qc_core/compliance/
diff <(sed 's/qc_core\.//g' telemarketing-qc-core/src/qc_core/compliance/collection_report.py) telemarketing-qc-api/core/compliance/collection_report.py && echo IDENTIK
```
Expected: `IDENTIK` (modul ini tidak mengimpor apa pun dari paket, jadi tidak ada prefix yang perlu disesuaikan).

- [ ] **Step 6: Commit di ketiga repo**

```bash
git -C telemarketing-qc-api add core/compliance/collection_report.py tests/test_collection_report.py
git -C telemarketing-qc-api commit -m "feat(collection): normalisasi laporan audit berbobot POJK 22"
git -C telemarketing-qc-worker add core/compliance/collection_report.py
git -C telemarketing-qc-worker commit -m "feat(collection): sinkron compliance/collection_report.py dari api"
git -C telemarketing-qc-core add src/qc_core/compliance/collection_report.py
git -C telemarketing-qc-core commit -m "feat(collection): sinkron compliance/collection_report.py dari api"
```

---

### Task 2: Rakit `result_json` dan ringkasan baris daftar

**Files:**
- Modify: `telemarketing-qc-api/core/compliance/collection_report.py` (tambah di akhir berkas)
- Test: `telemarketing-qc-api/tests/test_collection_report.py` (tambah)
- Sync: salinan worker & core seperti Task 1 Step 5

**Interfaces:**
- Consumes: `normalize_weighted_report`, `REPORT_TYPE` (Task 1)
- Produces:
  - `build_collection_result_json(*, result_id: str, campaign: str, source_files: list[str], report: dict, processed_at: str, processing_sec: float, audio_duration=None) -> dict`
  - `is_collection_result_json(result_json) -> bool`
  - `collection_list_row(result, result_json: dict | None) -> dict` dengan key: `result_id, campaign, ticket_id, source_files, status, uploaded_at, completed_at, agent_name, consumer_full_name, product_type, score, maximum_score, passing_grade, ai_status, critical_status, commitment_status, error_code_count`

- [ ] **Step 1: Tulis test yang gagal**

```python
from datetime import datetime
from types import SimpleNamespace

from compliance.collection_report import (
    REPORT_TYPE,
    build_collection_result_json,
    collection_list_row,
    is_collection_result_json,
)


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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `RUN_API_TESTS tests/test_collection_report.py`
Expected: FAIL — `ImportError: cannot import name 'build_collection_result_json'`

- [ ] **Step 3: Tulis implementasi (tambahkan di akhir `collection_report.py`)**

```python
def build_collection_result_json(*, result_id, campaign, source_files, report,
                                 processed_at, processing_sec, audio_duration=None):
    """``result_json`` tiket Collection. Sengaja TANPA ``reference_data``,
    ``assigned_agent``, ``recording_types`` dsb.: semua itu turunan TMS/Ascend dan
    jalur ini tidak menyentuhnya. ``report_type`` membuat pembaca tidak pernah
    salah mengira isinya format Cashline."""
    return {
        "report_type": REPORT_TYPE,
        "result_id": str(result_id),
        "campaign": campaign,
        "source_files": list(source_files),
        "num_calls": len(source_files),
        "audio_duration": audio_duration,
        "processed_at": processed_at,
        "processing_sec": round(processing_sec, 2),
        "evaluation": report,
    }


def is_collection_result_json(result_json) -> bool:
    return isinstance(result_json, dict) and result_json.get("report_type") == REPORT_TYPE


def _ticket_id(source_files):
    first = (source_files or [None])[0]
    return first.split("_", 1)[0] if isinstance(first, str) and first else None


def collection_list_row(result, result_json):
    """Satu baris tabel menu Collection. Laporan dibaca ULANG lewat normalizer
    supaya baris lama yang tersimpan sebelum aturan berubah ikut konsisten."""
    report = (normalize_weighted_report(result_json.get("evaluation"))
              if is_collection_result_json(result_json) else None)
    iso = lambda dt: dt.isoformat() if dt is not None else None  # noqa: E731
    return {
        "result_id": str(result.id),
        "campaign": result.campaign,
        "ticket_id": _ticket_id(result.source_files),
        "source_files": list(result.source_files or []),
        "status": result.status,
        "uploaded_at": iso(result.uploaded_at),
        "completed_at": iso(result.completed_at),
        "agent_name": report["agent_name"] if report else None,
        "consumer_full_name": report["consumer_full_name"] if report else None,
        "product_type": report["product_type"] if report else None,
        "score": report["ai_score_phase_2"] if report else None,
        "maximum_score": report["maximum_score"] if report else None,
        "passing_grade": report["passing_grade"] if report else None,
        "ai_status": report["ai_status"] if report else None,
        "critical_status": report["critical_compliance_check"]["status"] if report else None,
        "commitment_status": report["commitment_status"]["status"] if report else None,
        "error_code_count": len(report["error_codes"]) if report else 0,
    }
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `RUN_API_TESTS tests/test_collection_report.py`
Expected: PASS (14 passed)

- [ ] **Step 5: Sinkron ke worker & core** — ulangi perintah `cp` + `diff` Task 1 Step 5. Expected: `IDENTIK`.

- [ ] **Step 6: Commit di ketiga repo**

```bash
git -C telemarketing-qc-api add core/compliance/collection_report.py tests/test_collection_report.py
git -C telemarketing-qc-api commit -m "feat(collection): result_json bertanda report_type dan ringkasan baris daftar"
git -C telemarketing-qc-worker add core/compliance/collection_report.py
git -C telemarketing-qc-worker commit -m "feat(collection): sinkron collection_report (result_json + baris daftar)"
git -C telemarketing-qc-core add src/qc_core/compliance/collection_report.py
git -C telemarketing-qc-core commit -m "feat(collection): sinkron collection_report (result_json + baris daftar)"
```

---

### Task 3: Worker — jalur Collection tanpa TMS/Ascend

**Files:**
- Modify: `telemarketing-qc-worker/worker/tasks/process_transcript.py` (impor di atas; cabang tepat sesudah `tahap.catat("unduh_pdf")` + guard `if not pdf_paths`; fungsi baru `_process_collection` di atas `process_transcript`)
- Modify: `telemarketing-qc-worker/docker-compose.yml` (teruskan env `COLLECTION_CAMPAIGNS`)

**Interfaces:**
- Consumes: `build_collection_result_json`, `normalize_weighted_report`, `scorecard_maximum` (Task 1–2); `compliance.campaign_kind.is_collection`, `parse_collection_campaigns`; `build_transcript`, `call_duration`, `latest_generated_timestamp` dari `compliance.pdf_parser`; `evaluate`.
- Produces: baris `result_data` dengan `result_json.report_type == "collection_weighted"`; objek MinIO `results/{result_id}.json`.

Worker tidak punya suite test sendiri; logika murni sudah diuji di Task 1–2. Task ini diverifikasi dengan import-check dan e2e di Task 11.

- [ ] **Step 1: Periksa tanda tangan `build_transcript` dan `call_duration`**

Run: `grep -n "^def build_transcript\|^def call_duration\|^def latest_generated_timestamp" -A12 telemarketing-qc-worker/core/compliance/pdf_parser.py`
Expected: `build_transcript(pdf_paths)` mengembalikan 4 nilai `(sorted_filenames, messages, audio_duration, audio_durations)` — dipakai persis begitu di `_nilai_satu` (`f_names, f_msgs, _d, _ds = build_transcript([path])`). Bila urutannya berbeda, sesuaikan unpacking di Step 3.

- [ ] **Step 2: Tambah impor**

Di blok impor `process_transcript.py`, sesudah `from compliance.call_ownership import (...)`:

```python
from compliance.campaign_kind import is_collection, parse_collection_campaigns
from compliance.collection_report import (
    build_collection_result_json,
    normalize_weighted_report,
    scorecard_maximum,
)
```

- [ ] **Step 3: Tambah `_process_collection` di atas `def process_transcript`**

```python
def _collection_campaigns() -> frozenset:
    # Dibaca tiap tiket, tidak di-cache — sama dengan api.rbac.collection_campaigns_from_env.
    return parse_collection_campaigns(os.getenv("COLLECTION_CAMPAIGNS", ""))


def _process_collection(db, result, result_id, pdf_paths, settings, tahap, started_at):
    """Jalur campaign Collection: audit BERBOBOT POJK 22/2023.

    Sengaja PENDEK. Seluruh langkah Cashline yang bergantung pada TMS atau Ascend —
    pemilik panggilan (tms_cashline.agent_id), jangkar submit_time, reference data
    DWH/Ascend, riplay, klasifikasi rekaman, MUS, resync_scores — dilewati: tiket
    penagihan tidak punya baris di sana, dan membacanya hanya menghasilkan acuan
    kosong yang tampak seperti data.
    """
    sorted_filenames, messages, audio_duration, _durations = build_transcript(pdf_paths)
    tahap.catat("rangkai_transkrip")
    if not messages:
        raise ValueError(
            "Transkrip kosong: tidak ada segmen yang bisa di-parse dari PDF "
            "(format transkrip mungkin tidak dikenali)."
        )

    campaign = crud.get_active_campaign(db, result.campaign)
    if campaign is None:
        raise ValueError(f"Active campaign '{result.campaign}' not found")
    missing = [label for label, text in (("prompt", campaign.prompt_text),
                                         ("scorecard", campaign.scorecard_text),
                                         ("KB", campaign.kb_text))
               if not (text or "").strip()]
    if missing:
        raise ValueError(
            f"Campaign '{result.campaign}' belum punya konfigurasi QC: "
            f"{', '.join(missing)} masih kosong. Upload dulu lewat menu Upload Campaign."
        )
    # Maksimum milik konfigurasi, bukan milik subset item yang dijawab model —
    # balasan terpotong tidak boleh mengecilkan penyebut dan menggelembungkan persen.
    configured_max = scorecard_maximum(campaign.scorecard_text)
    if configured_max is None:
        logger.warning("result %s: scorecard campaign %s bukan JSON array berbobot; "
                       "maksimum diambil dari item jawaban", result_id, result.campaign)
    tahap.catat("campaign_dan_acuan")

    raw, usage = evaluate(
        prompt_text=campaign.prompt_text,
        messages=messages,
        kb_text=campaign.kb_text,
        scorecard_text=campaign.scorecard_text,
        reference_text="",
        llm_client=_llm_client(),
        model=settings.llm_model,
        source_files=sorted_filenames,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
        reasoning_effort=settings.llm_reasoning_effort,
        return_usage=True,
    )
    tahap.catat("penilaian_llm")
    logger.info("token penilaian (collection): masuk=%s (ter-cache=%s) keluar=%s",
                usage.get("input_token"), usage.get("cached_token"), usage.get("output_token"))

    report = normalize_weighted_report(raw, configured_maximum=configured_max)
    tahap.catat("gabung_dan_skor")

    completed_at = _utcnow()
    processing_sec = (completed_at - started_at).total_seconds()
    final_json = build_collection_result_json(
        result_id=result_id, campaign=result.campaign, source_files=sorted_filenames,
        report=report, processed_at=completed_at.isoformat(),
        processing_sec=processing_sec, audio_duration=audio_duration,
    )
    final_json["timings"] = tahap.data

    payload = json.dumps(final_json, ensure_ascii=False).encode("utf-8")
    result_path = f"{result_id}.json"
    _minio_client().put_object(settings.minio_bucket_results, result_path,
                               io.BytesIO(payload), length=len(payload),
                               content_type="application/json")
    crud.save_result_data(db, result_id, final_json)
    tahap.catat("simpan_hasil")

    crud.update_result_status(db, result_id, "done", result_path=result_path,
                              completed_at=completed_at,
                              processing_sec=round(processing_sec, 2),
                              generated_at=latest_generated_timestamp(pdf_paths))
    tahap.catat("tandai_selesai")
    logger.info("waktu per tahap %s (collection): %s", result_id, tahap.ringkas())
    return {"result_id": str(result_id), "status": "done"}
```

- [ ] **Step 4: Sisipkan cabang di `process_transcript`**

Tepat sesudah blok berikut (sebelum komentar `# 2b. Buang panggilan milik agent LAIN`):

```python
        pdf_paths = _download_transcripts(result_id)
        tahap.catat("unduh_pdf")
        if not pdf_paths:
            raise ValueError(f"No transcript PDFs found for result {result_id}")
```

tambahkan:

```python
        # Campaign Collection keluar di sini, SEBELUM langkah pertama yang membaca
        # TMS (2b). Kegagalan di dalamnya jatuh ke except/finally yang sama di bawah,
        # jadi status failed + pembersihan /tmp tetap berlaku.
        if is_collection(result.campaign, _collection_campaigns()):
            return _process_collection(db, result, result_id, pdf_paths,
                                       settings, tahap, started_at)
```

- [ ] **Step 5: Teruskan env di compose worker**

Run: `grep -n "environment:\|env_file" telemarketing-qc-worker/docker-compose.yml`
Bila service worker memakai `env_file: .env`, cukup tambahkan `COLLECTION_CAMPAIGNS=Collection` ke `.env` worker (nilai sama dengan `.env` API). Bila memakai blok `environment:`, tambahkan baris `COLLECTION_CAMPAIGNS: ${COLLECTION_CAMPAIGNS:-}` di service `worker`.

- [ ] **Step 6: Import-check di image worker dengan kode baru**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker run --rm -v "$PWD/core/compliance:/app/compliance:ro" -v "$PWD/worker:/app/worker:ro" \
  --entrypoint sh local/qc-worker:latest -c \
  'cd /app && python -c "import worker.tasks.process_transcript as m; print(m._process_collection.__name__)"'
```
Expected: `_process_collection`

- [ ] **Step 7: Commit**

```bash
git -C telemarketing-qc-worker add worker/tasks/process_transcript.py docker-compose.yml
git -C telemarketing-qc-worker commit -m "feat(worker): jalur audit berbobot campaign Collection tanpa TMS/Ascend"
```

---

### Task 4: API — capability `MENU_COLLECTION_RESULTS`

**Files:**
- Modify: `telemarketing-qc-api/api/permissions.py`
- Test: `telemarketing-qc-api/tests/test_rbac_collection_permissions.py`

**Interfaces:**
- Produces: `MENU_COLLECTION_RESULTS = "menu.collection_results"`; termasuk di `COLLECTION_ADDED_PERMISSIONS` dan `_ADMIN_PERMISSIONS`; berlabel `"Collection Results"` di `PERMISSION_GROUPS` grup `"Menu"`.

- [ ] **Step 1: Tulis test yang gagal (tambahkan di berkas test)**

```python
def test_menu_collection_results_ditambahkan_untuk_login_collection():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS}, ["Collection"], COLLECTION)
    assert P.MENU_COLLECTION_RESULTS in out


def test_menu_collection_results_tidak_bocor_ke_cashline():
    out = rbac.collection_adjusted_permissions({P.MENU_RESULTS}, ["Cashline"], COLLECTION)
    assert P.MENU_COLLECTION_RESULTS not in out


def test_admin_memegang_menu_collection_results():
    assert P.MENU_COLLECTION_RESULTS in P._ADMIN_PERMISSIONS


def test_menu_collection_results_punya_label_manage_role():
    labels = {code for _group, rows in P.PERMISSION_GROUPS for code, _label in rows}
    assert P.MENU_COLLECTION_RESULTS in labels
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `RUN_API_TESTS tests/test_rbac_collection_permissions.py`
Expected: FAIL — `AttributeError: module 'api.permissions' has no attribute 'MENU_COLLECTION_RESULTS'`

- [ ] **Step 3: Implementasi**

1. Sesudah `MENU_ROLE_HIERARCHY = "menu.role_hierarchy"` tambahkan:
```python
MENU_COLLECTION_RESULTS = "menu.collection_results"
```
2. Tambahkan `MENU_COLLECTION_RESULTS` ke daftar semua permission (blok yang memuat `MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,` sekitar baris 161) — pastikan set/list itu memang katalog permission sah (baca 10 baris di atasnya).
3. Ubah `COLLECTION_ADDED_PERMISSIONS`:
```python
COLLECTION_ADDED_PERMISSIONS = frozenset({
    MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT, AUDIO_UPLOAD, TRANSCRIPT_UPLOAD,
    # Menu hasil audit berbobot Collection (17 September 2026) — halaman terpisah
    # dari Results karena format laporannya berbeda dan tidak memakai TMS/Ascend.
    MENU_COLLECTION_RESULTS,
})
```
4. Tambahkan `MENU_COLLECTION_RESULTS` ke `_ADMIN_PERMISSIONS`.
5. Di `PERMISSION_GROUPS` grup `"Menu"`, sesudah `(MENU_RESULTS, "Results"),` tambahkan `(MENU_COLLECTION_RESULTS, "Collection Results"),`.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `RUN_API_TESTS tests/test_rbac_collection_permissions.py`
Expected: PASS (semua test lama + 4 baru)

- [ ] **Step 5: Commit**

```bash
git -C telemarketing-qc-api add api/permissions.py tests/test_rbac_collection_permissions.py
git -C telemarketing-qc-api commit -m "feat(rbac): capability menu.collection_results"
```

---

### Task 5: API — query daftar Collection & pengecualian dari Results

**Files:**
- Modify: `telemarketing-qc-api/core/db/crud.py` (`list_results`, fungsi baru `list_collection_results`)
- Modify: `telemarketing-qc-api/api/routers/stats.py` (`_resolve_filtered_results`, 4 panggilan `crud.list_results`)
- Test: `telemarketing-qc-api/tests/test_collection_router.py` (bagian crud; butuh DB — test otomatis skip bila DB tak terjangkau)
- Sync: `crud.py` ke `telemarketing-qc-worker/core/db/crud.py` dan `telemarketing-qc-core/src/qc_core/db/crud.py` (hanya dua hunk ini; cek `diff` dulu karena crud bisa sudah berbeda)

**Interfaces:**
- Produces:
  - `crud.list_results(..., exclude_campaigns: Optional[Iterable[str]] = None)`
  - `crud.list_collection_results(db, *, campaigns: list[str], status=None, ai_status=None, ticket_id=None, date_start=None, date_end=None, page=1, limit=20) -> tuple[list[tuple[Result, dict | None]], int]`

- [ ] **Step 1: Tulis test yang gagal**

```python
"""Menu Collection: query daftar dan endpoint-nya.

Bagian DB memakai fixture ``db`` (transaksi yang selalu di-rollback, skip bila DB
tidak terjangkau)."""
import uuid
from datetime import datetime

from db import crud
from db.models import Result, ResultData
from compliance.collection_report import REPORT_TYPE


def _seed(db, campaign, status="done", evaluation=None, uploaded_at=None):
    r = Result(id=uuid.uuid4(), campaign=campaign, status=status,
               source_files=[f"{uuid.uuid4().hex[:8]}_call.pdf"],
               uploaded_at=uploaded_at or datetime(2026, 9, 17, 3, 0))
    db.add(r)
    db.flush()
    if evaluation is not None:
        db.add(ResultData(result_id=r.id, result_json={"report_type": REPORT_TYPE, "evaluation": evaluation}))
        db.flush()
    return r


def _passing_eval():
    return {"scorecard_result": [{"weight": 10, "status": "SESUAI", "item_code": "A"}]}


def _failing_eval():
    return {"scorecard_result": [{"weight": 10, "status": "BELUM_SESUAI", "item_code": "A"}]}


def test_list_results_bisa_mengecualikan_campaign(db):
    kol = _seed(db, "ZZTestCollection")
    cash = _seed(db, "ZZTestCashline")
    ids = {str(r.id) for r in crud.list_results(db, limit=1_000_000, exclude_campaigns=["zztestcollection"])[0]}
    assert str(cash.id) in ids
    assert str(kol.id) not in ids


def test_list_collection_results_hanya_campaign_yang_diminta(db):
    kol = _seed(db, "ZZTestCollection", evaluation=_passing_eval())
    _seed(db, "ZZTestCashline")
    rows, total = crud.list_collection_results(db, campaigns=["ZZTestCollection"], limit=100)
    assert total == 1
    assert str(rows[0][0].id) == str(kol.id)
    assert rows[0][1]["report_type"] == REPORT_TYPE


def test_list_collection_results_filter_ai_status(db):
    lulus = _seed(db, "ZZTestCollection", evaluation=_passing_eval())
    _seed(db, "ZZTestCollection", evaluation=_failing_eval())
    rows, total = crud.list_collection_results(db, campaigns=["ZZTestCollection"], ai_status="PASS")
    assert total == 1 and str(rows[0][0].id) == str(lulus.id)


def test_list_collection_results_daftar_campaign_kosong(db):
    assert crud.list_collection_results(db, campaigns=[]) == ([], 0)
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `RUN_API_TESTS tests/test_collection_router.py`
Expected: FAIL — `TypeError: list_results() got an unexpected keyword argument 'exclude_campaigns'` (atau SKIP bila DB tak terjangkau dari container; jalankan dengan `--network` yang sama dengan service API: tambah `--network "$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' telemarketing-qc-api-api-1)"` ke `docker run`).

- [ ] **Step 3: Implementasi di `crud.py`**

Di signature `list_results` tambahkan parameter terakhir `exclude_campaigns=None`, lalu sesudah blok `if campaigns is not None: ...` sisipkan:

```python
    if exclude_campaigns:
        # Campaign Collection punya menu sendiri (format laporan berbobot); tanpa
        # pengecualian ini tiketnya ikut tampil di Results dan dibaca sebagai Cashline.
        q = q.filter(
            (Result.campaign.is_(None))
            | func.lower(Result.campaign).notin_([c.strip().casefold() for c in exclude_campaigns])
        )
```

Tambahkan fungsi baru tepat sesudah `list_results`:

```python
def list_collection_results(
    db: Session,
    *,
    campaigns,
    status: Optional[str] = None,
    ai_status: Optional[str] = None,
    ticket_id: Optional[str] = None,
    date_start=None,
    date_end=None,
    page: int = 1,
    limit: int = 20,
):
    """Hasil campaign Collection beserta ``result_json``-nya — HANYA tabel
    ``results`` + ``result_data``; tidak ada join ke tms_cashline / ascend.

    ``campaigns`` adalah irisan campaign Collection dengan cakupan user; list kosong
    = tidak ada yang boleh dilihat. ``ai_status`` (PASS/FAIL) dihitung dari laporan
    yang dinormalisasi, jadi penyaringnya di Python — volumenya kecil.
    """
    from compliance.collection_report import normalize_weighted_report

    if not campaigns:
        return [], 0
    q = hidden_ticket_filter(db.query(Result, ResultData.result_json).outerjoin(
        ResultData, ResultData.result_id == Result.id))
    q = q.filter(func.lower(Result.campaign).in_([c.strip().casefold() for c in campaigns]))
    if status:
        q = q.filter(Result.status == status)
    if ticket_id:
        q = q.filter(Result.source_files[0].astext.ilike(f"{ticket_id.strip()}%"))
    if date_start is not None:
        q = q.filter(func.date(Result.uploaded_at) >= date_start)
    if date_end is not None:
        q = q.filter(func.date(Result.uploaded_at) <= date_end)
    q = q.order_by(desc(Result.uploaded_at))

    wanted = ai_status.strip().upper() if isinstance(ai_status, str) and ai_status.strip() else None
    if wanted is None:
        total = q.count()
        return [(r, rj) for r, rj in q.offset((page - 1) * limit).limit(limit).all()], total

    matched = [
        (r, rj) for r, rj in q.filter(Result.status == "done").all()
        if isinstance(rj, dict)
        and normalize_weighted_report(rj.get("evaluation"))["ai_status"] == wanted
    ]
    return matched[(page - 1) * limit : page * limit], len(matched)
```

> Bila `list_results` menyaring tanggal dengan konversi WIB (lihat cara `date_start` dipakai di sana), tiru ekspresi yang sama di sini alih-alih `func.date(Result.uploaded_at)` supaya kedua menu sepakat soal batas hari.

- [ ] **Step 4: Kecualikan Collection dari Results di `stats.py`**

Di `_resolve_filtered_results`, sesudah `role_campaigns = effective_campaigns_for(db, current_user)` (baris ~450) tambahkan:

```python
    # Tiket Collection dilayani menu Collection Results (format laporan berbeda).
    from api.rbac import collection_campaigns_from_env
    _exclude = sorted(collection_campaigns_from_env()) or None
```

lalu tambahkan argumen `exclude_campaigns=_exclude` ke **keempat** panggilan `crud.list_results(` di fungsi itu (baris ~548, ~589, ~606, ~614). Verifikasi: `grep -n "crud.list_results(" -A3 api/routers/stats.py | grep -c exclude_campaigns` → `4` untuk fungsi ini (panggilan di sekitar baris 1831 milik ekspor; tambahkan juga di sana dengan cara yang sama agar ekspor XLSX tidak memuat tiket Collection).

- [ ] **Step 5: Jalankan test**

Run: `RUN_API_TESTS tests/test_collection_router.py` (dengan `--network` seperti Step 2)
Expected: PASS (4 passed)

Run juga regresi: `RUN_API_TESTS tests/test_reprocess_filtered.py tests/test_pending_check_queue.py`
Expected: jumlah pass/fail sama dengan sebelum perubahan (catat angka sebelumnya lewat `git stash` bila perlu).

- [ ] **Step 6: Sinkron hunk crud ke worker & core, lalu commit**

```bash
cd /data/scorecard_v2
diff <(sed 's/qc_core\.//g' telemarketing-qc-core/src/qc_core/db/crud.py) telemarketing-qc-api/core/db/crud.py | head -40
diff telemarketing-qc-worker/core/db/crud.py telemarketing-qc-api/core/db/crud.py | head -40
```
Bila satu-satunya selisih adalah dua hunk Task ini, salin berkasnya (`cp`, untuk core ubah `from compliance.` → `from qc_core.compliance.` di impor lokal `list_collection_results`). Bila ada selisih lain, terapkan hunk secara manual.

```bash
git -C telemarketing-qc-api add core/db/crud.py api/routers/stats.py tests/test_collection_router.py
git -C telemarketing-qc-api commit -m "feat(collection): query daftar Collection; Results mengecualikan campaign Collection"
git -C telemarketing-qc-worker add core/db/crud.py && git -C telemarketing-qc-worker commit -m "chore(core): sinkron crud list_collection_results"
git -C telemarketing-qc-core add src/qc_core/db/crud.py && git -C telemarketing-qc-core commit -m "chore(core): sinkron crud list_collection_results"
```

---

### Task 6: API — router `/collection/results`

**Files:**
- Create: `telemarketing-qc-api/api/routers/collection.py`
- Modify: `telemarketing-qc-api/api/main.py` (impor + `app.include_router(collection.router)`)
- Test: `telemarketing-qc-api/tests/test_collection_router.py` (tambah; tanpa DB, fungsi route dipanggil langsung dengan `monkeypatch`)

**Interfaces:**
- Consumes: `crud.list_collection_results`, `crud.get_result`, `crud.get_result_data` (Task 5 / sudah ada), `collection_list_row`, `normalize_weighted_report`, `is_collection_result_json` (Task 2), `MENU_COLLECTION_RESULTS` (Task 4), `ensure_can_view_result`, `effective_campaigns_for`, `collection_campaigns_from_env`, `has_perm`, `stage_table`.
- Produces (JSON):
  - `GET /collection/results?status&ai_status&ticket_id&date_start&date_end&page&limit` → `{"items": [row...], "total": int, "page": int, "limit": int, "campaigns": [str]}`
  - `GET /collection/results/{result_id}` → `{"result_id", "campaign", "status", "source_files", "uploaded_at", "completed_at", "processing_sec", "error", "current_stage", "stages", "report"}` (`report` = laporan ternormalisasi atau `null`)
  - `PDF` tetap lewat `GET /transcript_pdf/{result_id}?filename=` yang sudah ada (tidak menyentuh TMS).

- [ ] **Step 1: Tulis test yang gagal (tambahkan)**

```python
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers import collection as col


def _user():
    return SimpleNamespace(role="qc", username="u1")


def test_allowed_campaigns_irisan_env_dan_cakupan(monkeypatch):
    monkeypatch.setattr(col, "collection_campaigns_from_env", lambda: frozenset({"collection", "koleksi"}))
    monkeypatch.setattr(col, "effective_campaigns_for", lambda db, u: ["Collection", "Cashline"])
    assert col._allowed_campaigns(None, _user()) == ["collection"]


def test_allowed_campaigns_tanpa_pembatasan_memakai_seluruh_env(monkeypatch):
    monkeypatch.setattr(col, "collection_campaigns_from_env", lambda: frozenset({"collection"}))
    monkeypatch.setattr(col, "effective_campaigns_for", lambda db, u: None)
    assert col._allowed_campaigns(None, _user()) == ["collection"]


def test_list_ditolak_tanpa_capability(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: False)
    with pytest.raises(HTTPException) as exc:
        col.list_collection_results(db=None, current_user=_user())
    assert exc.value.status_code == 403


def test_detail_campaign_bukan_collection_404(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(col.crud, "get_result", lambda db, rid: SimpleNamespace(
        id=rid, campaign="Cashline", status="done", source_files=[], uploaded_at=None,
        completed_at=None, processing_sec=None, error_message=None, current_stage=None))
    monkeypatch.setattr(col, "ensure_can_view_result", lambda db, u, r: None)
    monkeypatch.setattr(col, "_allowed_campaigns", lambda db, u: ["collection"])
    with pytest.raises(HTTPException) as exc:
        col.get_collection_result("r1", db=None, current_user=_user())
    assert exc.value.status_code == 404


def test_detail_done_mengembalikan_laporan_ternormalisasi(monkeypatch):
    monkeypatch.setattr(col, "has_perm", lambda db, u, p: True)
    monkeypatch.setattr(col.crud, "get_result", lambda db, rid: SimpleNamespace(
        id=rid, campaign="Collection", status="done", source_files=["1_a.pdf"], uploaded_at=None,
        completed_at=None, processing_sec=3.2, error_message=None, current_stage="tandai_selesai"))
    monkeypatch.setattr(col, "ensure_can_view_result", lambda db, u, r: None)
    monkeypatch.setattr(col, "_allowed_campaigns", lambda db, u: ["collection"])
    monkeypatch.setattr(col.crud, "get_result_data", lambda db, rid: SimpleNamespace(
        result_json={"report_type": "collection_weighted",
                     "evaluation": {"scorecard_result": [{"weight": 4, "status": "PASS"}]}}))
    out = col.get_collection_result("r1", db=None, current_user=_user())
    assert out["report"]["ai_score_phase_2"] == 4
    assert out["report"]["ai_status"] == "PASS"
    assert out["source_files"] == ["1_a.pdf"]
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `RUN_API_TESTS tests/test_collection_router.py`
Expected: FAIL — `ImportError: cannot import name 'collection' from 'api.routers'`

- [ ] **Step 3: Tulis router**

```python
"""Menu Collection Results — hasil audit BERBOBOT campaign penagihan.

Terpisah dari ``/list_results`` karena laporannya berformat lain
(``compliance.collection_report``) dan karena seluruh pengayaan menu Results —
TMS submit_time, Ascend, dokumen/SLA, banding, manual check — tidak berlaku untuk
penagihan. Endpoint di sini HANYA membaca ``results`` + ``result_data``.

PDF transkrip memakai ``GET /transcript_pdf/{result_id}`` yang sudah ada: ia
hanya membaca MinIO dan sudah menjaga cakupan tiket.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import MENU_COLLECTION_RESULTS
from api.qc_scope import ensure_can_view_result
from api.rbac import collection_campaigns_from_env, effective_campaigns_for, has_perm
from compliance.collection_report import (
    collection_list_row,
    is_collection_result_json,
    normalize_weighted_report,
)
from compliance.processing_stages import stage_table
from db import crud

router = APIRouter(prefix="/collection", tags=["collection"])


def _allowed_campaigns(db, current_user) -> list:
    """Campaign Collection yang boleh dilihat: env ∩ cakupan campaign efektif.
    ``None`` dari ``effective_campaigns_for`` = tidak dibatasi."""
    collection = collection_campaigns_from_env()
    scope = effective_campaigns_for(db, current_user)
    if scope is None:
        return sorted(collection)
    return sorted(collection & {c.strip().casefold() for c in scope})


def _require_menu(db, current_user):
    if not has_perm(db, current_user, MENU_COLLECTION_RESULTS):
        raise HTTPException(status_code=403, detail="Akses ditolak")


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Tanggal tidak valid: {value}")


@router.get("/results")
def list_collection_results(
    status: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None, description="PASS | FAIL"),
    ticket_id: Optional[str] = Query(None),
    date_start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_menu(db, current_user)
    campaigns = _allowed_campaigns(db, current_user)
    rows, total = crud.list_collection_results(
        db, campaigns=campaigns, status=status, ai_status=ai_status, ticket_id=ticket_id,
        date_start=_parse_date(date_start), date_end=_parse_date(date_end),
        page=page, limit=limit,
    )
    return {
        "items": [collection_list_row(r, rj) for r, rj in rows],
        "total": total, "page": page, "limit": limit, "campaigns": campaigns,
    }


@router.get("/results/{result_id}")
def get_collection_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_menu(db, current_user)
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result tidak ditemukan")
    ensure_can_view_result(db, current_user, result)
    # 404, bukan 403: tiket Cashline tidak "terlarang" di sini, ia memang bukan
    # bagian menu ini — detailnya ada di menu Results.
    if (result.campaign or "").strip().casefold() not in _allowed_campaigns(db, current_user):
        raise HTTPException(status_code=404, detail="Result ini bukan campaign Collection")

    report = None
    if result.status == "done":
        data = crud.get_result_data(db, result_id)
        rj = data.result_json if data else None
        if is_collection_result_json(rj):
            report = normalize_weighted_report(rj.get("evaluation"))

    iso = lambda dt: dt.isoformat() if dt is not None else None  # noqa: E731
    return {
        "result_id": str(result.id),
        "campaign": result.campaign,
        "status": result.status,
        "source_files": list(result.source_files or []),
        "uploaded_at": iso(result.uploaded_at),
        "completed_at": iso(result.completed_at),
        "processing_sec": result.processing_sec,
        "error": result.error_message if result.status == "failed" else None,
        "current_stage": result.current_stage,
        "stages": stage_table(result.current_stage) if result.status in ("pending", "processing") else [],
        "report": report,
    }
```

Di `api/main.py`: tambahkan `collection` ke impor router (ikuti bentuk impor yang ada) dan `app.include_router(collection.router)` sesudah `app.include_router(app_setting.router)`.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `RUN_API_TESTS tests/test_collection_router.py`
Expected: PASS (5 test router baru lulus; 4 test DB lulus atau skip)

- [ ] **Step 5: Commit**

```bash
git -C telemarketing-qc-api add api/routers/collection.py api/main.py tests/test_collection_router.py
git -C telemarketing-qc-api commit -m "feat(api): endpoint /collection/results daftar dan detail tanpa TMS/Ascend"
```

---

### Task 7: Dashboard — capability, route, menu, helper tampilan

**Files:**
- Modify: `telemarketing-qc-dashboard/src/permissions.js`
- Modify: `telemarketing-qc-dashboard/src/router/index.js` (**gitignored** — catat di deskripsi PR)
- Modify: `telemarketing-qc-dashboard/src/components/SidebarMenu.vue`
- Create: `telemarketing-qc-dashboard/src/utils/collectionReport.js`
- Test: `telemarketing-qc-dashboard/src/utils/collectionReport.test.mjs`
- Modify: `telemarketing-qc-dashboard/package.json` (script test)

**Interfaces:**
- Produces:
  - `P.MENU_COLLECTION_RESULTS = 'menu.collection_results'`; `ROUTE_PERMISSIONS['/dashboard/collection']`
  - Route `/dashboard/collection` → `CollectionView.vue`; `/dashboard/collection/:resultId` → `CollectionDetailView.vue`
  - `collectionReport.js`: `verdictTone(value) -> 'success'|'danger'|'warning'|'muted'`, `verdictLabel(value) -> string`, `commitmentBadge(status) -> {label, tone}`, `scorePercent(report) -> number`, `groupScorecard(items) -> [{category, items, weight, earned}]`, `formatEvidence(evidence) -> string|null`, `formatDateTime(iso) -> string`

- [ ] **Step 1: Tulis test yang gagal**

```js
// Jalankan: node --test src/utils/collectionReport.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  verdictTone, verdictLabel, commitmentBadge, scorePercent, groupScorecard, formatEvidence,
} from './collectionReport.js'

test('verdictTone memetakan kedua kosakata verdict', () => {
  assert.equal(verdictTone('PASS'), 'success')
  assert.equal(verdictTone('SESUAI'), 'success')
  assert.equal(verdictTone('MATCH'), 'success')
  assert.equal(verdictTone('FAIL'), 'danger')
  assert.equal(verdictTone('BELUM_SESUAI'), 'danger')
  assert.equal(verdictTone('MISMATCH'), 'danger')
  assert.equal(verdictTone('TIDAK_TERSEDIA'), 'muted')
  assert.equal(verdictTone('SKIPPED_NULL'), 'muted')
  assert.equal(verdictTone(undefined), 'muted')
})

test('verdictLabel tidak pernah menampilkan kode mentah bergaris bawah', () => {
  assert.equal(verdictLabel('BELUM_SESUAI'), 'Belum Sesuai')
  assert.equal(verdictLabel('TIDAK_TERSEDIA'), 'Tidak Tersedia')
  assert.equal(verdictLabel('SKIPPED_NULL'), 'Tanpa Acuan')
  assert.equal(verdictLabel(null), '—')
})

test('commitmentBadge', () => {
  assert.deepEqual(commitmentBadge('COMMITTED_TO_PAY'), { label: 'Berkomitmen Membayar', tone: 'success' })
  assert.deepEqual(commitmentBadge('REFUSED'), { label: 'Menolak', tone: 'danger' })
  assert.deepEqual(commitmentBadge('xxx'), { label: 'Tidak Disebutkan', tone: 'muted' })
})

test('scorePercent aman terhadap maksimum nol', () => {
  assert.equal(scorePercent({ ai_score_phase_2: 90, maximum_score: 120 }), 75)
  assert.equal(scorePercent({ ai_score_phase_2: 0, maximum_score: 0 }), 0)
})

test('groupScorecard menjaga urutan kategori pertama kali muncul', () => {
  const g = groupScorecard([
    { category: 'B', weight: 2, item_score: 2 },
    { category: 'A', weight: 3, item_score: null },
    { category: 'B', weight: 4, item_score: 0 },
  ])
  assert.deepEqual(g.map(x => [x.category, x.items.length, x.weight, x.earned]), [['B', 2, 6, 2], ['A', 1, 3, 0]])
})

test('formatEvidence', () => {
  assert.equal(formatEvidence({ timestamp: '00:12', quote: 'halo' }), '[00:12] "halo"')
  assert.equal(formatEvidence({ timestamp: null, quote: 'halo' }), '"halo"')
  assert.equal(formatEvidence({ timestamp: '00:12', quote: null }), null)
  assert.equal(formatEvidence(null), null)
})
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `cd /data/scorecard_v2/telemarketing-qc-dashboard && node --test src/utils/collectionReport.test.mjs`
Expected: FAIL — `Cannot find module '.../collectionReport.js'`

- [ ] **Step 3: Tulis helper**

```js
// Helper murni tampilan laporan audit berbobot Collection. Tidak mengimpor Vue,
// supaya bisa diuji `node --test` seperti assignTicketData.test.mjs.
//
// Kosakata verdict mengikuti api core/compliance/collection_report.py. Nilai yang
// tidak dikenal SELALU jatuh ke 'muted' — tidak pernah ditebak lulus/gagal.

const SUCCESS = new Set(['PASS', 'SESUAI', 'MATCH'])
const DANGER = new Set(['FAIL', 'BELUM_SESUAI', 'MISMATCH'])

const LABELS = {
  PASS: 'Pass', FAIL: 'Fail', SESUAI: 'Sesuai', BELUM_SESUAI: 'Belum Sesuai',
  TIDAK_DINILAI: 'Tidak Dinilai', TIDAK_TERSEDIA: 'Tidak Tersedia',
  MATCH: 'Cocok', MISMATCH: 'Tidak Cocok', SKIPPED_NULL: 'Tanpa Acuan',
  INITIATED: 'Dibahas', NOT_INITIATED: 'Tidak Dibahas',
}

const COMMITMENT = {
  COMMITTED_TO_PAY: { label: 'Berkomitmen Membayar', tone: 'success' },
  PARTIAL_COMMITMENT: { label: 'Komitmen Sebagian', tone: 'warning' },
  DISPUTE: { label: 'Sengketa', tone: 'warning' },
  REFUSED: { label: 'Menolak', tone: 'danger' },
  NOT_STATED: { label: 'Tidak Disebutkan', tone: 'muted' },
}

export function verdictTone(value) {
  if (SUCCESS.has(value)) return 'success'
  if (DANGER.has(value)) return 'danger'
  return 'muted'
}

export function verdictLabel(value) {
  if (value == null || value === '') return '—'
  return LABELS[value] || String(value)
}

export function commitmentBadge(status) {
  return COMMITMENT[status] || COMMITMENT.NOT_STATED
}

export function scorePercent(report) {
  const max = Number(report?.maximum_score) || 0
  if (max <= 0) return 0
  return Math.round(((Number(report?.ai_score_phase_2) || 0) / max) * 1000) / 10
}

export function groupScorecard(items) {
  const groups = new Map()
  for (const it of items || []) {
    const key = it.category || '-'
    if (!groups.has(key)) groups.set(key, { category: key, items: [], weight: 0, earned: 0 })
    const g = groups.get(key)
    g.items.push(it)
    g.weight += Number(it.weight) || 0
    g.earned += Number(it.item_score) || 0
  }
  return [...groups.values()]
}

export function formatEvidence(evidence) {
  if (!evidence || !evidence.quote) return null
  return evidence.timestamp ? `[${evidence.timestamp}] "${evidence.quote}"` : `"${evidence.quote}"`
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  // Stempel dari API naive UTC; tampilkan dalam WIB seperti menu lain.
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', dateStyle: 'medium', timeStyle: 'short' })
}
```

- [ ] **Step 4: Jalankan test, pastikan lulus; daftarkan di `package.json`**

Ubah script test menjadi:
```json
"test": "node --test src/views/qc/assignTicketData.test.mjs src/utils/collectionReport.test.mjs"
```
Run: `npm test`
Expected: seluruh test lulus (test lama + 6 baru)

- [ ] **Step 5: Capability, route, menu**

`src/permissions.js` — di blok Menu sesudah `MENU_ROLE_HIERARCHY`:
```js
  MENU_COLLECTION_RESULTS: 'menu.collection_results',
```
dan di `ROUTE_PERMISSIONS` sesudah `'/dashboard/results'`:
```js
  '/dashboard/collection': P.MENU_COLLECTION_RESULTS,
```
(detail `/dashboard/collection/:resultId` mewarisi izin lewat pencarian prefix di router.)

`src/router/index.js` — sesudah route `/dashboard/results`:
```js
  {
    // Collection Results: hasil audit berbobot POJK 22 campaign penagihan (17 September 2026).
    // Berkas router ada di .gitignore — salin blok ini manual ke tiap environment.
    path: '/dashboard/collection',
    component: () => import('../views/dashboard/CollectionView.vue'),
  },
  {
    path: '/dashboard/collection/:resultId',
    component: () => import('../views/dashboard/CollectionDetailView.vue'),
  },
```

`src/components/SidebarMenu.vue` — sesudah RouterLink Results (baris ~39):
```vue
        <RouterLink v-if="can(P.MENU_COLLECTION_RESULTS)" to="/dashboard/collection" class="menu-item" active-class="active" :title="collapsed ? 'Collection Results' : ''">
          <span class="icon">CR</span> <span class="label">Collection Results</span>
        </RouterLink>
```

Buat berkas sementara agar build tidak gagal sebelum Task 8/10:
`src/views/dashboard/CollectionView.vue` dan `CollectionDetailView.vue` berisi
```vue
<template><SidebarLayout title="Collection Results" /></template>
<script setup>import SidebarLayout from '../../components/SidebarLayout.vue'</script>
```

Run: `npm run build`
Expected: build sukses tanpa error.

- [ ] **Step 6: Commit**

```bash
git -C telemarketing-qc-dashboard add src/permissions.js src/components/SidebarMenu.vue src/utils/collectionReport.js src/utils/collectionReport.test.mjs package.json src/views/dashboard/CollectionView.vue src/views/dashboard/CollectionDetailView.vue
git -C telemarketing-qc-dashboard commit -m "feat(collection): menu, capability, dan helper tampilan laporan berbobot"
```
(`src/router/index.js` tidak ter-commit karena gitignored — sebutkan di PR.)

---

### Task 8: Dashboard — halaman daftar `CollectionView.vue`

**Files:**
- Modify (ganti isi sementara): `telemarketing-qc-dashboard/src/views/dashboard/CollectionView.vue`

**Interfaces:**
- Consumes: `GET /collection/results` (Task 6), `formatDateTime`, `verdictTone`, `verdictLabel` (Task 7), `SidebarLayout`, `TablePager`.

- [ ] **Step 1: Baca pola yang ditiru**

Run: `sed -n 80,410p src/views/dashboard/TranscriptsView.vue` dan `sed -n 1,60p src/components/TablePager.vue`
Tujuan: salin kelas CSS `.filter-bar`, `.text-input`, `.btn-clear`, `.table-card`, `.data-table`, `.data-row`, `.empty`, `.skeleton-*`, `.error-box` apa adanya, dan pahami bentuk prop `v` pada `TablePager` (`{page, pageCount, ...}`) beserta event-nya. Gunakan bentuk yang sama persis di Step 2.

- [ ] **Step 2: Tulis halaman**

```vue
<template>
  <SidebarLayout title="Collection Results">
    <div class="filter-bar">
      <input v-model="ticketId" type="text" class="text-input" placeholder="Cari Tiket ID…" @input="debounced" />
      <input v-model="dateStart" type="date" class="text-input date-input" title="Dari tanggal upload" @change="reload(1)" />
      <input v-model="dateEnd" type="date" class="text-input date-input" title="Sampai tanggal upload" @change="reload(1)" />
      <select v-model="aiStatus" class="text-input" @change="reload(1)">
        <option value="">Semua Hasil</option>
        <option value="PASS">Pass</option>
        <option value="FAIL">Fail</option>
      </select>
      <select v-model="status" class="text-input" @change="reload(1)">
        <option value="">Semua Status Proses</option>
        <option value="done">Selesai</option>
        <option value="processing">Diproses</option>
        <option value="pending">Menunggu</option>
        <option value="failed">Gagal</option>
      </select>
      <button class="btn-clear" @click="reset">Reset</button>
    </div>

    <div class="summary-strip" v-if="!loading && items.length">
      <div class="summary-tile"><span class="k">Total tiket</span><span class="v">{{ total }}</span></div>
      <div class="summary-tile"><span class="k">Pass (halaman ini)</span><span class="v tone-success">{{ passCount }}</span></div>
      <div class="summary-tile"><span class="k">Fail (halaman ini)</span><span class="v tone-danger">{{ failCount }}</span></div>
      <div class="summary-tile"><span class="k">Rata-rata skor</span><span class="v">{{ avgPercent }}%</span></div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="loading" class="skeleton-list"><div class="skeleton-row" v-for="i in 5" :key="i"></div></div>

    <div v-else class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Tiket ID</th>
            <th>Tanggal Upload</th>
            <th>Agent</th>
            <th>Konsumen</th>
            <th class="num">Skor</th>
            <th>Hasil</th>
            <th>Kritis</th>
            <th class="num">Error Code</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="items.length === 0"><td colspan="9" class="empty">Tidak ada data.</td></tr>
          <tr
            v-for="row in items" :key="row.result_id" class="data-row" tabindex="0" role="link"
            @click="open(row)" @keydown.enter.prevent="open(row)"
          >
            <td class="cell-strong mono">{{ row.ticket_id || '—' }}</td>
            <td class="cell-date">{{ formatDateTime(row.uploaded_at) }}</td>
            <td>{{ row.agent_name || '—' }}</td>
            <td>{{ row.consumer_full_name || '—' }}</td>
            <td class="num mono">
              <template v-if="row.score != null">{{ row.score }} / {{ row.maximum_score }}</template>
              <template v-else>—</template>
            </td>
            <td><span class="pill" :class="`tone-${verdictTone(row.ai_status)}`">{{ verdictLabel(row.ai_status) }}</span></td>
            <td><span class="pill" :class="`tone-${verdictTone(row.critical_status)}`">{{ verdictLabel(row.critical_status) }}</span></td>
            <td class="num">{{ row.error_code_count }}</td>
            <td>{{ STATUS_LABEL[row.status] || row.status }}</td>
          </tr>
        </tbody>
      </table>
      <!-- Sesuaikan prop/event dengan bentuk TablePager yang dibaca di Step 1. -->
      <TablePager :v="pager" @page="reload" />
    </div>
  </SidebarLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SidebarLayout from '../../components/SidebarLayout.vue'
import TablePager from '../../components/TablePager.vue'
import apiClient from '../../api/client.js'
import { formatDateTime, verdictTone, verdictLabel } from '../../utils/collectionReport.js'

const STATUS_LABEL = { done: 'Selesai', processing: 'Diproses', pending: 'Menunggu', failed: 'Gagal' }
const LIMIT = 20

const router = useRouter()
const items = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const ticketId = ref('')
const dateStart = ref('')
const dateEnd = ref('')
const aiStatus = ref('')
const status = ref('')

const pager = computed(() => ({ page: page.value, pageCount: Math.max(1, Math.ceil(total.value / LIMIT)), total: total.value }))
const passCount = computed(() => items.value.filter(r => r.ai_status === 'PASS').length)
const failCount = computed(() => items.value.filter(r => r.ai_status === 'FAIL').length)
const avgPercent = computed(() => {
  const scored = items.value.filter(r => r.score != null && r.maximum_score > 0)
  if (!scored.length) return 0
  return Math.round(scored.reduce((s, r) => s + r.score / r.maximum_score, 0) / scored.length * 1000) / 10
})

async function reload(p = page.value) {
  page.value = p
  loading.value = true
  error.value = ''
  try {
    const { data } = await apiClient.get('/collection/results', {
      params: {
        page: page.value, limit: LIMIT,
        ticket_id: ticketId.value || undefined, ai_status: aiStatus.value || undefined,
        status: status.value || undefined,
        date_start: dateStart.value || undefined, date_end: dateEnd.value || undefined,
      },
    })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Gagal memuat hasil Collection.'
  } finally {
    loading.value = false
  }
}

let timer
function debounced() { clearTimeout(timer); timer = setTimeout(() => reload(1), 350) }
function reset() { ticketId.value = dateStart.value = dateEnd.value = aiStatus.value = status.value = ''; reload(1) }
function open(row) { router.push(`/dashboard/collection/${row.result_id}`) }

onMounted(() => reload(1))
</script>

<style scoped>
/* Salin blok .filter-bar/.text-input/.btn-clear/.table-card/.data-table/.data-row/
   .empty/.skeleton-*/.error-box dari TranscriptsView.vue (Step 1) di sini. */
.summary-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 14px; }
.summary-tile { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
.summary-tile .k { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; }
.summary-tile .v { font-size: 22px; font-weight: 700; }
.mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; border: 1px solid transparent; }
.tone-success { color: #1F8A4C; } .pill.tone-success { background: #E2F2E8; border-color: #b7dfc6; }
.tone-danger { color: #C73838; }  .pill.tone-danger { background: #FBE4E4; border-color: #f0bcbc; }
.tone-warning { color: #C98A00; } .pill.tone-warning { background: #FBF0D2; border-color: #f0dca0; }
.tone-muted { color: #636466; }   .pill.tone-muted { background: #EEEFF1; border-color: #E4E5E8; }
</style>
```

- [ ] **Step 3: Verifikasi build dan tampilan**

Run: `npm run build` → sukses.
Jalankan dev server (`npm run dev`), login sebagai admin, buka `/dashboard/collection`. Expected: filter bar + tabel tampil; tanpa data tampil "Tidak ada data."; Network tab hanya memanggil `/collection/results` (tidak ada `/list_results`, `/tickets_daily*`).

- [ ] **Step 4: Commit**

```bash
git -C telemarketing-qc-dashboard add src/views/dashboard/CollectionView.vue
git -C telemarketing-qc-dashboard commit -m "feat(collection): halaman daftar Collection Results"
```

---

### Task 9: Dashboard — panel PDF yang lebih bagus

**Files:**
- Modify: `telemarketing-qc-dashboard/src/utils/pdfRender.js` (opsi `zoom`)
- Create: `telemarketing-qc-dashboard/src/components/collection/CollectionPdfPanel.vue`

**Interfaces:**
- Produces:
  - `createPdfPageRenderer().renderAll(pdfDoc, container, { zoom = 1 } = {})` — `zoom` dikalikan ke lebar pas-halaman; pemanggil lama (tanpa argumen ketiga) tidak berubah.
  - `<CollectionPdfPanel :result-id="string" :files="string[]" />`

Peningkatan dibanding `PdfViewer.vue` (yang tetap dipakai menu lain, tidak diubah):
1. Header gelap bergradasi bergaya panel qc-collection (ikon dokumen oranye Mega, nama berkas mono emas).
2. **Tab per berkas** bila tiket punya >1 PDF, alih-alih akordeon bertumpuk.
3. **Toolbar**: nomor halaman `3 / 7` yang mengikuti scroll, tombol halaman sebelumnya/berikutnya, zoom −/+ (50–200%), "Pas lebar", Unduh, Tab baru, **Layar penuh** (Fullscreen API).
4. Muat otomatis saat panel tampil (tidak perlu klik), skeleton halaman saat memuat.
5. Tetap canvas + lapisan teks pdf.js supaya Ctrl+F bekerja (alasan di `PdfViewer.vue` masih berlaku).

- [ ] **Step 1: Tambah opsi zoom di `pdfRender.js`**

Ubah signature dan perhitungan skala:

```js
  async function renderAll(pdfDoc, container, { zoom = 1 } = {}) {
    if (!pdfDoc || !container) return
    const token = ++renderToken
    const width = contentWidth(container) * zoom
```

Tidak ada perubahan lain: `scale = width / base.width` otomatis ikut zoom, dan `--scale-factor` tetap sama dengan skala tampilan sehingga lapisan teks tidak bergeser. Karena halaman bisa lebih lebar dari wadah saat zoom > 1, lebar `.pdf-page` diatur panel (Step 2), bukan `width: 100%`.

Run: `npm run build` → sukses; buka satu tiket di menu Results/Transcripts dan pastikan PDF lama tetap tampil normal.

- [ ] **Step 2: Tulis komponen**

```vue
<template>
  <section ref="rootEl" class="cpdf" :class="{ fullscreen: isFullscreen }">
    <header class="cpdf-head">
      <div class="cpdf-title">
        <span class="cpdf-icon" aria-hidden="true">PDF</span>
        <div class="cpdf-title-text">
          <h3>Dokumen Transkrip</h3>
          <p>Berkas: <span class="cpdf-file">{{ active || '—' }}</span></p>
        </div>
      </div>
      <div class="cpdf-actions">
        <a v-if="downloadUrl" class="cpdf-btn" :href="downloadUrl" :download="active">Unduh</a>
        <a v-if="active" class="cpdf-btn" :href="nativeUrl" target="_blank" rel="noopener">Tab baru</a>
        <button class="cpdf-btn" type="button" @click="toggleFullscreen">{{ isFullscreen ? 'Keluar layar penuh' : 'Layar penuh' }}</button>
      </div>
    </header>

    <nav v-if="files.length > 1" class="cpdf-tabs" role="tablist">
      <button
        v-for="(f, i) in files" :key="f" type="button" role="tab" class="cpdf-tab"
        :class="{ on: f === active }" :aria-selected="f === active" @click="select(f)"
      >Rekaman {{ i + 1 }}</button>
    </nav>

    <div class="cpdf-toolbar">
      <div class="cpdf-group">
        <button type="button" :disabled="page <= 1" @click="goTo(page - 1)" aria-label="Halaman sebelumnya">‹</button>
        <span class="cpdf-page">{{ numPages ? `${page} / ${numPages}` : '—' }}</span>
        <button type="button" :disabled="page >= numPages" @click="goTo(page + 1)" aria-label="Halaman berikutnya">›</button>
      </div>
      <div class="cpdf-group">
        <button type="button" :disabled="zoom <= 0.5" @click="setZoom(zoom - 0.25)" aria-label="Perkecil">−</button>
        <span class="cpdf-zoom">{{ Math.round(zoom * 100) }}%</span>
        <button type="button" :disabled="zoom >= 2" @click="setZoom(zoom + 0.25)" aria-label="Perbesar">+</button>
        <button type="button" class="cpdf-fit" :disabled="zoom === 1" @click="setZoom(1)">Pas lebar</button>
      </div>
    </div>

    <div ref="scrollEl" class="cpdf-body" @scroll.passive="onScroll">
      <div v-if="loading" class="cpdf-skeleton"><div class="sk-page" v-for="i in 2" :key="i"></div></div>
      <div v-else-if="error" class="cpdf-state">{{ error }}</div>
      <div v-show="!loading && !error" ref="pagesEl" class="cpdf-pages"></div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { createPdfPageRenderer } from '../../utils/pdfRender.js'
import apiClient from '../../api/client.js'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const props = defineProps({
  resultId: { type: String, required: true },
  files: { type: Array, default: () => [] },
})

const rootEl = ref(null)
const scrollEl = ref(null)
const pagesEl = ref(null)
const active = ref(props.files[0] || '')
const loading = ref(false)
const error = ref('')
const downloadUrl = ref('')
const numPages = ref(0)
const page = ref(1)
const zoom = ref(1)
const isFullscreen = ref(false)

const { renderAll } = createPdfPageRenderer()
let pdfDoc = null
let resizeObserver = null
let lastWidth = 0

// Lihat PdfViewer.vue: <a target=_blank> tak bisa membawa header Authorization.
const nativeUrl = computed(() => {
  const base = apiClient.defaults.baseURL || ''
  const token = localStorage.getItem('access_token') || ''
  return `${base}/transcript_pdf/${encodeURIComponent(props.resultId)}`
    + `?filename=${encodeURIComponent(active.value)}&token=${encodeURIComponent(token)}`
})

function cleanupDoc() {
  if (downloadUrl.value) URL.revokeObjectURL(downloadUrl.value)
  downloadUrl.value = ''
  try { pdfDoc?.destroy?.() } catch { /* ignore */ }
  pdfDoc = null
  numPages.value = 0
  page.value = 1
}

async function load() {
  if (!active.value) return
  cleanupDoc()
  loading.value = true
  error.value = ''
  try {
    const res = await apiClient.get(`/transcript_pdf/${encodeURIComponent(props.resultId)}`, {
      params: { filename: active.value }, responseType: 'arraybuffer', headers: { Accept: 'application/pdf' },
    })
    const bytes = new Uint8Array(res.data)
    downloadUrl.value = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }))
    pdfDoc = await pdfjsLib.getDocument({ data: bytes }).promise
    numPages.value = pdfDoc.numPages
    loading.value = false
    await nextTick()
    await render()
  } catch (e) {
    let detail = ''
    try { detail = JSON.parse(new TextDecoder().decode(e?.response?.data))?.detail || '' } catch { /* bukan JSON */ }
    error.value = detail || (e?.response?.status ? `Gagal memuat PDF (HTTP ${e.response.status}).` : 'Gagal memuat PDF.')
    loading.value = false
  }
}

async function render() {
  if (!pdfDoc || !pagesEl.value) return
  lastWidth = scrollEl.value?.clientWidth || 0
  await renderAll(pdfDoc, pagesEl.value, { zoom: zoom.value })
}

function select(f) { if (f !== active.value) { active.value = f; load() } }

function setZoom(z) {
  zoom.value = Math.min(2, Math.max(0.5, Math.round(z * 100) / 100))
  render()
}

function pageEls() { return pagesEl.value ? [...pagesEl.value.querySelectorAll('.pdf-page')] : [] }

function goTo(n) {
  const el = pageEls()[n - 1]
  if (el && scrollEl.value) scrollEl.value.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' })
}

function onScroll() {
  const els = pageEls()
  if (!els.length || !scrollEl.value) return
  const mid = scrollEl.value.scrollTop + scrollEl.value.clientHeight / 3
  let current = 1
  els.forEach((el, i) => { if (el.offsetTop <= mid) current = i + 1 })
  page.value = current
}

async function toggleFullscreen() {
  if (document.fullscreenElement) await document.exitFullscreen()
  else await rootEl.value?.requestFullscreen?.()
}
function onFullscreenChange() {
  isFullscreen.value = document.fullscreenElement === rootEl.value
  nextTick(render)
}

watch(() => props.files, (fs) => {
  if (!fs.includes(active.value)) { active.value = fs[0] || ''; load() }
})

onMounted(() => {
  load()
  document.addEventListener('fullscreenchange', onFullscreenChange)
  if ('ResizeObserver' in window && scrollEl.value) {
    let t
    resizeObserver = new ResizeObserver(() => {
      const w = scrollEl.value?.clientWidth || 0
      if (!w || Math.abs(w - lastWidth) < 4) return
      clearTimeout(t)
      t = setTimeout(render, 150)
    })
    resizeObserver.observe(scrollEl.value)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  resizeObserver?.disconnect()
  cleanupDoc()
})
</script>

<style scoped>
.cpdf { display: flex; flex-direction: column; background: #fff; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 2px 8px rgba(30,31,33,.06); height: 100%; min-height: 0; }
.cpdf.fullscreen { border-radius: 0; }
.cpdf-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; color: #fff; background: linear-gradient(90deg, #1E1F21 0%, #002D62 100%); }
.cpdf-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.cpdf-icon { flex-shrink: 0; width: 34px; height: 34px; border-radius: 10px; background: #F37022; display: grid; place-items: center; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.cpdf-title-text { min-width: 0; }
.cpdf-title-text h3 { margin: 0; font-size: 14px; font-weight: 700; }
.cpdf-title-text p { margin: 2px 0 0; font-size: 11px; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cpdf-file { font-family: 'IBM Plex Mono', ui-monospace, monospace; color: #F2B600; font-weight: 600; }
.cpdf-actions { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }
.cpdf-btn { font-size: 12px; font-weight: 600; color: #fff; text-decoration: none; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.15); border-radius: 8px; padding: 5px 10px; cursor: pointer; }
.cpdf-btn:hover { background: rgba(255,255,255,.2); }
.cpdf-tabs { display: flex; gap: 4px; padding: 8px 12px 0; background: #F4F5F6; border-bottom: 1px solid var(--border); overflow-x: auto; }
.cpdf-tab { border: 1px solid transparent; border-bottom: none; background: transparent; padding: 7px 14px; font-size: 12px; font-weight: 600; color: #636466; border-radius: 8px 8px 0 0; cursor: pointer; white-space: nowrap; }
.cpdf-tab.on { background: #fff; color: #1E1F21; border-color: var(--border); box-shadow: inset 0 2px 0 #F37022; }
.cpdf-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 12px; background: #FAFBFC; border-bottom: 1px solid var(--border); }
.cpdf-group { display: flex; align-items: center; gap: 4px; }
.cpdf-group button { min-width: 30px; height: 30px; border: 1px solid #E4E5E8; background: #fff; border-radius: 8px; font-size: 15px; font-weight: 700; color: #1E1F21; cursor: pointer; }
.cpdf-group button:disabled { opacity: .4; cursor: default; }
.cpdf-group .cpdf-fit { font-size: 12px; padding: 0 10px; }
.cpdf-page, .cpdf-zoom { min-width: 64px; text-align: center; font-size: 12px; font-weight: 600; font-family: 'IBM Plex Mono', ui-monospace, monospace; color: #4A4B4E; }
.cpdf-body { flex: 1; min-height: 480px; max-height: calc(100vh - 220px); overflow: auto; background: #3f4246; }
.cpdf.fullscreen .cpdf-body { max-height: none; }
.cpdf-pages { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 18px; width: max-content; min-width: 100%; box-sizing: border-box; }
.cpdf-pages :deep(.pdf-page) { box-shadow: 0 4px 14px rgba(0,0,0,.45); background: #fff; border-radius: 2px; }
.cpdf-state { color: #fca5a5; text-align: center; padding: 40px 16px; font-size: 13px; }
.cpdf-skeleton { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 18px; }
.sk-page { width: min(100%, 720px); aspect-ratio: 1 / 1.414; background: linear-gradient(90deg, #55585c 0%, #62666a 50%, #55585c 100%); background-size: 200% 100%; animation: shimmer 1.2s linear infinite; border-radius: 2px; }
@keyframes shimmer { to { background-position: -200% 0; } }
</style>
```

> Catatan lebar halaman: `pdf-text-layer.css` menetapkan `.pdf-page`. Periksa `sed -n 15,30p src/assets/pdf-text-layer.css`; bila ia memaksa `width: 100%`, zoom > 100% tidak akan melebar. Dalam kasus itu tambahkan di `pdfRender.js`, sesudah `pageEl.style.setProperty('--scale-factor', ...)`: `pageEl.style.width = \`${Math.floor(viewport.width)}px\`` **hanya bila `zoom !== 1`**, supaya menu lain tidak berubah.

- [ ] **Step 3: Verifikasi manual**

Run: `npm run build` → sukses. Uji visual di Task 10 Step 4 (komponen dipakai di halaman detail).

- [ ] **Step 4: Commit**

```bash
git -C telemarketing-qc-dashboard add src/utils/pdfRender.js src/components/collection/CollectionPdfPanel.vue
git -C telemarketing-qc-dashboard commit -m "feat(collection): panel PDF bertab dengan toolbar halaman, zoom, dan layar penuh"
```

---

### Task 10: Dashboard — seksi laporan berbobot & halaman detail

**Files:**
- Create: `telemarketing-qc-dashboard/src/components/collection/CollectionReportHeader.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/CriticalCheckCard.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/DataVerificationTable.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/CategorySummaryGrid.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/ErrorCodeList.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/ScorecardDetail.vue`
- Create: `telemarketing-qc-dashboard/src/components/collection/collection.css`
- Modify (ganti isi sementara): `telemarketing-qc-dashboard/src/views/dashboard/CollectionDetailView.vue`

**Interfaces:**
- Consumes: `GET /collection/results/{id}` (Task 6); helper Task 7; `CollectionPdfPanel` (Task 9).
- Setiap komponen seksi menerima satu prop `report` (objek `WeightedAuditReport` ternormalisasi).

Pemetaan dari `qc-collection/src/components/WeightedAuditView.tsx`:

| Seksi TSX (baris) | Komponen Vue |
|---|---|
| Header skor + PASS/FAIL, komitmen, konteks agunan (100–225) | `CollectionReportHeader.vue` |
| Executive Summary (227–236) | di dalam `CollectionReportHeader.vue` (blok gelap di bawahnya) |
| Critical Compliance Check (238–310) | `CriticalCheckCard.vue` |
| SP Reference Check (312–380) | `DataVerificationTable.vue` |
| Ringkasan per kategori (382–450) | `CategorySummaryGrid.vue` |
| Error Code Analysis (451–500) | `ErrorCodeList.vue` |
| Rincian scorecard 25 indikator (502–652) | `ScorecardDetail.vue` |

- [ ] **Step 1: Baca sumbernya**

Run: `sed -n 1,100p /data/qc-collection/src/components/WeightedAuditView.tsx` dan `sed -n 238,652p /data/qc-collection/src/components/WeightedAuditView.tsx`
Tujuan: salin teks judul/subjudul Indonesia persis, urutan kolom tabel, dan teks catatan (mis. penjelasan agunan 16 poin). Kelas Tailwind diterjemahkan ke `collection.css` di bawah — dashboard tidak memakai Tailwind.

- [ ] **Step 2: Gaya bersama `collection.css`**

```css
/* Gaya seksi laporan Collection — terjemahan kelas Tailwind WeightedAuditView.tsx
   ke token warna mega.css. Di-import oleh CollectionDetailView.vue. */
.col-card { background: #fff; border: 1px solid #E4E5E8; border-radius: 14px; box-shadow: 0 1px 2px rgba(30,31,33,.06); padding: 20px 22px; }
.col-card + .col-card { margin-top: 16px; }
.col-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 12px; margin-bottom: 14px; border-bottom: 1px solid #EEEFF1; }
.col-card-head h2 { margin: 0; font-size: 16px; font-weight: 700; color: #1E1F21; }
.col-card-head p { margin: 2px 0 0; font-size: 12px; color: #818489; }
.col-pill { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; border: 1px solid transparent; white-space: nowrap; }
.col-pill.tone-success { color: #1F8A4C; background: #E2F2E8; border-color: #b7dfc6; }
.col-pill.tone-danger  { color: #C73838; background: #FBE4E4; border-color: #f0bcbc; }
.col-pill.tone-warning { color: #C98A00; background: #FBF0D2; border-color: #f0dca0; }
.col-pill.tone-muted   { color: #636466; background: #EEEFF1; border-color: #E4E5E8; }
.col-quote { background: #FAFBFC; border: 1px solid #E4E5E8; border-left: 3px solid #F37022; border-radius: 8px; padding: 8px 10px; font-size: 12px; font-style: italic; font-family: 'IBM Plex Mono', ui-monospace, monospace; color: #1E1F21; margin-top: 6px; }
.col-muted { color: #818489; font-size: 12px; }
.col-table-wrap { overflow-x: auto; }
.col-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.col-table th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #636466; background: #F4F5F6; padding: 8px 10px; border-bottom: 1px solid #E4E5E8; }
.col-table td { padding: 10px; border-bottom: 1px solid #EEEFF1; vertical-align: top; }
.col-mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
```

- [ ] **Step 3: Tulis komponen seksi**

`CollectionReportHeader.vue`:

```vue
<template>
  <div class="col-card header">
    <div class="hdr-main">
      <div class="hdr-meta">
        <span class="col-pill tone-muted col-mono">ID: {{ report.call_id }}</span>
        <span v-if="report.product_type" class="col-pill tone-muted">Produk: {{ report.product_type }}</span>
        <span class="col-pill tone-muted">{{ campaign }}</span>
      </div>
      <h1>Hasil Audit Berbobot Kepatuhan Penagihan</h1>
      <div class="hdr-people">
        <span>Agent: <b>{{ report.agent_name || '—' }}</b></span>
        <span>Konsumen: <b>{{ report.consumer_full_name || '—' }}</b></span>
        <span>Topik Agunan: <b>{{ verdictLabel(report.agunan_discussion_status) }}</b></span>
      </div>
    </div>

    <div class="hdr-score">
      <div class="score-block">
        <div class="score-k">Total Skor Audit</div>
        <div class="score-v col-mono">{{ report.ai_score_phase_2 }} <small>/ {{ report.maximum_score }}</small></div>
        <div class="score-bar" role="meter" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
          <span class="fill" :class="`tone-${verdictTone(report.ai_status)}`" :style="{ width: `${Math.min(percent, 100)}%` }"></span>
          <span class="grade" :style="{ left: '90%' }" title="Passing grade 90%"></span>
        </div>
        <div class="col-muted">Passing Grade: <b>{{ report.passing_grade }}</b> · {{ percent }}%</div>
      </div>
      <div class="verdict" :class="`tone-${verdictTone(report.ai_status)}`">
        <span class="verdict-v">{{ report.ai_status }}</span>
        <span class="verdict-k">{{ report.ai_status === 'PASS' ? 'Memenuhi Syarat' : 'Tidak Lulus' }}</span>
      </div>
    </div>

    <div class="hdr-grid">
      <div class="sub">
        <div class="sub-k">Status Komitmen Konsumen</div>
        <span class="col-pill" :class="`tone-${commitment.tone}`">{{ commitment.label }}</span>
        <p class="sub-text">{{ report.commitment_status.reason || '—' }}</p>
        <div v-if="formatEvidence(report.commitment_status.evidence)" class="col-quote">{{ formatEvidence(report.commitment_status.evidence) }}</div>
      </div>
      <div class="sub">
        <div class="sub-k">Konteks Diskusi Agunan &amp; Maksimal Skor</div>
        <div class="kv"><span>Status Pembahasan Agunan</span><b>{{ verdictLabel(report.agunan_discussion_status) }}</b></div>
        <div class="kv"><span>Skor Maksimal Evaluasi</span><b>{{ report.maximum_score }} poin</b></div>
        <p class="col-muted">
          {{ report.agunan_discussion_status === 'NOT_INITIATED'
            ? 'Kategori "Prosedur Penarikan Agunan" (16 poin) dieksklusi dari perhitungan karena topik agunan tidak dibahas.'
            : 'Kategori "Prosedur Penarikan Agunan" (16 poin) diikutsertakan secara penuh.' }}
        </p>
      </div>
    </div>
  </div>

  <div class="summary">
    <div class="summary-k">Ringkasan Eksekutif Audit AI</div>
    <p>{{ report.ai_summary || 'Model tidak mengembalikan ringkasan.' }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { verdictTone, verdictLabel, commitmentBadge, scorePercent, formatEvidence } from '../../utils/collectionReport.js'

const props = defineProps({ report: { type: Object, required: true }, campaign: { type: String, default: '' } })
const percent = computed(() => scorePercent(props.report))
const commitment = computed(() => commitmentBadge(props.report.commitment_status?.status))
</script>

<style scoped>
.header { display: grid; gap: 18px; }
.hdr-main h1 { margin: 8px 0 6px; font-size: 22px; font-weight: 800; color: #1E1F21; }
.hdr-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.hdr-people { display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; color: #636466; }
.hdr-people b { color: #1E1F21; }
.hdr-score { display: flex; flex-wrap: wrap; align-items: stretch; gap: 14px; background: #FAFBFC; border: 1px solid #E4E5E8; border-radius: 14px; padding: 14px 16px; }
.score-block { flex: 1; min-width: 220px; display: grid; gap: 6px; }
.score-k, .sub-k, .summary-k { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; font-weight: 700; color: #818489; }
.score-v { font-size: 30px; font-weight: 800; color: #1E1F21; }
.score-v small { font-size: 16px; color: #9E9FA3; font-weight: 500; }
.score-bar { position: relative; height: 8px; background: #E4E5E8; border-radius: 999px; overflow: visible; }
.score-bar .fill { position: absolute; inset: 0 auto 0 0; border-radius: 999px; }
.score-bar .fill.tone-success { background: #1F8A4C; } .score-bar .fill.tone-danger { background: #C73838; } .score-bar .fill.tone-muted { background: #9E9FA3; }
.score-bar .grade { position: absolute; top: -4px; width: 2px; height: 16px; background: #1E1F21; }
.verdict { min-width: 130px; display: grid; place-content: center; text-align: center; border-radius: 12px; color: #fff; padding: 10px 18px; }
.verdict.tone-success { background: #1F8A4C; } .verdict.tone-danger { background: #C73838; } .verdict.tone-muted { background: #818489; }
.verdict-v { font-size: 22px; font-weight: 800; letter-spacing: .08em; }
.verdict-k { font-size: 10px; text-transform: uppercase; font-weight: 600; opacity: .9; }
.hdr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.sub { background: #FAFBFC; border: 1px solid #E4E5E8; border-radius: 12px; padding: 12px 14px; display: grid; gap: 6px; align-content: start; }
.sub-text { margin: 0; font-size: 12px; color: #4A4B4E; line-height: 1.5; }
.kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid #EEEFF1; }
.summary { margin-top: 16px; border-radius: 14px; padding: 18px 22px; color: #e2e8f0; background: linear-gradient(90deg, #0b1f3a 0%, #1E1F21 100%); }
.summary-k { color: #F2B600; margin-bottom: 6px; }
.summary p { margin: 0; font-size: 14px; line-height: 1.6; }
</style>
```

`CriticalCheckCard.vue`:

```vue
<template>
  <div class="col-card">
    <div class="col-card-head">
      <div>
        <h2>Pemeriksaan Kepatuhan Kritis (Critical Compliance Check)</h2>
        <p>Evaluasi indikator utama berisiko sanksi OJK (Pasal 62 &amp; Pasal 22)</p>
      </div>
      <span class="col-pill" :class="`tone-${verdictTone(check.status)}`">{{ verdictLabel(check.status) }}</span>
    </div>
    <p v-if="!check.checked_items.length" class="col-muted">Model tidak mengembalikan rincian item kritis — verdict tidak ditebak.</p>
    <ul v-else class="crit-list">
      <li v-for="it in check.checked_items" :key="it.item_code">
        <span class="col-mono code">{{ it.item_code }}</span>
        <span class="req">{{ it.requirement || '—' }}</span>
        <span class="col-pill" :class="`tone-${verdictTone(it.status)}`">{{ verdictLabel(it.status) }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { verdictTone, verdictLabel } from '../../utils/collectionReport.js'
const props = defineProps({ report: { type: Object, required: true } })
const check = computed(() => props.report.critical_compliance_check)
</script>

<style scoped>
.crit-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.crit-list li { display: grid; grid-template-columns: 90px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border: 1px solid #EEEFF1; border-radius: 10px; }
.code { font-size: 12px; font-weight: 700; color: #4A4B4E; }
.req { font-size: 13px; color: #1E1F21; }
</style>
```

`DataVerificationTable.vue`:

```vue
<template>
  <div class="col-card">
    <div class="col-card-head">
      <div>
        <h2>Verifikasi Akurasi Data Tunggakan (SP Reference Check)</h2>
        <p>Nilai yang disebut dalam panggilan. Jalur Collection tidak membaca TMS/Ascend, jadi baris tanpa acuan ditandai "Tanpa Acuan".</p>
      </div>
    </div>
    <p v-if="!rows.length" class="col-muted">Tidak ada data tunggakan yang diekstrak.</p>
    <div v-else class="col-table-wrap">
      <table class="col-table">
        <thead><tr><th>Field</th><th>Acuan</th><th>Dari Transkrip</th><th>Kecocokan</th><th>Kemiripan</th><th>Alasan</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.field">
            <td class="col-mono">{{ r.field }}</td>
            <td>{{ r.reference_value ?? '—' }}</td>
            <td>{{ r.extracted_value ?? '—' }}</td>
            <td><span class="col-pill" :class="`tone-${verdictTone(r.match)}`">{{ verdictLabel(r.match) }}</span></td>
            <td class="col-mono">{{ r.similarity_percent != null ? `${r.similarity_percent}%` : '—' }}</td>
            <td class="col-muted">{{ r.reason || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { verdictTone, verdictLabel } from '../../utils/collectionReport.js'
const props = defineProps({ report: { type: Object, required: true } })
const rows = computed(() => props.report.collection_data_verification || [])
</script>
```

`CategorySummaryGrid.vue`:

```vue
<template>
  <div class="col-card">
    <div class="col-card-head">
      <div>
        <h2>Ringkasan Nilai Per Kategori (9 Kategori POJK 22)</h2>
        <p>Bobot kategori, skor diperoleh, dan hasil per kategori</p>
      </div>
    </div>
    <p v-if="!cats.length" class="col-muted">Model tidak mengembalikan ringkasan kategori.</p>
    <div v-else class="cat-grid">
      <article v-for="c in cats" :key="c.category" class="cat" :class="`edge-${verdictTone(c.category_result)}`">
        <header>
          <h3>{{ c.category }}</h3>
          <span class="col-pill" :class="`tone-${verdictTone(c.category_result)}`">{{ verdictLabel(c.category_result) }}</span>
        </header>
        <div class="cat-score col-mono">{{ c.earned_score }} <small>/ {{ c.total_weight }}</small></div>
        <div class="bar"><span :style="{ width: `${c.total_weight ? Math.min(100, c.earned_score / c.total_weight * 100) : 0}%` }"></span></div>
        <p v-if="c.fail_reason" class="col-muted">{{ c.fail_reason }}</p>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { verdictTone, verdictLabel } from '../../utils/collectionReport.js'
const props = defineProps({ report: { type: Object, required: true } })
const cats = computed(() => props.report.category_summary || [])
</script>

<style scoped>
.cat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.cat { border: 1px solid #E4E5E8; border-left-width: 4px; border-radius: 12px; padding: 12px; display: grid; gap: 6px; }
.cat.edge-success { border-left-color: #1F8A4C; } .cat.edge-danger { border-left-color: #C73838; } .cat.edge-muted { border-left-color: #C5C6CA; }
.cat header { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.cat h3 { margin: 0; font-size: 12px; font-weight: 700; line-height: 1.35; color: #1E1F21; }
.cat-score { font-size: 20px; font-weight: 800; }
.cat-score small { font-size: 12px; color: #9E9FA3; font-weight: 500; }
.bar { height: 6px; background: #EEEFF1; border-radius: 999px; overflow: hidden; }
.bar span { display: block; height: 100%; background: linear-gradient(120deg, #F2B600 0%, #F37022 100%); }
</style>
```

`ErrorCodeList.vue`:

```vue
<template>
  <div class="col-card">
    <div class="col-card-head">
      <div>
        <h2>Analisis Kode Pelanggaran OJK (Error Code Analysis)</h2>
        <p>Kode pelanggaran yang terpicu beserta bukti percakapan</p>
      </div>
      <span class="col-pill" :class="codes.length ? 'tone-danger' : 'tone-success'">{{ codes.length }} kode</span>
    </div>
    <p v-if="!codes.length" class="col-muted">Tidak ada kode pelanggaran yang terpicu.</p>
    <div v-else class="ec-list">
      <article v-for="(e, i) in codes" :key="`${e.error_code}-${i}`" class="ec">
        <h3><span class="col-mono">{{ e.error_code }}</span> {{ e.details_error }}</h3>
        <p v-if="e.trigger_source.reason" class="reason">{{ e.trigger_source.reason }}</p>
        <div v-if="formatEvidence(e.trigger_source.evidence)" class="col-quote">{{ formatEvidence(e.trigger_source.evidence) }}</div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatEvidence } from '../../utils/collectionReport.js'
const props = defineProps({ report: { type: Object, required: true } })
const codes = computed(() => props.report.error_codes || [])
</script>

<style scoped>
.ec-list { display: grid; gap: 10px; }
.ec { background: #FBE4E4; border: 1px solid #f0bcbc; border-radius: 12px; padding: 12px 14px; }
.ec h3 { margin: 0; font-size: 13px; font-weight: 700; color: #7f1d1d; }
.reason { margin: 6px 0 0; font-size: 12px; color: #4A4B4E; }
</style>
```

`ScorecardDetail.vue`:

```vue
<template>
  <div class="col-card">
    <div class="col-card-head">
      <div>
        <h2>Rincian Evaluasi Scorecard Berbobot ({{ report.scorecard_result.length }} Indikator)</h2>
        <p>Dikelompokkan per kategori; klik indikator untuk melihat alasan dan bukti</p>
      </div>
      <div class="filters">
        <button v-for="f in FILTERS" :key="f.value" type="button" :class="{ on: filter === f.value }" @click="filter = f.value">{{ f.label }}</button>
      </div>
    </div>

    <section v-for="g in groups" :key="g.category" class="grp">
      <header class="grp-head">
        <h3>{{ g.category }}</h3>
        <span class="col-mono col-muted">{{ g.earned }} / {{ g.weight }}</span>
      </header>
      <details v-for="it in g.items" :key="it.item_code" class="ind" :open="it.status === 'BELUM_SESUAI'">
        <summary>
          <span class="col-mono code">{{ it.item_code }}</span>
          <span class="req">{{ it.requirement || '—' }}</span>
          <span v-if="it.tolerable === 'NO'" class="col-pill tone-warning" title="Non-tolerable">Kritis</span>
          <span class="col-mono w">{{ it.item_score ?? '—' }} / {{ it.weight }}</span>
          <span class="col-pill" :class="`tone-${verdictTone(it.status)}`">{{ verdictLabel(it.status) }}</span>
        </summary>
        <div class="ind-body">
          <p class="reason">{{ it.reason || 'Tidak ada alasan dari model.' }}</p>
          <div v-if="formatEvidence(it.evidence)" class="col-quote">{{ formatEvidence(it.evidence) }}</div>
          <p v-if="it.kb_reference" class="col-muted">Referensi KB: <span class="col-mono">{{ it.kb_reference }}</span></p>
        </div>
      </details>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { verdictTone, verdictLabel, groupScorecard, formatEvidence } from '../../utils/collectionReport.js'

const props = defineProps({ report: { type: Object, required: true } })
const FILTERS = [
  { value: '', label: 'Semua' },
  { value: 'BELUM_SESUAI', label: 'Belum Sesuai' },
  { value: 'TIDAK_DINILAI', label: 'Tidak Dinilai' },
  { value: 'SESUAI', label: 'Sesuai' },
]
const filter = ref('')
const groups = computed(() => groupScorecard(
  (props.report.scorecard_result || []).filter(it => !filter.value || it.status === filter.value),
))
</script>

<style scoped>
.filters { display: flex; gap: 4px; flex-wrap: wrap; }
.filters button { border: 1px solid #E4E5E8; background: #fff; border-radius: 999px; padding: 4px 12px; font-size: 12px; font-weight: 600; color: #636466; cursor: pointer; }
.filters button.on { background: #1E1F21; color: #fff; border-color: #1E1F21; }
.grp + .grp { margin-top: 14px; }
.grp-head { display: flex; justify-content: space-between; align-items: baseline; padding: 6px 2px; }
.grp-head h3 { margin: 0; font-size: 13px; font-weight: 700; color: #1E1F21; }
.ind { border: 1px solid #EEEFF1; border-radius: 10px; margin-top: 6px; }
.ind summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 90px 1fr auto auto auto; gap: 10px; align-items: center; padding: 10px 12px; }
.ind summary::-webkit-details-marker { display: none; }
.ind[open] summary { border-bottom: 1px solid #EEEFF1; background: #FAFBFC; border-radius: 10px 10px 0 0; }
.code { font-size: 12px; font-weight: 700; color: #4A4B4E; }
.req { font-size: 13px; color: #1E1F21; }
.w { font-size: 12px; color: #636466; }
.ind-body { padding: 10px 12px 12px; display: grid; gap: 6px; }
.reason { margin: 0; font-size: 13px; color: #4A4B4E; line-height: 1.5; }
@media (max-width: 720px) { .ind summary { grid-template-columns: 1fr auto; } .ind summary .code, .ind summary .w { display: none; } }
</style>
```

- [ ] **Step 4: Halaman detail `CollectionDetailView.vue`**

```vue
<template>
  <SidebarLayout title="Collection Results">
    <div class="detail-top">
      <RouterLink to="/dashboard/collection" class="back">‹ Kembali ke daftar</RouterLink>
      <div class="layout-toggle" v-if="data?.report">
        <button type="button" :class="{ on: layout === 'split' }" @click="setLayout('split')">Laporan + PDF</button>
        <button type="button" :class="{ on: layout === 'report' }" @click="setLayout('report')">Laporan saja</button>
      </div>
    </div>

    <div v-if="loading" class="col-card">Memuat…</div>
    <div v-else-if="error" class="error-box">{{ error }}</div>

    <template v-else-if="data">
      <div v-if="data.status === 'failed'" class="error-box">Pemrosesan gagal: {{ data.error }}</div>

      <div v-else-if="data.status !== 'done'" class="col-card">
        <h2 class="stage-title">Tiket sedang diproses</h2>
        <ol class="stages">
          <li v-for="s in data.stages" :key="s.key" :class="s.state">{{ s.label }}</li>
        </ol>
      </div>

      <div v-else-if="!data.report" class="error-box">Hasil tiket ini bukan laporan berbobot Collection (mungkin diproses sebelum fitur ini aktif). Reprocess tiket untuk menilainya ulang.</div>

      <div v-else class="detail-grid" :class="layout">
        <div class="report-col">
          <CollectionReportHeader :report="data.report" :campaign="data.campaign" />
          <CriticalCheckCard :report="data.report" />
          <DataVerificationTable :report="data.report" />
          <CategorySummaryGrid :report="data.report" />
          <ErrorCodeList :report="data.report" />
          <ScorecardDetail :report="data.report" />
        </div>
        <aside v-if="layout === 'split'" class="pdf-col">
          <CollectionPdfPanel :result-id="data.result_id" :files="data.source_files" />
        </aside>
      </div>

      <div v-if="data.report && layout === 'report'" class="pdf-below">
        <CollectionPdfPanel :result-id="data.result_id" :files="data.source_files" />
      </div>
    </template>
  </SidebarLayout>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import SidebarLayout from '../../components/SidebarLayout.vue'
import apiClient from '../../api/client.js'
import CollectionReportHeader from '../../components/collection/CollectionReportHeader.vue'
import CriticalCheckCard from '../../components/collection/CriticalCheckCard.vue'
import DataVerificationTable from '../../components/collection/DataVerificationTable.vue'
import CategorySummaryGrid from '../../components/collection/CategorySummaryGrid.vue'
import ErrorCodeList from '../../components/collection/ErrorCodeList.vue'
import ScorecardDetail from '../../components/collection/ScorecardDetail.vue'
import CollectionPdfPanel from '../../components/collection/CollectionPdfPanel.vue'
import '../../components/collection/collection.css'

const LAYOUT_KEY = 'collection.detail.layout'
const route = useRoute()
const data = ref(null)
const loading = ref(true)
const error = ref('')
const layout = ref(readLayout())
let pollTimer = null

function readLayout() {
  try { return localStorage.getItem(LAYOUT_KEY) === 'report' ? 'report' : 'split' } catch { return 'split' }
}
function setLayout(v) {
  layout.value = v
  try { localStorage.setItem(LAYOUT_KEY, v) } catch { /* abaikan */ }
}

async function load() {
  try {
    const res = await apiClient.get(`/collection/results/${encodeURIComponent(route.params.resultId)}`)
    data.value = res.data
    error.value = ''
    // Tiket yang masih berjalan dipantau tiap 5 detik sampai selesai/gagal.
    clearTimeout(pollTimer)
    if (['pending', 'processing'].includes(res.data.status)) pollTimer = setTimeout(load, 5000)
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Gagal memuat detail hasil.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => clearTimeout(pollTimer))
</script>

<style scoped>
.detail-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.back { font-size: 13px; font-weight: 600; color: var(--text-muted); text-decoration: none; }
.back:hover { color: #F37022; }
.layout-toggle { display: inline-flex; border: 1px solid #E4E5E8; border-radius: 999px; overflow: hidden; background: #fff; }
.layout-toggle button { border: 0; background: transparent; padding: 6px 14px; font-size: 12px; font-weight: 600; color: #636466; cursor: pointer; }
.layout-toggle button.on { background: #1E1F21; color: #fff; }
.detail-grid.split { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(360px, 1fr); gap: 16px; align-items: start; }
.pdf-col { position: sticky; top: 16px; height: calc(100vh - 110px); }
.pdf-below { margin-top: 16px; }
.report-col > * + * { margin-top: 16px; }
.stage-title { margin: 0 0 10px; font-size: 15px; }
.stages { margin: 0; padding-left: 18px; display: grid; gap: 4px; font-size: 13px; }
.stages .selesai { color: #1F8A4C; } .stages .berjalan { color: #F37022; font-weight: 700; } .stages .menunggu { color: #9E9FA3; }
.error-box { background: #FBE4E4; border: 1px solid #f0bcbc; color: #7f1d1d; border-radius: 10px; padding: 12px 14px; font-size: 13px; }
@media (max-width: 1100px) { .detail-grid.split { grid-template-columns: 1fr; } .pdf-col { position: static; height: 80vh; } }
</style>
```

> Periksa nama field baris `stage_table`: `sed -n 44,80p telemarketing-qc-api/core/compliance/processing_stages.py`. Bila key-nya bukan `key`/`label`/`state`, sesuaikan tiga atribut di template `stages`.

- [ ] **Step 5: Verifikasi build dan visual**

Run: `npm run build` → sukses.
Dengan dev server dan data dari Task 11 (atau, sebelum Task 11, sisipkan satu baris `result_data` berisi `SAMPLE_WEIGHTED_REPORT` dari `qc-collection/src/data/defaultData.ts` sebagai `evaluation` di DB lokal):
- Buka `/dashboard/collection/<id>`. Expected: 7 seksi tampil berurutan seperti qc-collection; panel PDF menempel di kanan, tab per rekaman, nomor halaman berubah saat scroll, zoom −/+ bekerja dan Ctrl+F menemukan teks di PDF, Layar penuh bekerja, toggle "Laporan saja" memindahkan PDF ke bawah dan diingat setelah refresh.
- Lebar 400px (DevTools): satu kolom, tabel verifikasi bisa di-scroll horizontal, tidak ada scroll horizontal halaman.
- Network tab: hanya `/collection/results/{id}` dan `/transcript_pdf/{id}`.

- [ ] **Step 6: Commit**

```bash
git -C telemarketing-qc-dashboard add src/components/collection src/views/dashboard/CollectionDetailView.vue
git -C telemarketing-qc-dashboard commit -m "feat(collection): halaman detail laporan berbobot dengan panel PDF berdampingan"
```

---

### Task 11: Konfigurasi campaign & verifikasi end-to-end

**Files:**
- Create: `telemarketing-qc-api/campaigns/collection_weighted/prompt.txt`, `scorecard.json`, `kb.json`
- Create: `telemarketing-qc-api/scripts/export_collection_weighted_preset.mjs`
- Modify: `.env` api & worker (tidak di-commit): `COLLECTION_CAMPAIGNS=Collection`

- [ ] **Step 1: Skrip ekspor preset dari qc-collection**

```js
// Ekspor preset audit BERBOBOT qc-collection menjadi tiga berkas Upload Campaign.
// Jalankan: node --experimental-strip-types scripts/export_collection_weighted_preset.mjs
import { writeFileSync, mkdirSync } from 'node:fs'
import { presetFor } from '/data/qc-collection/src/data/analysisPresets.ts'

const out = new URL('../campaigns/collection_weighted/', import.meta.url)
mkdirSync(out, { recursive: true })
const p = presetFor('weighted')
writeFileSync(new URL('prompt.txt', out), p.systemPrompt)
writeFileSync(new URL('scorecard.json', out), p.scorecardJson)
writeFileSync(new URL('kb.json', out), p.kbJson)
console.log('ok', JSON.parse(p.scorecardJson).length, 'item scorecard')
```

Run: `cd telemarketing-qc-api && node --experimental-strip-types scripts/export_collection_weighted_preset.mjs`
Expected: `ok 25 item scorecard` (atau jumlah item sebenarnya) dan tiga berkas terbentuk.
Bila impor `.ts` gagal di node 22.20, jalankan skrip yang sama di dalam container: `docker run --rm -v /data/qc-collection:/data/qc-collection:ro -v "$PWD:/w" -w /w qc-collection-app node --experimental-strip-types scripts/export_collection_weighted_preset.mjs`.

- [ ] **Step 2: Cek prompt cocok dengan format transkrip pipeline**

Run: `grep -n "TRANSCRIPT\|timestamp\|JSON" campaigns/collection_weighted/prompt.txt | head -20`
Prompt qc-collection dibuat untuk transkrip `[mm:ss - mm:ss] SPEAKER: teks`, sedangkan `format_transcript_for_llm` menghasilkan penanda `=== Panggilan ke-N ===` dan baris per pembicara. Bila prompt menyebut format input tertentu, tambahkan satu paragraf di akhir `prompt.txt`:
```
Input transcript format note: the TRANSCRIPT block may contain several calls separated by "=== Panggilan ke-N ===" markers. Evaluate all calls together as one collection interaction and cite evidence timestamps exactly as they appear.
```
Keluaran JSON wajib tetap sesuai skema `WeightedAuditReport` yang ada di prompt — jangan diubah.

- [ ] **Step 3: Aktifkan fitur dan unggah campaign**

1. Set `COLLECTION_CAMPAIGNS=Collection` di `.env` API dan worker; `docker compose up -d` di kedua repo.
2. Login admin → Upload Campaign → nama `Collection`, unggah `scorecard.json`, `kb.json`, `prompt.txt`.
3. Login Collection (user dengan campaign Collection saja) → sidebar memuat **Collection Results**, **Upload Audio**, **Upload Transcript**, tanpa Assign Ticket/Manual Check/Pending Check.

- [ ] **Step 4: E2E**

1. Upload Transcript satu PDF penagihan ke campaign `Collection`.
2. Log worker: `docker logs -f telemarketing-qc-worker-worker-1 | grep -i "collection\|result"` → Expected: baris `token penilaian (collection)` dan `waktu per tahap ... (collection)`; **tidak ada** log `reference data`, `panggilan ... dibuang`, `rekaman utama`.
3. DB: `SELECT result_json->>'report_type', result_json ? 'reference_data' FROM result_data ORDER BY id DESC LIMIT 1;` → `collection_weighted | f`.
4. `/dashboard/collection` menampilkan tiket; `/dashboard/results` (login admin) **tidak** menampilkannya.
5. Detail tiket sesuai Task 10 Step 5.
6. Regresi Cashline: upload satu transkrip Cashline → selesai dengan format lama dan tampil di Results seperti biasa.
7. Rollback: kosongkan `COLLECTION_CAMPAIGNS`, restart → menu Collection hilang, perilaku lama utuh.

- [ ] **Step 5: Commit & PR**

```bash
git -C telemarketing-qc-api add campaigns/collection_weighted scripts/export_collection_weighted_preset.mjs
git -C telemarketing-qc-api commit -m "chore(collection): preset prompt/scorecard/KB audit berbobot dari qc-collection"
```
Buka PR di keempat repo (`gh pr create`). Deskripsi PR dashboard **wajib** memuat blok route dari Task 7 Step 5 karena `src/router/index.js` tidak ter-commit.

---

## Catatan & Asumsi

- **Format PDF transkrip Collection** diasumsikan sama dengan PDF diarization yang sudah dipakai Cashline (bisa di-parse `build_transcript`). Bila berbeda, worker gagal dengan pesan "Transkrip kosong" — itu disengaja, bukan diam-diam menghasilkan laporan kosong.
- **SP Reference Check** tanpa acuan: sesuai keputusan tidak menembak TMS/Ascend, kolom "Acuan" kosong dan kecocokan `Tanpa Acuan`/`Tidak Tersedia`. Sumber acuan (input manual/PDF SP) di luar lingkup rencana ini.
- **Statistics** tidak diubah; tiket Collection bisa ikut terhitung di sana sampai ada keputusan terpisah.
- **Reprocess** memakai task yang sama (`process_transcript`), jadi otomatis ikut jalur Collection.
