# Stats Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menu Stats menampilkan statistik Collection atau Cashline sesuai hak akses login; Admin dan login yang di-assign campaign Collection + Cashline mendapat toggle.

**Architecture:** Server menghitung `stats_views` per login (`api/rbac.py`) dan mengirimnya lewat `/auth/me`. Endpoint baru `GET /stats/collection` mengambil tiket Collection dalam cakupan (`collection_view_scope`, query yang sama dengan daftar Collection Results) lalu mengagregasi lewat fungsi murni core `compliance/collection_stats.py`. Endpoint Stats Cashline menolak login yang hanya berhak Collection. Dashboard `StatsView.vue` mendapat toggle dan panel baru `CollectionStatsPanel.vue`.

**Tech Stack:** Python / FastAPI / SQLAlchemy (api; core vendored ke worker & core), Vue 3 + vue-chartjs (dashboard), pytest, `node --test`.

**Spec:** `/data/scorecard_v2/telemarketing-qc-api/docs/superpowers/specs/2026-09-17-collection-stats-design.md`

## Global Constraints

- Branch kerja: `feat/collection-weighted-results` di api, worker, core, dashboard (sudah ada; jangan pindah branch, jangan push).
- Repo `telemarketing-qc-system` dan `/data/qc-collection` tidak boleh diubah.
- Core di-vendor: setiap berkas core yang dibuat/diubah harus identik di `telemarketing-qc-api/core/`, `telemarketing-qc-worker/core/`, `telemarketing-qc-core/src/qc_core/` (core memakai prefix impor `qc_core.`). Cek: `diff <(sed 's/qc_core\.//g' ../telemarketing-qc-core/src/qc_core/<path>) core/<path>`.
- Test DB **tidak pernah** memakai `.env` (DB bersama `10.155.32.28`). Gunakan runner Postgres sementara di bawah.
- `stats_views` hanya berisi subset berurutan dari `["cashline", "collection"]`.
- Keduanya hanya untuk: role ∈ `ADMIN_LIKE_ROLES` (`admin`, `demo`) atau login non-Admin yang campaign efektifnya berisi campaign Collection DAN non-Collection (bukan cakupan sales).
- Login non-Admin tanpa batas campaign (`effective_campaigns_for` = `None`) ⇒ `["cashline"]`.
- `COLLECTION_CAMPAIGNS` kosong ⇒ pemegang `menu.stats` mendapat `["cashline"]` dan seluruh perilaku Stats lama tidak berubah.
- Verdict tidak dikarang: laporan dibaca lewat `normalize_stored_report`; `TIDAK_TERSEDIA` tidak dihitung PASS/FAIL; pembagi nol ⇒ `None`.
- Persentase dibulatkan 1 desimal.
- Teks UI & komentar berbahasa Indonesia mengikuti gaya repo.
- Commit diakhiri baris kosong lalu `Co-Authored-By: <model yang menulis commit>`.

**Runner test API (Postgres sementara)** — skrip sudah ada di `/data/tmp/claude-1002/-data-scorecard-v2/91e4e11e-e84a-4a2b-8bad-4ddcfc07ce7a/scratchpad/run_db_tests.sh`; argumen = argumen pytest, contoh:

```bash
/data/tmp/claude-1002/-data-scorecard-v2/91e4e11e-e84a-4a2b-8bad-4ddcfc07ce7a/scratchpad/run_db_tests.sh "tests/test_collection_stats.py -p no:warnings"
```

Ia membuat jaringan + `postgres:16-alpine` sementara, menyalin `core/compliance`, `core/db`, `db/migrations`, `api`, `tests` ke image `local/qc-api:latest`, menjalankan `alembic upgrade head`, pytest, lalu menghapus container & jaringan. Disebut **`RUN_DB_TESTS "<args>"`** di bawah.

**Klarifikasi spec (diputuskan di rencana):** spec menulis endpoint Stats Cashline menolak 403 bila `"cashline"` tidak ada di `stats_views`. Karena endpoint-endpoint itu hari ini hanya butuh login (tidak memeriksa `menu.stats`), menolak semua login dengan `stats_views = []` akan mengubah perilaku di luar lingkup. Maka gerbangnya: **tolak hanya bila `"collection"` ada dan `"cashline"` tidak ada** (login yang hanya berhak Collection). Perilaku lain tidak berubah.

---

## File Structure

| Repo | Berkas | Tanggung jawab |
|---|---|---|
| core ×3 | `compliance/collection_stats.py` (baru) | Agregasi murni payload Stats Collection |
| api | `tests/test_collection_stats.py` (baru) | Test unit agregasi + test DB endpoint |
| core ×3 | `db/crud.py` (ubah) | `collection_results_query` bersama; `collection_stats_rows` |
| api | `api/rbac.py`, `api/schemas/auth.py`, `api/routers/auth.py` (ubah) | `stats_views_for`, field `/auth/me` |
| api | `tests/test_rbac_collection_permissions.py` (ubah) | Test `stats_views_for` |
| api | `api/routers/stats_collection.py` (baru), `api/main.py`, `api/routers/stats.py` (ubah) | Endpoint Collection + gerbang Cashline |
| dashboard | `src/utils/statsView.js` + `.test.mjs` (baru), `package.json` | Resolusi mode toggle (murni) |
| dashboard | `src/stores/auth.js`, `src/views/dashboard/StatsView.vue` (ubah) | `statsViews`, toggle, muat data per mode |
| dashboard | `src/components/collection/CollectionStatsPanel.vue` (baru) | Panel Stats Collection |
| api | `api/rbac.py`, `api/qc_scope.py` (ubah, Task 7) | Menu & cakupan Collection Results = Admin atau di-assign Collection |

---

### Task 1: Agregasi murni `aggregate_collection_stats`

**Files:**
- Create: `telemarketing-qc-api/core/compliance/collection_stats.py`
- Test: `telemarketing-qc-api/tests/test_collection_stats.py`
- Sync: `telemarketing-qc-worker/core/compliance/collection_stats.py`, `telemarketing-qc-core/src/qc_core/compliance/collection_stats.py` (ganti impor `compliance.` → `qc_core.compliance.`)

**Interfaces:**
- Consumes: `compliance.collection_report.normalize_stored_report(evaluation) -> dict`, `is_collection_result_json(result_json) -> bool` (sudah ada).
- Produces: `aggregate_collection_stats(rows) -> dict` dengan bentuk payload persis seperti spec bagian "Core". `rows`: iterable `(result, result_json)`; `result` punya `status`, `source_files`, `uploaded_at`, `generated_at`.

- [ ] **Step 1: Tulis test yang gagal**

