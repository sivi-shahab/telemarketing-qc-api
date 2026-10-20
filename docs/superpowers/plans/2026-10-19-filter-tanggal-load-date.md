# Filter Tanggal Results & Stats pakai `load_date` App C — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter tanggal dan grafik per hari di Results & Stats memakai `load_date` App C (revisi 20 Okt: satu tiket = satu tanggal = `load_date` terakhir, dipakai untuk filter, grafik, tanggal default, Delete All, Reprocess), dengan aturan lama sebagai cadangan.

**Architecture:** Tabel per-tiket baru `ticket_load_dates` diisi task beat worker dari App C `/tickets-daily` (+ backfill sekali jalan). `crud` (SQL, Results) dan `stats_aggregate` (Python, Stats) membaca tabel itu lewat helper bersama; tiket tanpa baris App C jatuh ke aturan lama. Batas H+2/Risk Base tetap Tanggal Agree.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Alembic, Celery beat, PostgreSQL (schema `dashboard`), Vue 3.

**Spec:** `docs/superpowers/specs/2026-10-19-filter-tanggal-load-date-design.md`

## Global Constraints

- Branch: `feat/filter-load-date` di api (sudah ada; merge `main` dulu), worker, core, dashboard — dibuat dari `main`. PR `fix/results-vonis-per-tiket` (core #37, api #59, worker #42) sudah merge 20 Okt.
- Core vendored: setiap perubahan `core/` di api disalin identik ke `telemarketing-qc-worker/core/` dan ke `telemarketing-qc-core/src/qc_core/` (impor disesuaikan bila beda).
- Jangan sentuh `telemarketing-qc-system` (monolit beku) dan `/data/app_scheduler`.
- Migration baru: `db/migrations/versions/0069_ticket_load_dates.py`, `down_revision = "0068"`.
- Snapshot Stats: `version = "v31"` di `crud` (blok komentar versi di atas `version = "v30"`), alasan: tanggal filter/grafik pindah ke load_date tanpa data baru.
- `_submit_time_map`, `_doc_sla_expired`, `_submit_agent_map`, `crud.tms_submit_time_map` **tidak diubah**.
- Test dijalankan di image qc-api (lihat memori "Run python tests in the qc-api image"): `pip install -q pytest`, `PYTHONPATH=/tmp/w/core:/tmp/w`, cwd di luar `/app`. Selanjutnya disebut **RUN-API** / **RUN-WORKER**:
  ```bash
  docker run --rm -v /data/scorecard_v2/<repo>:/src:ro --network host --env-file <(docker exec telemarketing-qc-api-api-1 env | grep -E '^(POSTGRES_|TMS_API_)') -w /tmp \
    "$(docker inspect -f '{{.Config.Image}}' telemarketing-qc-api-api-1)" sh -lc \
    'mkdir -p /tmp/w && cp -r /src/. /tmp/w/ && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q /tmp/w/tests/<file>'
  ```
  Fixture `db` membuka transaksi yang selalu di-rollback, jadi aman terhadap DB prod; tabel `ticket_load_dates` harus sudah ada di DB yang dipakai test → test Task 1–4 memakai DB test terisolasi (`qc-test-pg`) atau jalankan migration di DB test dulu. **Jangan** menjalankan `alembic upgrade` ke DB prod sebelum Task 8.

## Review Focus

1. Tiket tanpa baris App C (Collection, upload manual, Megapay PDF lama) harus tetap tampil di tanggal lamanya (Agree → generated_at → upload WIB) — dipin di Task 2 & 3.
2. App C mati/timeout saat sync: tabel tidak boleh terhapus/terkosongkan; task log error dan putaran berikut mencoba lagi — dipin di Task 5.
3. `id` App C vs prefix nama file berbeda spasi/kapital → tiket tidak ketemu dan diam-diam jatuh ke cadangan — normalisasi `strip()` di kedua sisi (bukan casefold: ID App C case-sensitive) — dipin di Task 1.
4. Vonis PASS/FAIL/PENDING tidak boleh bergeser karena tanggal pindah (H+2 tetap Agree) — dipin di Task 3.
5. Delete All / Reprocess 12–17 tidak boleh menyentuh tiket yang load_date terakhirnya di luar rentang (mis. load 14/16/19) — dipin di Task 4.

---

### Task 1: Tabel `ticket_load_dates` + akses crud

**Files:**
- Create: `db/migrations/versions/0069_ticket_load_dates.py`
- Modify: `core/db/models.py` (kelas baru setelah `QcAssignmentEvent`)
- Modify: `core/db/crud.py` (dua fungsi baru, dekat `cashline_agent_index`)
- Test: `tests/test_ticket_load_dates.py`

**Interfaces:**
- Produces:
  - model `TicketLoadDate` (`__tablename__ = "ticket_load_dates"`; kolom `ticket_id String(100)` PK, `load_date Date` PK, `campaign String(100)` nullable, `synced_at DateTime server_default=func.now()`; index `ix_ticket_load_dates_load_date` pada `load_date`).
  - `crud.upsert_ticket_load_dates(db, rows: Iterable[tuple[str, date, str | None]]) -> int` — `INSERT … ON CONFLICT (ticket_id, load_date) DO UPDATE SET synced_at = now(), campaign = EXCLUDED.campaign`; `ticket_id` di-`strip()`, baris dengan ticket_id kosong dibuang; mengembalikan jumlah baris yang dikirim; tidak commit (pemanggil yang commit).
  - `crud.load_dates_by_ticket(db, ticket_ids: Iterable[str]) -> dict[str, list[date]]` — key = ticket_id ter-strip, value urut naik; tiket tanpa baris tidak muncul; input kosong → `{}` tanpa query.

- [ ] **Step 1: Write failing tests** — `test_upsert_lalu_baca_urut_naik` (upsert `("ZZLD1", 2026-10-15)`, `("ZZLD1", 2026-10-10)` → `{"ZZLD1": [date(2026,10,10), date(2026,10,15)]}`), `test_upsert_idempoten` (dua kali baris sama → satu baris), `test_ticket_id_di_strip` (upsert `" ZZLD2 "`, baca `["ZZLD2"]` → ketemu), `test_tanpa_baris_tidak_muncul`, `test_input_kosong_tanpa_query` (`load_dates_by_ticket(db, []) == {}`).
- [ ] **Step 2: Run RUN-API `tests/test_ticket_load_dates.py`** — Expected: FAIL (`AttributeError: ... upsert_ticket_load_dates`).
- [ ] **Step 3: Implement** model, migration 0069 (upgrade create table + index; downgrade drop), dan dua fungsi crud. Upsert pakai `sqlalchemy.dialects.postgresql.insert`.
- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(db): tabel ticket_load_dates (load_date App C per tiket)`

### Task 2: Results — filter & tanggal default pakai load_date

**Files:**
- Modify: `core/db/crud.py` — `_series_date_expr` (tetap, jadi cadangan), `list_results`, `latest_result_date`
- Test: `tests/test_results_filter_load_date.py`; perbarui `tests/test_latest_result_date.py` bila ada asersi yang bergantung pada aturan lama untuk tiket ber-App C (tiket test tanpa baris App C tetap lolos — jangan diubah).

**Interfaces:**
- Consumes: `TicketLoadDate` (Task 1).
- Produces:
  - `crud._ticket_date_expr(db)` — SQL: `coalesce((SELECT max(load_date) FROM ticket_load_dates WHERE ticket_id = <cid>), _series_date_expr(db))`, `<cid>` = `func.split_part(Result.source_files[0].astext, "_", 1)` (sama dengan yang dipakai `customer_ids`).
  - `list_results(...)` (signature tetap) — blok `if date_start is not None or date_end is not None` menyaring `_ticket_date_expr(db)` dalam rentang (batas `None` = tak dibatasi di sisi itu). `load_date` lama yang ada di rentang diabaikan bila `load_date` terakhir di luar.
  - `latest_result_date` memakai `func.max(_ticket_date_expr(db))`.
  - `collection_results_query` **tidak** diubah.

- [ ] **Step 1: Write failing tests** (pakai pola `_mk` dari `test_latest_result_date.py`, campaign `ZZ-TEST-LOAD-DATE`, Result dengan `generated_at` jauh dari load_date):
  - `test_satu_load_date_dalam_rentang` — load 2026-10-13, generated 2026-09-01 → lolos filter 12–17.
  - `test_multi_load_terakhir_di_rentang_lolos` — load 10 & 15 Okt → lolos 12–17.
  - `test_multi_load_terakhir_di_luar_tidak_lolos` — load 14, 16, 19 Okt → **tidak** lolos 12–17, lolos 18–19.
  - `test_tanpa_app_c_pakai_aturan_lama` — tanpa baris tld, generated 2026-10-14 → lolos 12–17; generated 2026-10-10 → tidak.
  - `test_batas_inklusif_dan_satu_sisi` — load 12 Okt lolos `[12,17]`, `[12,None]`, `[None,12]`.
  - `test_latest_result_date_pakai_load_terakhir` — load 10 & 18 Okt, generated 2026-10-05 → `date(2026,10,18)`.
- [ ] **Step 2: Run RUN-API both files** — Expected: FAIL.
- [ ] **Step 3: Implement** `_ticket_date_expr`, filter `list_results`, perubahan `latest_result_date`. Perbarui komentar blok filter (sumber kini load_date App C, cadangan aturan lama).
- [ ] **Step 4: Run RUN-API both files + `tests/test_list_results_ticket_ids.py tests/test_list_results_no_n_plus_one.py`** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(results): filter tanggal pakai load_date App C`

### Task 3: Stats — filter, grafik, QC Productivity, snapshot v31

**Files:**
- Modify: `core/compliance/stats_aggregate.py` — helper baru dekat `_submit_date_map`; pemakai di `compute_failure_reasons` (blok `_in_window`), `compute_failure_reasons_hierarchy`, `compute_stats_snapshot`, `compute_ai_status_timeseries` (`_chart_date`), `ticket_chart_dates`
- Modify: `core/db/crud.py` — filter tanggal QC Productivity (blok yang memanggil `ticket_chart_dates`) dan `version = "v31"` + komentar
- Test: `tests/test_stats_load_date.py`

**Interfaces:**
- Consumes: `crud.load_dates_by_ticket` (Task 1).
- Produces:
  - `TicketDates = NamedTuple("TicketDates", [("loads", tuple[date, ...]), ("fallback", date | None)])` dengan method `single() -> date | None` (= `max(loads)` bila ada, else `fallback`) dan `in_window(start: date | None, end: date | None) -> bool` (= `single()` di rentang; `None` → False).
  - `_ticket_dates_map(db, results) -> dict[Result.id, TicketDates]` — `loads` dari `crud.load_dates_by_ticket` via `_customer_id(r.source_files)`; `fallback` = `_submit_date_map(...).get(r.id) or _series_date(r)`.
  - `ticket_date_windows(db, ticket_ids) -> dict[str, TicketDates]` — versi per ticket id (cadangan sama seperti `ticket_chart_dates` lama).
  - `ticket_chart_dates(db, ticket_ids) -> dict[str, date]` — signature tetap, nilainya kini `TicketDates.single()`.
- Aturan pemakaian: semua blok `_in_window` → `td.in_window(date_start, date_end)`; `_chart_date` di timeseries (anchor & bucket) → `td.single()`; QC Productivity menyaring dengan `ticket_date_windows(...)[t].in_window(...)`.

- [ ] **Step 1: Write failing tests:**
  - `test_ticketdates_single_dan_window` — unit murni: `TicketDates((d10, d15), d01).single() == d15`; `.in_window(d12, d17)` True; `TicketDates((), d14).in_window(d12, d17)` True; `TicketDates((d14, d16, d19), None).single() == d19` dan `.in_window(d12, d17)` **False**.
  - `test_failure_reasons_filter_load_terakhir` — tiket done dengan load 15 Okt & submit 10 Okt masuk `compute_failure_reasons(date_start=12 Okt, date_end=17 Okt)`; tiket submit 15 Okt tanpa tld tetap masuk; tiket load 10 Okt saja tidak; tiket load 14 & 19 Okt tidak.
  - `test_timeseries_bucket_load_terakhir` — tiket load 14 & 16 Okt muncul di bucket harian 16 Okt.
  - `test_submit_time_map_tidak_berubah` — tiket punya tld 15 Okt dan submit_time `2026-10-10 11:52:32` → `_submit_time_map` tetap `"2026-10-10 11:52:32"` (H+2 tetap Agree).
  - `test_qc_productivity_filter_load_terakhir` — tiket ter-assign dengan load 10 & 15 Okt dihitung di filter 12–17; load 14 & 19 Okt tidak.
- [ ] **Step 2: Run RUN-API** — Expected: FAIL.
- [ ] **Step 3: Implement** helper & ganti pemakai; perbarui docstring yang menyebut "TMS submit_time" sebagai basis tanggal; naikkan versi snapshot ke `v31` dengan entri komentar.
- [ ] **Step 4: Run RUN-API `tests/test_stats_load_date.py tests/test_hierarchy_failure_rate.py tests/test_stats_snapshot*.py`** (yang ada) — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(stats): tanggal filter & grafik pakai load_date App C (snapshot v31)`

### Task 4: Delete All & Reprocess-by-filter — pin aturan load_date terakhir

**Files:**
- Modify: `api/routers/stats.py` — hanya teks `description` Query dan docstring (logika diwarisi dari `crud.list_results`, Task 2)
- Modify: `api/routers/reprocess.py` — docstring `_plan_for_filtered` saja
- Test: `tests/test_delete_filtered.py` (tambah test)

**Interfaces:**
- Consumes: `crud.list_results` (Task 2). Tidak ada parameter baru: tampilan, Delete All, dan Reprocess memakai aturan yang sama.

- [ ] **Step 1: Write failing test** `test_delete_all_rentang_tidak_ambil_tiket_load_terakhir_di_luar` — tiket A load 14/16/19 Okt, tiket B load 15 Okt; preview Delete All filter 12–17 → hanya B. Tambah kembarannya untuk plan reproses (`test_reprocess_filter_pakai_load_terakhir`) di file test reproses yang sudah ada bila ada, kalau tidak di file yang sama.
- [ ] **Step 2: Run RUN-API** — Expected: PASS bila Task 2 benar (test ini pin, bukan pemicu perubahan). Bila FAIL, perbaiki di Task 2, bukan di router.
- [ ] **Step 3: Implement** perbarui teks `description` Query `date_start`/`date_end` di `api/routers/stats.py` menjadi "Tanggal load App C …"; tulis alasan di docstring masing-masing (penghapusan permanen tidak boleh mengambil tiket yang masih aktif dimuat di luar rentang).
- [ ] **Step 4: Run RUN-API `tests/test_delete_filtered.py`** — Expected: PASS.
- [ ] **Step 5: Commit** — `test(delete,reprocess): pin filter tanggal load_date terakhir`

### Task 5: Sinkronisasi App C → `ticket_load_dates` (core + task worker + backfill)

**Files:**
- Create: `core/services/load_date_sync.py`
- Create: `scripts/backfill_ticket_load_dates.py` (api repo)
- Create (worker repo): `worker/tasks/load_date_sync.py`; Modify `worker/celery_app.py` (`beat_schedule`)
- Test: `tests/test_load_date_sync.py` (api), `tests/test_load_date_sync_task.py` (worker)

**Interfaces:**
- Consumes: `services.tickets_daily.fetch_all(load_date=...)`, `crud.upsert_ticket_load_dates` (Task 1).
- Produces:
  - `load_date_sync.sync_dates(db, dates: Iterable[date]) -> dict[date, int]` — untuk tiap tanggal: `fetch_all(load_date=d.isoformat(), max_pages=200)`, ambil `(item["id"], date.fromisoformat(item["load_date"]), item.get("campaign"))` untuk item dengan `id` & `load_date` terisi, upsert, `db.commit()` per tanggal; `TicketsDailyError` untuk satu tanggal → log & lanjut tanggal berikut (tanggal itu tidak masuk hasil); `truncated=True` → log warning.
  - `load_date_sync.recent_dates(today: date, days_back: int) -> list[date]` — `[today - days_back, …, today]`.
  - Task Celery `worker.tasks.load_date_sync.sync_ticket_load_dates()` — `LOAD_DATE_SYNC_ENABLED` (default `"1"`; `"0"` = no-op), `LOAD_DATE_SYNC_DAYS` (default `3`), hari ini = WIB (`crud.now_wib().date()`).
  - Beat entry `"sync-ticket-load-dates"`: `crontab(minute="5,35")`, `options={"expires": 25 * 60}`.
  - Script `python scripts/backfill_ticket_load_dates.py --from 2026-08-01 [--to YYYY-MM-DD]` (default `--to` = hari ini WIB) — memanggil `sync_dates`, mencetak jumlah per tanggal dan total.

- [ ] **Step 1: Write failing tests** (monkeypatch `tickets_daily.fetch_all`):
  - `test_sync_menyimpan_semua_baris` — dua item untuk 15 Okt → `load_dates_by_ticket` berisi keduanya, hasil `{date(2026,10,15): 2}`.
  - `test_app_c_error_tidak_menghapus` — baris lama ada; `fetch_all` raise `TicketsDailyError` → baris lama tetap, hasil tidak memuat tanggal itu, tanggal lain tetap diproses.
  - `test_item_tanpa_id_dibuang`.
  - `test_recent_dates` — `recent_dates(date(2026,10,19), 3)` → 16..19.
  - worker: `test_task_mati_bila_disabled` (`LOAD_DATE_SYNC_ENABLED=0` → `sync_dates` tidak dipanggil), `test_beat_terdaftar` (`"sync-ticket-load-dates"` ada di `celery_app.beat_schedule`).
- [ ] **Step 2: Run RUN-API & RUN-WORKER** — Expected: FAIL.
- [ ] **Step 3: Implement** modul core, script, task, entri beat (komentar gaya blok "Retry data acuan" di `celery_app.py`).
- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Commit** (api & worker masing-masing) — `feat(sync): sinkron load_date App C ke ticket_load_dates`

### Task 6: Sinkron core vendored ke worker & qc_core

**Files:**
- Modify: `telemarketing-qc-worker/core/db/models.py`, `core/db/crud.py`, `core/compliance/stats_aggregate.py`, `core/services/load_date_sync.py` — identik dengan api.
- Modify: `telemarketing-qc-core/src/qc_core/...` padanannya (+ test yang relevan dari Task 1–3, 5 disalin ke `telemarketing-qc-core/tests/`).

- [ ] **Step 1:** `diff -r` api/core vs worker/core untuk file di atas → hanya perbedaan yang sudah ada sebelum branch ini (bandingkan dengan `git diff main` di kedua repo).
- [ ] **Step 2:** Run suite penuh: RUN-API (`tests/`), RUN-WORKER (`tests/`), core (`pip install ".[test]" && python -m pytest -q`) — Expected: semua PASS (catat test yang sudah gagal sebelum branch, buktikan dengan run di branch dasar).
- [ ] **Step 3: Commit** di worker & core — `chore(core): sinkron filter load_date dari api`

### Task 7: Dashboard — label filter

**Files:**
- Modify: `telemarketing-qc-dashboard/src/views/dashboard/ResultsView.vue` (label `Tanggal` di `.date-range`, ±baris 48)
- Modify: `telemarketing-qc-dashboard/src/views/dashboard/StatsView.vue` (label filter `Dari`/`s/d`, ±baris 43 & 229)

**Interfaces:** tidak ada perubahan API.

- [ ] **Step 1:** Results: label jadi `Tanggal Load App C`; Stats: tambahkan `title="Tanggal tiket dimuat App C (load_date); tiket tanpa data App C memakai Tanggal Agree"` pada kedua grup filter. Kolom "Tanggal Submit" (Tiket Saya) tidak diubah.
- [ ] **Step 2:** `npm run build` di dashboard — Expected: build sukses tanpa error.
- [ ] **Step 3: Commit** — `feat(ui): label filter tanggal load App C`

### Task 8: Verifikasi data nyata, e2e, dan handoff deploy

- [ ] **Step 1:** Di DB test terisolasi (bukan prod): `alembic upgrade head` → 0069; jalankan backfill `--from 2026-10-01`.
- [ ] **Step 2:** E2E: rebuild bundle dashboard, lalu `./jalankan.sh` di `telemarketing-qc-api/e2e` — Expected: lulus.
- [ ] **Step 3:** Verifikasi angka (setelah deploy ke prod oleh user, lewat endpoint HTTP — bukan script): ticket ID unik Results campaign CashLine 12–17 Okt ≤ **330** (330 = aturan lama "salah satu"; catat angka persisnya), berisi 295 tiket daftar; `141248zgZn` (muncul di 19 Okt) dan 5 tiket `071114mH7F 070401utlJ 090803wMdP 100137zGl5 101257aSoz` tidak ada; Stats Failure Rate/hierarki & QC Productivity 12–17 konsisten dengan himpunan itu; total grafik harian = jumlah ticket ID unik tabel (satu tiket satu tanggal). Bandingkan vonis per tiket (AI/Manual status) sebelum vs sesudah → identik.
- [ ] **Step 4:** Tulis catatan deploy di PR: urutan migration 0069 → backfill → image api/worker/dashboard; tag `pre-filter-load-date`; **kube worker 10.158.3.13 harus di-update bersamaan atau task snapshot-nya dimatikan — tanyakan user sebelum deploy**; ikuti memori "Deploy: build cand, diff freeze, smoke, retag" dan cek `git status` sebelum build.
- [ ] **Step 5:** Buka PR (api, worker, core, dashboard). Deploy **tidak** dilakukan tanpa persetujuan eksplisit user.