```python
"""Stats Collection: agregasi murni atas laporan berbobot tersimpan.

Tanpa DB — ``rows`` adalah pasangan (result, result_json) tiruan.
"""
from datetime import datetime
from types import SimpleNamespace

from compliance.collection_report import REPORT_TYPE
from compliance.collection_stats import aggregate_collection_stats


def _res(status="done", generated_at=None, uploaded_at=datetime(2026, 9, 17, 3, 0)):
    return SimpleNamespace(status=status, source_files=["T1_a.pdf"],
                           generated_at=generated_at, uploaded_at=uploaded_at)


def _rep(*, agent="Tiwi", items=None, cats=None, critical=None, codes=None, commit="NOT_STATED", maximum=10):
    ev = {
        "agent_name": agent,
        "maximum_score": maximum,
        "scorecard_result": items if items is not None else [
            {"item_code": "A", "requirement": "salam", "category": "Pembukaan", "weight": 10, "status": "SESUAI"}],
        "category_summary": cats or [],
        "critical_compliance_check": critical or {"status": "PASS", "checked_items": []},
        "error_codes": codes or [],
        "commitment_status": {"status": commit},
    }
    return {"report_type": REPORT_TYPE, "evaluation": ev}


def test_input_kosong_pembagi_nol_none():
    out = aggregate_collection_stats([])
    assert out["kpi"] == {"total": 0, "done": 0, "in_progress": 0, "failed": 0, "with_report": 0,
                          "without_report": 0, "pass": 0, "fail": 0, "pass_rate": None,
                          "avg_score_percent": None}
    assert out["daily"] == [] and out["categories"] == [] and out["agents"] == []
    assert out["critical"] == {"pass": 0, "fail": 0, "unavailable": 0, "items": []}
    assert out["commitment"] == {"COMMITTED_TO_PAY": 0, "PARTIAL_COMMITMENT": 0, "DISPUTE": 0,
                                 "REFUSED": 0, "NOT_STATED": 0}


def test_kpi_status_dan_pass_fail():
    lulus = _rep()
    gagal = _rep(items=[{"item_code": "A", "weight": 10, "status": "BELUM_SESUAI", "category": "Pembukaan"}])
    rows = [(_res(), lulus), (_res(), gagal), (_res("pending"), None), (_res("processing"), None),
            (_res("failed"), None), (_res(), {"evaluation": {}})]
    k = aggregate_collection_stats(rows)["kpi"]
    assert (k["total"], k["done"], k["in_progress"], k["failed"]) == (6, 3, 2, 1)
    assert (k["with_report"], k["without_report"], k["pass"], k["fail"]) == (2, 1, 1, 1)
    assert k["pass_rate"] == 50.0
    assert k["avg_score_percent"] == 50.0


def test_tren_harian_generated_at_lalu_uploaded_wib():
    rows = [
        (_res(generated_at=datetime(2026, 9, 15, 23, 0)), _rep()),
        # 16 Sep 18:30 UTC = 17 Sep 01:30 WIB
        (_res(uploaded_at=datetime(2026, 9, 16, 18, 30)), _rep()),
    ]
    assert aggregate_collection_stats(rows)["daily"] == [
        {"date": "2026-09-15", "pass": 1, "fail": 0},
        {"date": "2026-09-17", "pass": 1, "fail": 0},
    ]


def test_kategori_dan_indikator():
    items = [
        {"item_code": "B", "requirement": "identitas", "category": "Pembukaan", "weight": 5, "status": "BELUM_SESUAI"},
        {"item_code": "A", "requirement": "salam", "category": "Pembukaan", "weight": 5, "status": "SESUAI"},
    ]
    cats = [{"category": "Pembukaan", "total_weight": 10, "earned_score": 5, "category_result": "FAIL"},
            {"category": "Penutup", "total_weight": 4, "earned_score": 4, "category_result": "??"}]
    out = aggregate_collection_stats([(_res(), _rep(items=items, cats=cats)),
                                      (_res(), _rep(items=items[:1], cats=cats[:1]))])
    assert out["categories"] == [
        {"category": "Pembukaan", "reports": 2, "avg_percent": 50.0, "fail": 2, "fail_rate": 100.0, "unavailable": 0},
        {"category": "Penutup", "reports": 1, "avg_percent": 100.0, "fail": 0, "fail_rate": 0.0, "unavailable": 1},
    ]
    assert out["top_failed_indicators"] == [
        {"item_code": "B", "requirement": "identitas", "category": "Pembukaan", "belum_sesuai": 2, "rate": 100.0}]


def test_top_indikator_maksimal_sepuluh_urut_stabil():
    items = [{"item_code": f"I{n:02d}", "requirement": "r", "category": "C", "weight": 1, "status": "BELUM_SESUAI"}
             for n in range(12)]
    top = aggregate_collection_stats([(_res(), _rep(items=items))])["top_failed_indicators"]
    assert [t["item_code"] for t in top] == [f"I{n:02d}" for n in range(10)]


def test_critical_dan_error_code():
    crit_fail = {"status": "FAIL", "checked_items": [
        {"item_code": "K1", "requirement": "tidak mengancam", "status": "FAIL"},
        {"item_code": "K2", "requirement": "identitas", "status": "PASS"}]}
    codes = [{"error_code": "E02", "details_error": ""}, {"error_code": "E02", "details_error": "ancaman"},
             "E01", " - "]
    out = aggregate_collection_stats([
        (_res(), _rep(critical=crit_fail, codes=codes)),
        (_res(), _rep(critical={"verifikasi": True})),   # bentuk datar -> TIDAK_TERSEDIA
        (_res(), _rep()),
    ])
    assert out["critical"] == {"pass": 1, "fail": 1, "unavailable": 1,
                               "items": [{"item_code": "K1", "requirement": "tidak mengancam", "fail": 1}]}
    assert out["error_codes"] == [{"error_code": "E02", "count": 2, "example": "ancaman"},
                                  {"error_code": "E01", "count": 1, "example": ""}]


def test_agent_dikelompokkan_dan_tidak_disebut():
    gagal_items = [{"item_code": "A", "weight": 10, "status": "BELUM_SESUAI", "category": "C"}]
    rows = [(_res(), _rep(agent="Ibu  Tiwi")), (_res(), _rep(agent=" ibu tiwi")),
            (_res(), _rep(agent="Ibu Tiwi", items=gagal_items)), (_res(), _rep(agent=None)),
            (_res(), _rep(agent="Andi"))]
    agents = aggregate_collection_stats(rows)["agents"]
    assert agents[0] == {"agent": "Ibu Tiwi", "tickets": 3, "pass": 2, "fail": 1,
                         "pass_rate": 66.7, "avg_score_percent": 66.7}
    assert [a["agent"] for a in agents[1:]] == ["Andi", "Tidak disebut"]


def test_komitmen():
    rows = [(_res(), _rep(commit="COMMITTED_TO_PAY")), (_res(), _rep(commit="REFUSED")),
            (_res(), _rep(commit="aneh"))]
    c = aggregate_collection_stats(rows)["commitment"]
    assert (c["COMMITTED_TO_PAY"], c["REFUSED"], c["NOT_STATED"]) == (1, 1, 1)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `RUN_DB_TESTS "tests/test_collection_stats.py -p no:warnings"`
Expected: FAIL — `ModuleNotFoundError: No module named 'compliance.collection_stats'`

- [ ] **Step 3: Implementasi**

Sebelum menulis, baca `core/compliance/collection_report.py` untuk memastikan nama & bentuk `normalize_stored_report` (payload: `ai_status`, `ai_score_phase_2`, `maximum_score`, `agent_name`, `scorecard_result[].{item_code,requirement,category,status}`, `category_summary[].{category,total_weight,earned_score,category_result}`, `critical_compliance_check.{status,checked_items[]}`, `error_codes[].{error_code,details_error}`, `commitment_status.status`). Bila `normalize_stored_report` mengubah `commitment_status` tidak dikenal menjadi `NOT_STATED` dan error code string menjadi dict, test di atas sudah sesuai.

```python
"""Statistik menu Stats untuk campaign Collection — agregasi MURNI.

Masukannya pasangan (result, result_json) yang sudah dipersempit ke cakupan login
(``api.qc_scope.collection_view_scope``). Setiap laporan dibaca ulang lewat
``normalize_stored_report`` supaya angka Stats sepakat dengan daftar & detail
Collection Results, dan verdict yang tidak terbaca (TIDAK_TERSEDIA) tidak pernah
dihitung sebagai PASS/FAIL.
"""
import re
from collections import Counter, OrderedDict
from datetime import timedelta

from compliance.collection_report import is_collection_result_json, normalize_stored_report

COMMITMENT_KEYS = ("COMMITTED_TO_PAY", "PARTIAL_COMMITMENT", "DISPUTE", "REFUSED", "NOT_STATED")
TOP_INDICATORS = 10
NO_AGENT = "Tidak disebut"
_WIB = timedelta(hours=7)


def _pct(num, den):
    return round(num / den * 100, 1) if den else None


def _avg(values):
    return round(sum(values) / len(values), 1) if values else None


def _ticket_date(result):
    if getattr(result, "generated_at", None) is not None:
        return result.generated_at.date().isoformat()
    if getattr(result, "uploaded_at", None) is not None:
        return (result.uploaded_at + _WIB).date().isoformat()
    return None


def _score_percent(report):
    maximum = report.get("maximum_score") or 0
    return report.get("ai_score_phase_2", 0) / maximum * 100 if maximum > 0 else None


def _agent_display(raw):
    return re.sub(r"\s+", " ", raw).strip() if isinstance(raw, str) else ""


def aggregate_collection_stats(rows) -> dict:
    kpi = Counter()
    daily = {}
    categories = OrderedDict()
    indicators = {}
    critical = Counter()
    critical_items = {}
    codes = OrderedDict()
    agents = {}
    commitment = Counter({k: 0 for k in COMMITMENT_KEYS})
    scores = []

    for result, result_json in rows:
        kpi["total"] += 1
        status = getattr(result, "status", None)
        if status in ("pending", "processing"):
            kpi["in_progress"] += 1
            continue
        if status == "failed":
            kpi["failed"] += 1
            continue
        if status != "done":
            continue
        kpi["done"] += 1
        if not is_collection_result_json(result_json):
            kpi["without_report"] += 1
            continue

        report = normalize_stored_report(result_json.get("evaluation"))
        kpi["with_report"] += 1
        verdict = report.get("ai_status")
        is_pass = verdict == "PASS"
        kpi["pass" if is_pass else "fail"] += 1
        percent = _score_percent(report)
        if percent is not None:
            scores.append(percent)

        day = _ticket_date(result)
        if day:
            bucket = daily.setdefault(day, {"date": day, "pass": 0, "fail": 0})
            bucket["pass" if is_pass else "fail"] += 1

        for cat in report.get("category_summary") or []:
            c = categories.setdefault(cat["category"], {"reports": 0, "percents": [], "fail": 0, "unavailable": 0})
            c["reports"] += 1
            if (cat.get("total_weight") or 0) > 0:
                c["percents"].append(cat.get("earned_score", 0) / cat["total_weight"] * 100)
            if cat.get("category_result") == "FAIL":
                c["fail"] += 1
            elif cat.get("category_result") == "TIDAK_TERSEDIA":
                c["unavailable"] += 1

        for item in report.get("scorecard_result") or []:
            code = (item.get("item_code") or "").strip()
            if item.get("status") != "BELUM_SESUAI" or code in ("", "-"):
                continue
            ind = indicators.setdefault(code, {"item_code": code, "requirement": item.get("requirement", ""),
                                               "category": item.get("category", ""), "belum_sesuai": 0})
            ind["belum_sesuai"] += 1

        check = report.get("critical_compliance_check") or {}
        crit_status = check.get("status")
        critical["pass" if crit_status == "PASS" else "fail" if crit_status == "FAIL" else "unavailable"] += 1
        for it in check.get("checked_items") or []:
            if it.get("status") != "FAIL":
                continue
            ci = critical_items.setdefault(it.get("item_code", "-"),
                                           {"item_code": it.get("item_code", "-"),
                                            "requirement": it.get("requirement", ""), "fail": 0})
            ci["fail"] += 1

        for err in report.get("error_codes") or []:
            code = (err.get("error_code") or "").strip()
            if code in ("", "-"):
                continue
            e = codes.setdefault(code, {"error_code": code, "count": 0, "example": ""})
            e["count"] += 1
            if not e["example"] and (err.get("details_error") or "").strip():
                e["example"] = err["details_error"].strip()

        display = _agent_display(report.get("agent_name"))
        key = display.casefold() if display else None
        a = agents.setdefault(key, {"names": Counter(), "tickets": 0, "pass": 0, "scores": []})
        a["names"][display or NO_AGENT] += 1
        a["tickets"] += 1
        a["pass"] += 1 if is_pass else 0
        if percent is not None:
            a["scores"].append(percent)

        commit = (report.get("commitment_status") or {}).get("status")
        commitment[commit if commit in COMMITMENT_KEYS else "NOT_STATED"] += 1

    with_report = kpi["with_report"]
    agent_rows = []
    for key, a in agents.items():
        name = NO_AGENT if key is None else sorted(a["names"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        agent_rows.append({"agent": name, "tickets": a["tickets"], "pass": a["pass"],
                           "fail": a["tickets"] - a["pass"], "pass_rate": _pct(a["pass"], a["tickets"]),
                           "avg_score_percent": _avg(a["scores"])})
    # "Tidak disebut" selalu di akhir; sisanya tiket terbanyak lalu nama.
    agent_rows.sort(key=lambda r: (r["agent"] == NO_AGENT, -r["tickets"], r["agent"]))

    return {
        "kpi": {
            "total": kpi["total"], "done": kpi["done"], "in_progress": kpi["in_progress"],
            "failed": kpi["failed"], "with_report": with_report, "without_report": kpi["without_report"],
            "pass": kpi["pass"], "fail": kpi["fail"], "pass_rate": _pct(kpi["pass"], with_report),
            "avg_score_percent": _avg(scores),
        },
        "daily": [daily[d] for d in sorted(daily)],
        "categories": [
            {"category": name, "reports": c["reports"], "avg_percent": _avg(c["percents"]),
             "fail": c["fail"], "fail_rate": _pct(c["fail"], c["reports"]), "unavailable": c["unavailable"]}
            for name, c in categories.items()
        ],
        "top_failed_indicators": [
            {**ind, "rate": _pct(ind["belum_sesuai"], with_report)}
            for ind in sorted(indicators.values(), key=lambda i: (-i["belum_sesuai"], i["item_code"]))[:TOP_INDICATORS]
        ],
        "critical": {
            "pass": critical["pass"], "fail": critical["fail"], "unavailable": critical["unavailable"],
            "items": sorted(critical_items.values(), key=lambda i: (-i["fail"], i["item_code"])),
        },
        "error_codes": sorted(codes.values(), key=lambda e: (-e["count"], e["error_code"])),
        "agents": agent_rows,
        "commitment": {k: commitment[k] for k in COMMITMENT_KEYS},
    }
```

> Spec menulis agent "urut tickets turun lalu nama"; rencana menaruh "Tidak disebut" selalu terakhir agar tidak menutupi nama sungguhan — test `test_agent_dikelompokkan_dan_tidak_disebut` mengikat perilaku ini.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `RUN_DB_TESTS "tests/test_collection_stats.py -p no:warnings"`
Expected: PASS (8 passed). Bila ada assertion yang gagal karena bentuk `normalize_stored_report` berbeda dari asumsi, sesuaikan IMPLEMENTASI (bukan test) kecuali test jelas bertentangan dengan spec; catat di laporan.

- [ ] **Step 5: Sinkron & commit**

```bash
cd /data/scorecard_v2
cp telemarketing-qc-api/core/compliance/collection_stats.py telemarketing-qc-worker/core/compliance/
sed 's/^from compliance\./from qc_core.compliance./' telemarketing-qc-api/core/compliance/collection_stats.py > telemarketing-qc-core/src/qc_core/compliance/collection_stats.py
diff <(sed 's/qc_core\.//g' telemarketing-qc-core/src/qc_core/compliance/collection_stats.py) telemarketing-qc-api/core/compliance/collection_stats.py && echo IDENTIK
git -C telemarketing-qc-api add core/compliance/collection_stats.py tests/test_collection_stats.py && git -C telemarketing-qc-api commit -m "feat(stats): agregasi murni Stats Collection"
git -C telemarketing-qc-worker add core/compliance/collection_stats.py && git -C telemarketing-qc-worker commit -m "chore(core): sinkron collection_stats"
git -C telemarketing-qc-core add src/qc_core/compliance/collection_stats.py && git -C telemarketing-qc-core commit -m "chore(core): sinkron collection_stats"
```

---

### Task 2: Query bersama `collection_results_query` + `collection_stats_rows`

**Files:**
- Modify: `telemarketing-qc-api/core/db/crud.py` (`list_collection_results`, baris ~394–486)
- Test: `telemarketing-qc-api/tests/test_collection_stats.py` (tambah bagian DB)
- Sync: `crud.py` ke worker & core (terapkan hunk yang sama; core memakai prefix `qc_core.` pada impor lokal)

**Interfaces:**
- Produces:
  - `collection_results_query(db, *, campaigns, uploaded_by_role=None, exclude_uploaded_by_role=None, status=None, ticket_id=None, date_start=None, date_end=None)` → SQLAlchemy query `(Result, ResultData.result_json)` terurut `uploaded_at desc`, atau `None` bila `campaigns` kosong.
  - `list_collection_results(...)` — signature & perilaku tetap; tubuhnya memakai `collection_results_query`.
  - `collection_stats_rows(db, *, campaigns, uploaded_by_role=None, exclude_uploaded_by_role=None, date_start=None, date_end=None) -> list[tuple[Result, dict | None]]`

- [ ] **Step 1: Tulis test DB yang gagal (tambah di `tests/test_collection_stats.py`)**

```python
import uuid

from db import crud
from db.models import Result, ResultData

CAMP = "ZZStatsCollection"


def _seed(db, *, status="done", campaign=CAMP, n_data=1, uploaded_by_role=None,
          uploaded_at=datetime(2026, 9, 17, 3, 0)):
    r = Result(id=uuid.uuid4(), campaign=campaign, status=status, uploaded_by_role=uploaded_by_role,
               source_files=[f"ZS{uuid.uuid4().hex[:8]}_call.pdf"], uploaded_at=uploaded_at)
    db.add(r)
    db.flush()
    for _ in range(n_data):
        db.add(ResultData(result_id=r.id, result_json=_rep()))
    db.flush()
    return r


def test_stats_rows_semua_status_tanpa_duplikat(db):
    a = _seed(db, n_data=2)
    b = _seed(db, status="pending", n_data=0)
    _seed(db, campaign="ZZStatsCashline")
    rows = crud.collection_stats_rows(db, campaigns=[CAMP])
    ids = [str(r.id) for r, _ in rows]
    assert sorted(ids) == sorted([str(a.id), str(b.id)])


def test_stats_rows_sepakat_dengan_daftar(db):
    for _ in range(3):
        _seed(db)
    _seed(db, uploaded_by_role="qc_support")
    kw = {"campaigns": [CAMP], "exclude_uploaded_by_role": "qc_support"}
    rows = crud.collection_stats_rows(db, **kw)
    _, total = crud.list_collection_results(db, limit=100, **kw)
    assert len(rows) == total == 3


def test_stats_rows_filter_tanggal_wib(db):
    _seed(db, uploaded_at=datetime(2026, 9, 16, 18, 30))  # 17 Sep WIB
    from datetime import date
    assert len(crud.collection_stats_rows(db, campaigns=[CAMP], date_start=date(2026, 9, 17),
                                          date_end=date(2026, 9, 17))) == 1
    assert crud.collection_stats_rows(db, campaigns=[CAMP], date_start=date(2026, 9, 16),
                                      date_end=date(2026, 9, 16)) == []


def test_stats_rows_campaign_kosong(db):
    assert crud.collection_stats_rows(db, campaigns=[]) == []
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `RUN_DB_TESTS "tests/test_collection_stats.py -p no:warnings"`
Expected: FAIL — `AttributeError: module 'db.crud' has no attribute 'collection_stats_rows'` (test unit Task 1 tetap lulus)

- [ ] **Step 3: Refaktor `list_collection_results`**

Pindahkan seluruh pembangunan query (subquery `result_data` terbaru, `hidden_ticket_filter`, filter campaign casefold, isolasi `uploaded_by_role`/`exclude_uploaded_by_role`, `status`, `ticket_id`, filter tanggal `series_date`, `order_by(desc(Result.uploaded_at))`) APA ADANYA ke fungsi baru tepat di atas `list_collection_results`:

```python
def collection_results_query(
    db: Session,
    *,
    campaigns,
    uploaded_by_role: Optional[str] = None,
    exclude_uploaded_by_role: Optional[str] = None,
    status: Optional[str] = None,
    ticket_id: Optional[str] = None,
    date_start=None,
    date_end=None,
):
    """Query ``(Result, result_json terbaru)`` tiket Collection dalam cakupan — satu
    definisi untuk daftar Collection Results DAN Stats Collection, supaya keduanya
    tidak pernah berbeda pendapat soal tiket mana yang terhitung. ``None`` bila
    ``campaigns`` kosong (tidak ada yang boleh dilihat)."""
    if not campaigns:
        return None
    # ... (isi yang dipindahkan dari list_collection_results, tanpa perubahan logika)
    return q
```

`list_collection_results` menjadi:

```python
    from compliance.collection_report import normalize_stored_report

    q = collection_results_query(
        db, campaigns=campaigns, uploaded_by_role=uploaded_by_role,
        exclude_uploaded_by_role=exclude_uploaded_by_role, status=status,
        ticket_id=ticket_id, date_start=date_start, date_end=date_end,
    )
    if q is None:
        return [], 0
    # (sisa: cabang ai_status & paginasi, tidak berubah)
```

Tambahkan sesudahnya:

```python
def collection_stats_rows(
    db: Session,
    *,
    campaigns,
    uploaded_by_role: Optional[str] = None,
    exclude_uploaded_by_role: Optional[str] = None,
    date_start=None,
    date_end=None,
) -> list:
    """Seluruh tiket Collection dalam cakupan (semua status, tanpa paginasi) untuk
    ``compliance.collection_stats.aggregate_collection_stats``."""
    q = collection_results_query(
        db, campaigns=campaigns, uploaded_by_role=uploaded_by_role,
        exclude_uploaded_by_role=exclude_uploaded_by_role,
        date_start=date_start, date_end=date_end,
    )
    return [] if q is None else [(r, rj) for r, rj in q.all()]
```

- [ ] **Step 4: Jalankan test baru + regresi**

Run: `RUN_DB_TESTS "tests/test_collection_stats.py tests/test_collection_router.py tests/test_collection_scope.py -p no:warnings"`
Expected: semua PASS.

- [ ] **Step 5: Sinkron & commit**

Terapkan hunk `crud.py` yang sama ke `telemarketing-qc-worker/core/db/crud.py` dan `telemarketing-qc-core/src/qc_core/db/crud.py` (cek `diff` dulu; untuk core ubah `from compliance.` → `from qc_core.compliance.` di impor lokal). Verifikasi identik dengan perintah diff di Global Constraints, lalu commit di tiga repo:
`refactor(collection): query bersama daftar & Stats Collection` / `chore(core): sinkron crud collection_results_query`.

---

### Task 3: `stats_views_for` dan `/auth/me`

**Files:**
- Modify: `telemarketing-qc-api/api/rbac.py`, `api/schemas/auth.py` (`MeResponse`), `api/routers/auth.py` (`me`)
- Test: `telemarketing-qc-api/tests/test_rbac_collection_permissions.py`

**Interfaces:**
- Consumes: `permissions_for`, `data_scope_for`, `effective_campaigns_for`, `collection_campaigns_from_env` (rbac), `perms.ADMIN_LIKE_ROLES`, `perms.is_sales_scope`, `perms.MENU_STATS`, `is_collection`.
- Produces:
  - `stats_views(role, permissions, data_scope, campaigns, collection_campaigns) -> list[str]` (murni)
  - `stats_views_for(db, user) -> list[str]`
  - `MeResponse.stats_views: list[str] = []`

- [ ] **Step 1: Tulis test yang gagal**

```python
ENV = frozenset({"collection"})
ALL = {P.MENU_STATS}


@pytest.mark.parametrize("role,perms_,scope,campaigns,env,expected", [
    ("admin", ALL, "all", None, ENV, ["cashline", "collection"]),
    ("demo", ALL, "all", None, ENV, ["cashline", "collection"]),
    ("admin", ALL, "all", None, frozenset(), ["cashline"]),
    ("spq_head", ALL, "all", None, ENV, ["cashline"]),
    ("qc", ALL, "qc_assigned", ["Collection"], ENV, ["collection"]),
    ("qc", ALL, "qc_assigned", ["Cashline"], ENV, ["cashline"]),
    ("qc", ALL, "qc_assigned", ["Cashline", " COLLECTION "], ENV, ["cashline", "collection"]),
    ("team_leader", ALL, "sales_tl", ["Cashline", "Collection"], ENV, ["cashline"]),
    ("sales_agent", ALL, "sales_agent", ["Collection"], ENV, []),
    ("qc", ALL, "qc_assigned", [], ENV, []),
    ("qc", set(), "qc_assigned", ["Collection"], ENV, []),
    ("qc", ALL, "qc_assigned", ["Collection"], frozenset(), ["cashline"]),
])
def test_stats_views(role, perms_, scope, campaigns, env, expected):
    assert rbac.stats_views(role, perms_, scope, campaigns, env) == expected
```

> Baris `("qc", ALL, "qc_assigned", ["Collection"], frozenset(), ["cashline"])`: env kosong ⇒ semua campaign dianggap non-Collection ⇒ perilaku lama. Baris `("qc", ALL, "qc_assigned", [], ENV, [])`: daftar kosong = dibatasi ke tidak ada apa pun.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `RUN_DB_TESTS "tests/test_rbac_collection_permissions.py -p no:warnings"`
Expected: FAIL — `AttributeError: module 'api.rbac' has no attribute 'stats_views'`

- [ ] **Step 3: Implementasi di `api/rbac.py` (sesudah `collection_results_visible`)**

```python
STATS_CASHLINE = "cashline"
STATS_COLLECTION = "collection"


def stats_views(role, permissions, data_scope, campaigns, collection_campaigns) -> list:
    """Tampilan Stats yang boleh dibuka: subset berurutan dari cashline/collection.

    Keputusan 17 September 2026: KEDUANYA hanya untuk Admin (``ADMIN_LIKE_ROLES``) dan
    login yang di-assign campaign Collection sekaligus non-Collection. Login non-Admin
    tanpa batas campaign tetap Cashline saja. Env kosong = perilaku lama (Cashline).
    Cakupan sales tidak pernah mendapat Collection (tidak ada pemetaan roster sales).
    """
    if perms.MENU_STATS not in permissions:
        return []
    if not collection_campaigns:
        return [STATS_CASHLINE]
    if role in perms.ADMIN_LIKE_ROLES:
        return [STATS_CASHLINE, STATS_COLLECTION]
    if campaigns is None:
        return [STATS_CASHLINE]
    has_collection = any(is_collection(c, collection_campaigns) for c in campaigns)
    has_other = any(not is_collection(c, collection_campaigns) for c in campaigns)
    views = []
    if has_other:
        views.append(STATS_CASHLINE)
    if has_collection and not perms.is_sales_scope(data_scope):
        views.append(STATS_COLLECTION)
    return views


def stats_views_for(db: Session, user) -> list:
    views = stats_views(
        getattr(user, "role", None),
        permissions_for(db, user),
        data_scope_for(db, user),
        effective_campaigns_for(db, user),
        collection_campaigns_from_env(),
    )
    if STATS_COLLECTION in views:
        # Gerbang data Collection yang sama dengan daftar Collection Results: cakupan
        # tak dikenal (None) tidak boleh mendapat tampilan yang isinya pasti ditolak.
        from api.qc_scope import collection_view_scope
        if collection_view_scope(db, user) is None:
            views = [v for v in views if v != STATS_COLLECTION]
    return views
```

Pastikan `data_scope_for` dan `effective_campaigns_for` terdefinisi di modul yang sama (sudah); bila `stats_views_for` diletakkan sebelum definisinya, pindahkan ke setelahnya.

`api/schemas/auth.py` — di `MeResponse` sesudah `campaigns`:
```python
    # Tampilan menu Stats yang boleh dibuka: subset ["cashline", "collection"].
    # Dua nilai = dashboard menampilkan toggle. Lihat ``api.rbac.stats_views``.
    stats_views: list[str] = []
```
`api/routers/auth.py` `me()` — tambah impor `stats_views_for` dan argumen `stats_views=stats_views_for(db, current_user),`.

- [ ] **Step 4: Jalankan test**

Run: `RUN_DB_TESTS "tests/test_rbac_collection_permissions.py tests/test_collection_scope.py -p no:warnings"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C telemarketing-qc-api add api/rbac.py api/schemas/auth.py api/routers/auth.py tests/test_rbac_collection_permissions.py
git -C telemarketing-qc-api commit -m "feat(rbac): stats_views Cashline/Collection per login di /auth/me"
```

---

### Task 4: Endpoint `GET /stats/collection` + gerbang Stats Cashline

**Files:**
- Create: `telemarketing-qc-api/api/routers/stats_collection.py`
- Modify: `api/main.py` (impor + `include_router`), `api/routers/stats.py` (endpoint Stats Cashline)
- Test: `telemarketing-qc-api/tests/test_collection_stats.py` (tambah bagian endpoint)

**Interfaces:**
- Consumes: `stats_views_for`, `STATS_CASHLINE`, `STATS_COLLECTION` (Task 3); `collection_view_scope`; `crud.collection_stats_rows` (Task 2); `aggregate_collection_stats` (Task 1).
- Produces:
  - `GET /stats/collection?date_start&date_end&campaign` → payload agregasi + `campaigns`, `date_start`, `date_end`.
  - `api.rbac.reject_collection_only_stats(db, user)` → raise 403 bila login hanya berhak Collection.

- [ ] **Step 1: Tulis test yang gagal**

Tiru fixture user di `tests/test_collection_scope.py` (`_user(db, role, campaigns)` membuat `User` + `UserCampaign`). Salin fungsi itu ke berkas ini.

```python
from fastapi import HTTPException
import pytest

from api.routers import stats_collection as sc
from api.routers import stats as st


@pytest.fixture()
def env_on(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", CAMP)


def _call(db, user, **kw):
    return sc.collection_stats(date_start=kw.get("date_start"), date_end=kw.get("date_end"),
                               campaign=kw.get("campaign"), db=db, current_user=user)


def test_qc_collection_only_sepakat_dengan_daftar(db, env_on):
    user = _user(db, "qc", [CAMP])
    for _ in range(2):
        _seed(db)
    out = _call(db, user)
    from api.routers import collection as col
    listed = col.list_collection_results(status=None, ai_status=None, ticket_id=None, date_start=None,
                                         date_end=None, page=1, limit=100, db=db, current_user=user)
    assert out["kpi"]["total"] == listed["total"] == 2
    assert out["kpi"]["pass"] == 2


def test_login_sales_ditolak(db, env_on):
    user = _user(db, "sales_agent", [CAMP])
    with pytest.raises(HTTPException) as exc:
        _call(db, user)
    assert exc.value.status_code == 403


def test_env_kosong_ditolak(db, monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    with pytest.raises(HTTPException) as exc:
        _call(db, _user(db, "admin"))
    assert exc.value.status_code == 403


def test_campaign_di_luar_cakupan_payload_nol(db, env_on):
    _seed(db)
    out = _call(db, _user(db, "admin"), campaign="ZZLain")
    assert out["kpi"]["total"] == 0


def test_stats_cashline_menolak_collection_only(db, env_on):
    with pytest.raises(HTTPException) as exc:
        st.stats_overview(db=db, current_user=_user(db, "qc", [CAMP]))
    assert exc.value.status_code == 403


def test_stats_cashline_tetap_melayani_admin(db, env_on):
    assert "overview" in st.stats_overview(db=db, current_user=_user(db, "admin"))
```

Sebelum menulis dua test terakhir, baca `stats_overview` di `api/routers/stats.py` untuk memastikan nama parameter & bentuk kembaliannya; sesuaikan assertion admin ke key yang benar-benar ada (bukan menebak). Pastikan role `qc`, `admin`, `sales_agent` ada di DB sementara (seed `DEFAULT_ROLES` lewat migrasi); bila tidak, tiru cara `tests/test_collection_scope.py` menyiapkan role.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `RUN_DB_TESTS "tests/test_collection_stats.py -p no:warnings"`
Expected: FAIL — `ImportError: cannot import name 'stats_collection'`

- [ ] **Step 3: Router `api/routers/stats_collection.py`**

```python
"""Stats Collection — statistik audit berbobot campaign penagihan.

Hanya membaca ``results`` + ``result_data`` dalam cakupan Collection login
(``api.qc_scope.collection_view_scope``) — tanpa TMS, Ascend, maupun roster sales.
Siapa yang boleh membuka tampilan ini ditentukan ``api.rbac.stats_views_for``.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.qc_scope import collection_view_scope
from api.rbac import STATS_COLLECTION, stats_views_for
from compliance.collection_stats import aggregate_collection_stats
from db import crud

router = APIRouter(tags=["stats"])


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Tanggal tidak valid: {value}")


@router.get("/stats/collection")
def collection_stats(
    date_start: Optional[str] = Query(None, description="YYYY-MM-DD, tanggal transkrip WIB"),
    date_end: Optional[str] = Query(None, description="YYYY-MM-DD, tanggal transkrip WIB"),
    campaign: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if STATS_COLLECTION not in stats_views_for(db, current_user):
        raise HTTPException(status_code=403, detail="Akses ditolak")
    scope = collection_view_scope(db, current_user)
    if scope is None:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    campaigns = scope["campaigns"]
    if campaign:
        wanted = campaign.strip().casefold()
        campaigns = [c for c in campaigns if c == wanted]
    d_start, d_end = _parse_date(date_start), _parse_date(date_end)
    iso = {k: v for k, v in scope.items() if k != "campaigns"}
    rows = crud.collection_stats_rows(db, campaigns=campaigns, date_start=d_start, date_end=d_end, **iso)
    return {
        **aggregate_collection_stats(rows),
        "campaigns": campaigns,
        "date_start": date_start,
        "date_end": date_end,
    }
```

Daftarkan di `api/main.py` mengikuti gaya impor router yang ada: impor `stats_collection` dan `app.include_router(stats_collection.router)` **sebelum** `app.include_router(stats.router)` (hindari bentrok path bila `stats.py` punya route `/stats/{...}` dinamis; periksa dulu).

- [ ] **Step 4: Gerbang Stats Cashline**

Di `api/rbac.py` (sesudah `stats_views_for`):

```python
def reject_collection_only_stats(db: Session, user) -> None:
    """403 bila login hanya berhak Stats Collection. Endpoint Stats Cashline
    sebelumnya cukup login; perilaku itu dipertahankan untuk semua login lain."""
    views = stats_views_for(db, user)
    if STATS_COLLECTION in views and STATS_CASHLINE not in views:
        raise HTTPException(status_code=403, detail="Akses ditolak")
```

Di `api/routers/stats.py`, panggil `reject_collection_only_stats(db, current_user)` sebagai baris pertama tubuh fungsi endpoint berikut (dan HANYA ini): `qc_performance` (`/stats/qc_performance`), `get_stats` (`/stats`), `get_daily_stats` (`/stats/daily`), `stats_overview`, `stats_campaigns_monthly`, `stats_hierarchy`, `stats_role_counts`, `stats_my_overview`, `stats_failure_reasons`, `stats_failure_reasons_hierarchy`, `stats_ai_status_timeseries`. Verifikasi: `grep -n "reject_collection_only_stats(db, current_user)" api/routers/stats.py | wc -l` → `11`. Bila ada endpoint `/stats/...` lain di berkas itu, catat di laporan dan beri gerbang yang sama.

- [ ] **Step 5: Jalankan test + regresi**

Run: `RUN_DB_TESTS "tests -p no:warnings"`
Expected: seluruh suite lulus; jumlah passed = sebelumnya + test baru, skipped tidak bertambah kecuali alasan yang dijelaskan.

- [ ] **Step 6: Commit**

```bash
git -C telemarketing-qc-api add api/routers/stats_collection.py api/main.py api/routers/stats.py api/rbac.py tests/test_collection_stats.py
git -C telemarketing-qc-api commit -m "feat(stats): endpoint /stats/collection; Stats Cashline menolak login Collection-only"
```

---

### Task 5: Dashboard — resolusi mode & toggle di StatsView

**Files:**
- Create: `telemarketing-qc-dashboard/src/utils/statsView.js`, `src/utils/statsView.test.mjs`
- Modify: `package.json` (script test), `src/stores/auth.js`, `src/views/dashboard/StatsView.vue`

**Interfaces:**
- Consumes: `/auth/me` field `stats_views` (Task 3).
- Produces:
  - `resolveStatsView(views, stored) -> 'cashline' | 'collection' | null`
  - `auth.statsViews` (computed, array)
  - `StatsView.vue` memakai `<CollectionStatsPanel />` (Task 6) pada mode `collection`.

- [ ] **Step 1: Test yang gagal**

```js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolveStatsView, STATS_VIEW_KEY } from './statsView.js'

test('satu tampilan dipakai apa adanya', () => {
  assert.equal(resolveStatsView(['collection'], 'cashline'), 'collection')
  assert.equal(resolveStatsView(['cashline'], null), 'cashline')
})

test('dua tampilan: pilihan tersimpan dihormati bila sah', () => {
  assert.equal(resolveStatsView(['cashline', 'collection'], 'collection'), 'collection')
  assert.equal(resolveStatsView(['cashline', 'collection'], 'aneh'), 'cashline')
  assert.equal(resolveStatsView(['cashline', 'collection'], null), 'cashline')
})

test('tanpa tampilan', () => {
  assert.equal(resolveStatsView([], 'cashline'), null)
  assert.equal(resolveStatsView(undefined, null), null)
})

test('kunci localStorage stabil', () => {
  assert.equal(STATS_VIEW_KEY, 'stats.view')
})
```

Run: `node --test src/utils/statsView.test.mjs` → FAIL (modul tidak ada).

- [ ] **Step 2: Implementasi helper**

```js
// Resolusi mode menu Stats (Cashline | Collection) dari `stats_views` server.
// Server yang memutuskan hak akses (api/rbac.py stats_views); di sini hanya
// memilih mana yang tampil bila login berhak keduanya.
export const STATS_VIEW_KEY = 'stats.view'

export function resolveStatsView(views, stored) {
  const list = Array.isArray(views) ? views : []
  if (!list.length) return null
  if (list.includes(stored)) return stored
  return list[0]
}
```

Tambahkan berkas test ke script `test` di `package.json` (gabung dengan yang ada). Run `npm test` → semua PASS.

- [ ] **Step 3: Store**

Di `src/stores/auth.js` tambahkan `const statsViews = computed(() => user.value?.stats_views || [])` di sebelah `campaigns`, dan ekspor di objek return.

- [ ] **Step 4: StatsView**

Baca `src/views/dashboard/StatsView.vue` penuh sebelum mengubah. Ubahan minimal:

1. Di dalam `<div class="mega-scope stats-page">`, sebelum konten yang ada, tambahkan toggle yang memakai kelas `.tab-group`/`.tab` yang sudah ada di berkas ini:
```vue
      <div v-if="statsViews.length > 1" class="toolbar">
        <div class="tab-group" role="tablist" aria-label="Jenis statistik">
          <button type="button" role="tab" class="tab" :class="{ active: mode === 'cashline' }"
                  :aria-selected="mode === 'cashline'" @click="setMode('cashline')">Cashline</button>
          <button type="button" role="tab" class="tab" :class="{ active: mode === 'collection' }"
                  :aria-selected="mode === 'collection'" @click="setMode('collection')">Collection</button>
        </div>
      </div>
      <CollectionStatsPanel v-if="mode === 'collection'" />
      <div v-else-if="!mode" class="empty-state">Tidak ada statistik yang dapat ditampilkan untuk akun ini.</div>
```
2. Bungkus SELURUH konten Cashline yang ada (cabang `isScopedRole` dan non-scoped) dalam `<template v-if="mode === 'cashline'">…</template>`.
3. Script:
```js
import CollectionStatsPanel from '../../components/collection/CollectionStatsPanel.vue'
import { resolveStatsView, STATS_VIEW_KEY } from '../../utils/statsView.js'
// …
const statsViews = computed(() => auth.statsViews)   // pakai instance store yang sudah ada di berkas; bila belum ada, useAuthStore()
function readStoredView() { try { return localStorage.getItem(STATS_VIEW_KEY) } catch { return null } }
const mode = ref(resolveStatsView(statsViews.value, readStoredView()))
function setMode(v) {
  if (!statsViews.value.includes(v) || v === mode.value) return
  mode.value = v
  try { localStorage.setItem(STATS_VIEW_KEY, v) } catch { /* abaikan */ }
}
```
4. Pemuatan & timer Cashline hanya berjalan saat `mode === 'cashline'`: pindahkan isi `onMounted` yang ada ke fungsi `startCashline()` dan pembersihan timer ke `stopCashline()`; lalu
```js
watch(mode, (m) => { stopCashline(); if (m === 'cashline') startCashline() }, { immediate: false })
onMounted(() => { if (mode.value === 'cashline') startCashline() })
onUnmounted(stopCashline)
```
   Pastikan tidak ada request Cashline yang terkirim saat mode `collection` (login Collection-only akan menerima 403).
5. Gaya `.empty-state` sederhana memakai token yang ada.

Buat komponen sementara `src/components/collection/CollectionStatsPanel.vue` berisi `<template><div /></template>` agar build lulus (diganti di Task 6).

Run: `npm test` dan `npm run build` → lulus.

- [ ] **Step 5: Commit**

```bash
git -C telemarketing-qc-dashboard add package.json src/utils/statsView.js src/utils/statsView.test.mjs src/stores/auth.js src/views/dashboard/StatsView.vue src/components/collection/CollectionStatsPanel.vue
git -C telemarketing-qc-dashboard commit -m "feat(stats): toggle Cashline | Collection sesuai stats_views"
```

---

### Task 6: Dashboard — `CollectionStatsPanel.vue`

**Files:**
- Modify (ganti isi sementara): `telemarketing-qc-dashboard/src/components/collection/CollectionStatsPanel.vue`

**Interfaces:**
- Consumes: `GET /stats/collection` (Task 4); `verdictLabel`, `commitmentBadge` dari `src/utils/collectionReport.js`; `Bar` dari `vue-chartjs` (sudah dipakai `StatsView.vue` — tiru registrasi Chart.js di sana, jangan menduplikasi registrasi global bila sudah ada).

- [ ] **Step 1: Baca pola**

Baca `StatsView.vue`: kartu KPI (kelas kartu/grid), opsi chart batang bertumpuk (`stackedOptions`), gaya tabel; dan `CollectionView.vue`: pola AbortController + requestId. Tiru kelas/token tersebut; jangan membuat sistem gaya baru.

- [ ] **Step 2: Implementasi**

Struktur (Bahasa Indonesia):
1. Filter: input tanggal "Dari" / "Sampai" (tanggal transkrip) + tombol Reset; berubah ⇒ muat ulang.
2. Kartu KPI: Total tiket (`kpi.total`), Selesai (`done`), Diproses (`in_progress`), Gagal proses (`failed`), PASS (`pass`), FAIL (`fail`), PASS rate (`pass_rate`%), Rata-rata skor (`avg_score_percent`%). `None` ⇒ "—". Bila `without_report > 0`, tampilkan keterangan kecil "N tiket selesai tanpa laporan berbobot".
3. Grafik "Tren harian PASS/FAIL": `Bar` bertumpuk, label = `daily[].date`, dataset PASS (warna sukses) & FAIL (warna bahaya) dari token yang dipakai StatsView.
4. Grid dua kolom:
   - "Kepatuhan per Kategori": tabel Kategori | Laporan | Rata-rata skor | FAIL | % FAIL | Tidak Tersedia.
   - "Indikator Paling Sering Belum Sesuai": tabel Kode | Requirement | Kategori | Jumlah | % laporan.
5. Grid dua kolom:
   - "Critical Compliance": tiga angka PASS / FAIL / Tidak Tersedia + tabel item FAIL (Kode | Requirement | FAIL).
   - "Kode Pelanggaran OJK": tabel Kode | Jumlah | Contoh.
6. Grid dua kolom:
   - "Per Agent": tabel Agent | Tiket | PASS | FAIL | PASS rate | Rata-rata skor.
   - "Komitmen Konsumen": daftar lima status dengan label `commitmentBadge(status).label` dan jumlahnya.
7. Kosong (`kpi.total === 0`) ⇒ "Belum ada data Collection pada rentang ini." (filter tetap tampil). Gagal ⇒ kotak error dengan `detail` API. Loading ⇒ skeleton seperti StatsView.
8. Muat ulang otomatis tiap 30 detik mengikuti StatsView; hentikan timer & abort request saat unmount.
9. Responsif: grid dua kolom ⇒ satu kolom di lebar < 1100px; tabel dalam wadah `overflow-x: auto`.
10. Key `v-for` unik (sertakan index bila field bisa berulang).

- [ ] **Step 3: Verifikasi**

Run: `npm test` dan `npm run build` → lulus. Tidak ada kredensial login: pengecekan visual diserahkan ke user; catat.

- [ ] **Step 4: Commit**

```bash
git -C telemarketing-qc-dashboard add src/components/collection/CollectionStatsPanel.vue
git -C telemarketing-qc-dashboard commit -m "feat(stats): panel Stats Collection (KPI, tren, kategori, critical, error code, agent, komitmen)"
```

---

### Task 7: Menu & cakupan Collection Results memakai aturan campaign yang sama

Keputusan user (17 September 2026): menu **Collection Results** (dan data di baliknya: daftar, detail, PDF) memakai aturan yang sama dengan Stats — **Admin** (`ADMIN_LIKE_ROLES`) atau login yang **di-assign** campaign Collection. Login non-Admin tanpa batas campaign (`effective_campaigns_for` = `None`, mis. SPQ Head / TL QC pusat) tidak lagi melihat Collection.

**Files:**
- Modify: `telemarketing-qc-api/api/rbac.py` (`collection_results_visible` + pemanggilnya di `permissions_for`), `api/qc_scope.py` (`collection_view_scope`)
- Test: `tests/test_rbac_collection_permissions.py`, `tests/test_collection_scope.py`, `tests/test_collection_stats.py`

**Interfaces:**
- Produces:
  - `collection_results_visible(role, data_scope, campaigns, collection_campaigns) -> bool` — parameter `role` DITAMBAHKAN di depan. True bila env tidak kosong DAN cakupan bukan sales DAN (`role` ∈ `ADMIN_LIKE_ROLES` ATAU (`campaigns` bukan `None` DAN ada campaign Collection di dalamnya)).
  - `collection_view_scope(db, user)`: bila role bukan Admin dan `effective_campaigns_for` = `None` ⇒ `None`. Admin tanpa batas ⇒ `campaigns = sorted(env)` seperti sekarang.
  - `stats_views` (Task 3) tetap sepakat: login yang mendapat `"collection"` di Stats = login yang melihat menu Collection Results (kecuali syarat `menu.stats`).

- [ ] **Step 1: Ubah/ tambah test (gagal dulu)**
  - Ganti test yang saat ini mengharapkan login non-Admin tanpa batas campaign (`effective=None`, mis. `tests/test_rbac_collection_permissions.py` sekitar baris 208–209) mendapat `MENU_COLLECTION_RESULTS`: sekarang harus TIDAK mendapat menu; tambahkan kasus Admin tanpa batas ⇒ mendapat menu, demo ⇒ mendapat menu.
  - `tests/test_collection_scope.py`: tambah kasus DB user `spq_head` (atau role non-Admin `data_scope: all`) tanpa `user_campaigns` ⇒ `collection_view_scope` = `None`, daftar kosong, detail 404/403, `collection_can_view` False; Admin tanpa batas ⇒ tetap melihat tiket Collection.
  - Sesuaikan test lain yang memanggil `collection_results_visible` dengan signature baru.
  - `tests/test_collection_stats.py`: tambah test bahwa untuk sekumpulan login (admin, demo, spq_head tanpa campaign, qc Collection-only, qc campuran, qc Cashline-only, sales campuran) `("collection" in stats_views_for) == (MENU_COLLECTION_RESULTS in permissions_for)` — dengan `menu.stats` dimiliki semua login tersebut.

  Run: `RUN_DB_TESTS "tests/test_rbac_collection_permissions.py tests/test_collection_scope.py tests/test_collection_stats.py -p no:warnings"` → FAIL pada kasus baru.

- [ ] **Step 2: Implementasi**
  - `collection_results_visible`: tambah parameter `role`; logika seperti di Interfaces; perbarui docstring (sebut keputusan 17 September 2026).
  - `permissions_for`: teruskan `getattr(user, "role", None)`.
  - `collection_view_scope`: sesudah pengecekan scope sales/tak dikenal, bila `effective is None` dan role bukan Admin ⇒ `return None`.
  - Rapikan `stats_views` (Task 3) agar memakai `collection_results_visible(role, data_scope, campaigns, env)` untuk bagian Collection — satu definisi, bukan dua.

- [ ] **Step 3: Jalankan suite penuh**
  Run: `RUN_DB_TESTS "tests -p no:warnings"` → seluruh suite lulus.

- [ ] **Step 4: Commit**
  `fix(rbac): Collection Results & Stats Collection hanya Admin dan login yang di-assign Collection`

---

## Catatan untuk eksekusi

- Tidak ada perubahan worker selain sinkron core (Task 1, 2).
- Tidak ada push/PR/deploy/perubahan `.env` dalam rencana ini.
- Menu **Collection Results** diselaraskan dengan aturan Stats di Task 7 (keputusan user).
