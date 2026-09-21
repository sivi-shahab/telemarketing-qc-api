# Merge `4-service-telemarketing-qc-system` → repo production (21 September 2026)

Status: **MERGE SELESAI DI BRANCH `merge/4service-21092026` (4 repo) — BELUM DI-DEPLOY.**
Semua kelompok disetujui user 21 Sep 2026 (§6). Deploy ke production menunggu konfirmasi
terpisah; langkahnya di §7, hasil verifikasi di §8.

Repo target (production): `telemarketing-qc-api`, `telemarketing-qc-core`,
`telemarketing-qc-worker`, `telemarketing-qc-dashboard`.

---

## 1. Ruang lingkup

| | Nilai |
|---|---|
| Repo sumber (A) | `4-service-telemarketing-qc-system` (`github.com/ai-engineer-jaskapital/...`), branch `main` |
| Port terakhir ke production | A@`1ccd74c` (14 Sep 2026) — dikerjakan 15 Sep (api PR #1, worker PR #1, dashboard PR #2; lihat `docs_api_15092026.md`, `telemarketing-qc-core/docs_15092026.md`) |
| Delta yang di-merge sekarang | A `1ccd74c..aec99ce` — **28 commit, 15–21 Sep 2026**, 68 file kode (+4112/−1337) + 12 file docs |
| HEAD production saat analisis | api `3d3930e`, core `18d3d81`, worker `f0186e4`, dashboard `1ff285a` — semua working tree bersih |
| DB production | schema `dashboard`, alembic **`0053`**, `results` = 261 baris, `tms_cashline`/`ascend_custp` kosong |

A dan production **bukan versi lama vs baru** — keduanya garis pengembangan terpisah.
Production punya fitur yang tidak ada di A (DWH API untuk reference data, boto3
multi-bucket, proxy App C, Collection, load-last-date, dsb.). Karena itu merge dilakukan
**aditif per file (3-way)**, tidak pernah menimpa file production dengan file A.

### Daftar commit A yang masuk ruang lingkup

```
f75c1c2 feat(qc): kolom AI Processing Time + rapikan kolom SCOREBOMB
ec28dac fix(qc): exact-match nomor telepon, wording FE Data Leads, TMS campaign status log
d340b1a fix(qc): Hierarki Failure Rate hitung 1 risk base tertinggi per tiket
ea66a6b perf(stats): index hot columns, batch credit-limit lookup, cache scoped snapshots
69a6f5b perf: Fase 1 improvement.md — quick wins load time
6822339 perf: Fase 2 improvement.md — cache stats lanjutan + polling hemat
3388a2c perf: Fase 3 improvement.md — index & dedup query
8eebe08 perf(dashboard): Fase 5 improvement.md — frontend
3e606b4 fix(qc): hapus kode error code di baris tiket tabel Failure Reason per Hierarki
31a3746 fix(compliance): validasi key wajib Task B/C/D pada evaluate()
870c1f5 fix(stats): selaraskan Failure Reason & tambal 2 gap error code (Ultima Shield, B29)
13c4e64 fix(error-codes): sinkronkan error_reasons.json dengan B27/B28/B29
521fe84 fix(sc_cl_2): SC_CL_2 (nama on-air) dinilai LLM sepenuhnya
e6f2317 feat(scorecard): SC_CL_43 — premi MUS tidak dapat dikembalikan
e98d2c9 feat(qc): validasi PDF + pilih recording utama untuk tiket multi-rekaman
81085fa fix(qc): recording_types ikut recording_tags
27c0270 feat(qc): tiket tanpa TMS/Ascend tidak dinilai — langsung PENDING
2e026dd fix(qc): fix_speaker_roles kenali pembuka panggilan susulan
f672425 feat(qc): aktifkan penilaian PARALEL untuk tiket multi-rekaman
d783386 feat(results): menu Export Agregat per fase percakapan
00d5150 feat(qc): alasan SC_CL_2 untuk B29 menyebut nama on-air dan nama yang disebut
4cf9db5 feat(rbac): Export Agregat untuk SPQ Head dan Team Leader QC (migrasi 0059)
3acfc1f feat(stats): kartu "Total Failure (Risk Level)"
aec99ce perf(qc): panggilan LLM penilaian PARALEL berjalan bersamaan
(+ 4 commit docs: 7f364ca, f231b53, 4a24ec6, abaae4b, fd1f1df, b9bfd0f)
```

---

## 2. Proses merge

### 2.1 Pemetaan path

| A | Production |
|---|---|
| `api/` | `telemarketing-qc-api/api/` |
| `core/{compliance,db,prompt}` (impor `core.x`) | **tiga salinan identik**: `telemarketing-qc-api/core/`, `telemarketing-qc-worker/core/` (impor datar `from db import crud`), `telemarketing-qc-core/src/qc_core/` (impor `qc_core.`) |
| `core/db/migrations/versions/` | `telemarketing-qc-api/db/migrations/versions/` |
| `core/config/base.py` | tidak ada — setting worker ke `telemarketing-qc-worker/worker/config.py` |
| `worker/` | `telemarketing-qc-worker/worker/` |
| `dashboard/` | `telemarketing-qc-dashboard/` |

Kondisi awal: api/core dan worker/core byte-identik; qc_core identik setelah prefiks
`qc_core.` dibuang. Belum satu pun perubahan delta ada di production.

### 2.2 Metode

1. Per file: `git merge-file` dengan **base = A@1ccd74c**, **ours = production**, **theirs = A@aec99ce**
   (impor dinormalisasi dulu agar diff tidak dipenuhi prefiks).
2. Setiap konflik diselesaikan manual. Setiap hasil *auto-merge* juga dibaca ulang — ditemukan
   3 kasus di mana merge-file **tidak melaporkan konflik tapi hasilnya salah** (§4).
3. Kandidat diuji di salinan scratch (tidak di folder production):
   * qc-core: **309 passed, 5 skipped** (baseline 257)
   * api: **276 passed, 140 skipped** (sama dengan baseline)
   * worker: tes A terhadap core ter-patch 93 passed, 1 failed (kegagalan yang sama sudah ada di A —
     `test_evaluate_direct_json` mengharap temperature 0.0); smoke run end-to-end dengan DB/S3/LLM/DWH palsu:
     1 PDF → 1 panggilan LLM; 5 PDF → 4 dibuang, 1 panggilan; 4 PDF → 1 dibuang, 3 panggilan paralel;
     tanpa data DWH → 0 panggilan, PENDING.
   * dashboard: `vite build` OK, `npm test` **51/51**, `nginx -t` OK untuk kandidat `nginx.conf`.
4. Penerapan (tahap 2) dikerjakan di **branch `merge/4service-21092026` lewat git worktree**, bukan di
   folder repo utama — folder utama adalah konteks build production (`docker compose up -d --build`
   ikut membawa perubahan yang belum di-commit).

### 2.3 Migrasi — penomoran bentrok

| | 0052 | 0053 |
|---|---|---|
| Production | `perm_tl_qc_upload_sales_database` | `result_current_stage` |
| A | `result_current_stage` (isi sama dengan prod 0053) | `tms_missing_export_columns` |

Migrasi A 0053–0059 **tidak boleh** dipakai dengan nomor aslinya. Evaluasi per migrasi:

| A | Isi | Keputusan usulan |
|---|---|---|
| 0053, 0054 | Tambah kolom `tms_cashline`, tabel status campaign TMS | **Tidak di-port** — tabel lokal kosong, production pakai DWH API |
| 0055 | 2 index | **Tidak di-port** — duplikat index `idx_*` yang sudah ada; A sendiri men-drop-nya di 0057 |
| 0056 | `stats_snapshots.scope_key` + unique (snapshot_date, scope_key) | → **prod 0054**, hanya bila Kelompok C disetujui |
| 0057 | Drop 4 index duplikat | → **prod 0055**, dipangkas ke 2 index + `IF EXISTS` |
| 0058 | Expression index (`results`) | → **prod 0056**, `IF NOT EXISTS` |
| 0059 | Grant `results.export.verification` ke `spq_head`, `team_leader_qc` | → **prod 0057**, hanya bila Kelompok F disetujui |

Tabel production kecil (261 baris `results`, 10 baris `stats_snapshots`) — `CREATE INDEX`
non-concurrent tidak menimbulkan lock yang berarti.

---

## 3. Hasil analisis per kelompok

Kelas: **a** = tanpa perubahan perilaku · **b** = perubahan logic/tampilan, **butuh konfirmasi** ·
**c** = tidak di-port · **d** = butuh skema/env/infra.

### Kelompok A — Aman, tanpa perubahan logic (a)

| Perubahan | Repo | Commit |
|---|---|---|
| Tes core baru/ter-update (10 file, 5 baru) | core, api, worker | beberapa |
| Celery `worker_prefetch_multiplier=1` | worker | 69a6f5b |
| GZip response API (min 1000 B) — JSON stats/list mengecil ±80–90% | api | 69a6f5b |
| nginx: `gzip_vary`, `gzip_min_length`, svg gzip (header cache production **dipertahankan**) | dashboard | 69a6f5b |
| Polling Stats berhenti saat tab tersembunyi | dashboard | 6822339 |
| EvaluationView lazy-load, vendor chunk | dashboard | 8eebe08 |
| SlaCountdown satu timer per baris | dashboard | 8eebe08 |
| Katalog error code & daftar campaign di-cache 5 menit di browser | dashboard | 8eebe08 |
| Komentar index di models | core | — |

Catatan: `SlaCountdown` dari A juga membawa perubahan tampilan: tiket Pending yang **tidak**
menunggu dokumen menampilkan "—" alih-alih hitung mundur H+2. Ini kelas **b** (masuk Kelompok G).

### Kelompok B — Definisi angka Statistik berubah (b)

| Perubahan | Dampak ke user | Commit |
|---|---|---|
| Hierarki Failure Rate menghitung **1 risk base tertinggi per tiket** (bukan semua pelanggaran) | High/Medium/Low, Total Failure dan Failure Rate di view global & AM/TL **turun**; tidak lagi bisa >100% | d340b1a |
| Failure Reason: kolom "Failure" = jumlah kemunculan (bukan tiket distinct); batas top-3 alasan dihapus | angka dan jumlah baris berubah | 870c1f5 |
| Baris tiket di tabel Failure Reason per Hierarki tanpa "— SC_CL_x" | kosmetik | 3e606b4 |
| Kartu "Total Failure" → "Total Failure (Risk Level)" + persentase | label | 3acfc1f |
| Signature cache stats naik ke `"v25"` (wajib — kedua garis sama-sama di `"v24"` dengan arti berbeda) | cache lama otomatis dibuang | — |

### Kelompok C — Cache stats untuk role ber-scope (b + d)

`/stats` untuk AM/TL/Agent/QC, Failure Reason, timeseries AI Status disimpan di `stats_snapshots`
per `scope_key` (butuh migrasi prod 0054). Menghemat beban, tetapi **risiko angka basi**:
signature tidak ikut berubah saat Manual Status, upload/OCR dokumen, jam SLA H+2, fallback agent
DWH, atau pergantian hari — angka tetap lama sampai SPQ Head menekan Refresh. Saat ini semua
view tersebut selalu live.
Bug di A yang sudah diperbaiki di kandidat: `None` (tanpa batasan) dan `[]` (tanpa akses) jatuh
ke kunci cache yang sama → user tanpa scope bisa melihat data seluruh organisasi.
**Usulan: tunda.**

### Kelompok D — Penilaian scorecard berubah (b)

| Perubahan | Dampak | Syarat | Commit |
|---|---|---|---|
| SC_CL_2 / B29 nama on-air dinilai LLM (field `agent_name_said`); `apply_agent_name_verdict` dihapus; alasan B29 menyebut kedua nama | vonis SC_CL_2 berubah | **prompt v82 + KB v38 harus di-update di DB production** — kalau tidak, aturan nama on-air tidak ditegakkan sama sekali. Core + worker wajib deploy bersamaan (worker production mengimpor fungsi yang dihapus) | 521fe84, 00d5150, 870c1f5 |
| SC_CL_43 — premi MUS tidak dapat dikembalikan; bobot MUS 35.5 → 36.75 | skor dihitung saat dibaca → tiket lama ikut berubah; vonis hanya bisa berbalik FAIL→PASS | scorecard/KB/prompt campaign production harus memuat SC_CL_43; kalau tidak, setiap tiket MUS dapat 1.25 poin gratis | e6f2317 |
| "Penjelasan Mega Ultima Shield" memicu B10 | tabel error, Risk Base, Failure Rate berubah (termasuk tiket historis) | — | 870c1f5 |
| `error_reasons.json` + B27/B28/B29 | muncul di pemilih error code | — | 13c4e64 |
| `fix_speaker_roles` mengenali pembuka panggilan susulan | transkrip yang dilihat LLM berubah untuk semua tiket | — | 2e026dd |
| Regex nama menerima "Ibu/Pak" + stopword "dari" | kepemilikan panggilan | — | 521fe84 |
| `parse_cust_name` menangani ",S.KEP" dan "_PA"; `mus_cc` di blok interest | reference data ke LLM | pasangkan dengan prompt v82 | ec28dac |
| Ringkasan XLSX per tiket: bobot 100/36.75/13.25 + passing grade terhitung | angka di file unduhan (sekaligus memperbaiki bug production yang masih memakai 108.75/41.25) | 36.75 hanya benar bila SC_CL_43 ikut; jika tidak, 35.5 | e6f2317 |

### Kelompok E — Pipeline multi-rekaman **diganti** (b + d)

Ini **penggantian**, bukan penambahan. Production saat ini (port 1ccd74c):
filter Double Agent → klasifikasi tiap rekaman oleh LLM → gate SLA 7 hari → PARALEL 3 thread.
Versi A:

| Perubahan | Dampak | Commit |
|---|---|---|
| Hapus filter Double Agent | panggilan oleh agent lain **ikut dinilai lagi** | ec28dac |
| Hapus klasifikasi LLM per rekaman; stage `klasifikasi_llm` → `cek_nama_agent` | hemat 1 panggilan LLM per tiket; api + worker harus deploy bersamaan (tabel progres) | ec28dac |
| Validasi PDF regex (Legal Statement) + rekaman utama = yang tertua | rekaman lain dibuang; regex dikalibrasi hanya dengan 10 PDF, bisa membuang rekaman utama yang sebenarnya | e98d2c9, 81085fa |
| PARALEL untuk >1 rekaman valid, tanpa gate SLA; berjalan bersamaan maks 4/tiket | beban Azure naik: worst case 8 × 4 = 32 panggilan serentak (risiko 429). Usulan maks 3 | f672425, aec99ce |
| Tiket tanpa data TMS/Ascend → langsung PENDING tanpa panggilan LLM | **Risiko:** saat DWH down, `fetch_bundle` mengembalikan bundle kosong (di-cache 300 dtk) → tiket jadi PENDING tanpa dinilai dan tidak diulang otomatis. Harus diperbaiki dulu (gagal/tidak cache saat error jaringan/5xx) | 27c0270 |
| `evaluate(required_keys)` — retry bila key Task B/C/D hilang | lebih tahan terhadap output LLM tidak lengkap | 31a3746 |
| Env baru `PARALLEL_RECORDING_EVAL`, `PARALLEL_RECORDING_MAX_WORKERS` | di A saklar ini tidak pernah terbaca oleh setting worker production → sudah ditambahkan field nyata di kandidat | — |

Perbaikan yang sudah dimasukkan ke kandidat: `_resync_critical` dikembalikan (A menghilangkannya →
penalti item kritis rekaman utama tetap berlaku walau rekaman susulan memperbaikinya);
`build_reference_data` tetap mengembalikan baris DWH mentah (versi A membaca tabel lokal yang kosong →
**semua** tiket akan PENDING).
E2E suite (`e2e/jalankan.sh`) perlu penyesuaian: `test_klasifikasi_sekali` dan stub LLM tanpa route DWH.

### Kelompok F — Export Agregat per fase percakapan + RBAC (b + d)

| Perubahan | Commit |
|---|---|
| `category=fase:<phase>`, endpoint baru `GET /export_categories`, dropdown dua grup | d783386 |
| Migrasi (prod 0057): `results.export.verification` untuk `spq_head` & `team_leader_qc` — akses langsung berubah tanpa deploy dashboard | 4cf9db5 |

Catatan: role `spq_head`/`team_leader_qc` **dipakai juga oleh login Collection**
(`api/permissions.py:223`) → user Collection ikut mendapat Export Agregat kecuali capability
ditambahkan ke `COLLECTION_REMOVED_PERMISSIONS`. Export juga tidak dibatasi isolasi tiket QC Support.
Perlu cek route nginx host untuk `/export_categories`.

### Kelompok G — Perubahan tampilan dashboard (b)

| Perubahan | Commit |
|---|---|
| Kolom "AI Processing Time" (layout Demo; data `processing_sec` sudah ada) | f75c1c2 |
| Alasan klasifikasi rekaman sebagai catatan abu-abu, bukan tooltip | f75c1c2 |
| "Ticket ID" → "Data Leads" di modal, Evaluation, Assign Ticket, Reprocess, Stats (header/filter Results tetap "ID" → istilah campur) | ec28dac |
| Teks ambang similarity (telepon & rekening exact, email per bagian) | ec28dac |
| Stats: subjudul KPI & hint Sales dihapus, kolom rata tengah | ec28dac |
| SlaCountdown "—" untuk Pending yang tidak menunggu dokumen | 8eebe08 (dari A 3 Sep) |

### Kelompok H — Infrastruktur API (d)

| Perubahan | Dampak | Usulan |
|---|---|---|
| gunicorn 2 UvicornWorker, timeout 300, dependency `gunicorn` | memori 2×; cache in-process terbelah — setelah simpan Manage Role, proses lain bisa melayani permission lama ≤10 dtk; panggilan DWH/App C saat cache dingin bisa 2× | konfirmasi |
| Pool DB 10+20 → 5+5 | tidak perlu (DWH max_connections 1000, terpakai ±117) | **tolak**, pertahankan 10+20 |

### Tidak di-port (c)

| Item | Alasan |
|---|---|
| `package.json`: hapus `pdfjs-dist` | production memakainya (`PdfViewer.vue`, `TranscriptDetailView.vue`, `utils/pdfRender.js`) — `npm ci` di Dockerfile akan gagal |
| Header cache `nginx.conf` dari A | hasil merge gagal `nginx -t` (location duplikat) dan membuang blok `.mjs` untuk worker pdf.js; production sudah lebih ketat |
| `TranscriptsView` | production memakai implementasi lain (App C tickets-daily) |
| list_results N+1 / dedup doc-type (69a6f5b, 3388a2c) | production sudah punya versinya sendiri (api PR #10–#12) |
| `reference_data`: `mega_cashline` → key `campaign` | baris DWH tidak punya key `campaign` (0/261) → reference jadi null; tetap `jenis-kartu-yang-dikehendaki` |
| Kolom `TmsCashline` +34, batch helper tms, `get_credit_limits` batch | tabel lokal kosong di production |
| `scripts/backfill_tms_campaign.py`, `load_reference_csv.py` | hanya mengisi `tms_cashline` lokal |
| `config/base.py` | production memakai `core_config.py` / `worker/config.py` |
| Migrasi A 0053, 0054, 0055 | lihat §2.3 |

---

## 4. Jebakan yang ditemukan saat merge

1. **Worker crash saat import** bila core di-deploy tanpa worker: `apply_agent_name_verdict` dihapus di A
   tetapi diimpor `process_transcript.py:45`.
2. **Cache stats diam-diam basi**: kedua garis di signature `"v24"` → merge-file tidak konflik. Dinaikkan ke `"v25"`.
3. **NameError tersembunyi**: merge-file meng-auto-merge dua baris `credit_limits` di `_missing_docs_map`
   yang definisinya ada di hunk konflik. Dikembalikan ke `get_credit_limit(cid, db)` milik production.
4. **`aiProcessingTime(item)`** ter-merge tanpa konflik di `ResultsView`, padahal loop production memakai `group`.
5. **`_resync_critical` hilang** tanpa konflik di worker.
6. **Saklar PARALEL tidak bisa dimatikan** — `getattr(settings, ..., True)` pada setting yang tidak punya field-nya.
7. **Bug kunci cache scope** `None` vs `[]` (Kelompok C).

## 5. Temuan di luar delta (tidak diubah)

* `_missing_docs_map` hanya memuat evaluasi tiket ber-band bila pemanggil tidak mengopernya
  (`stats_aggregate.py:2990`); monolit memuat semua (aturan waiver dokumen 3 Sep).
* Docstring `tests/test_hierarchy_failure_rate.py` masih menyebut rasio >100% wajar.

---

## 6. Keputusan (dikonfirmasi user, 21 September 2026)

| Kelompok | Keputusan |
|---|---|
| A — aman | diterapkan |
| B — definisi angka Stats | **diterapkan** |
| C — cache stats ber-scope | **diterapkan** ("sedang tidak digunakan oleh users") — termasuk perbaikan bug kunci `None`/`[]` |
| D — penilaian scorecard | **diterapkan**; campaign Cashline production WAJIB di-update saat deploy (§7) |
| E — pipeline multi-rekaman | **diterapkan**, dengan perbaikan DWH (§8.2) dan maks 3 panggilan paralel per tiket |
| F — Export Agregat fase + RBAC | **diterapkan**; login Collection **ikut** mendapat Export Agregat (tidak ditambahkan ke `COLLECTION_REMOVED_PERMISSIONS`) |
| G — tampilan dashboard | **diterapkan** |
| H — gunicorn 2 worker | **diterapkan**; pool DB tetap 10+20 (usulan 5+5 dari A ditolak) |

## 7. Langkah deploy (BELUM dijalankan — butuh konfirmasi)

1. Merge PR keempat repo ke `main`, lalu `git pull` di folder production. Cek `git status` bersih di
   api/worker/core (image dibangun dari folder, termasuk perubahan yang belum di-commit).
2. Tag image yang sedang berjalan untuk rollback:
   `docker tag local/qc-api:latest local/qc-api:pre-merge-4service` (sama untuk `qc-worker`, `qc-dashboard`).
3. **Update campaign Cashline di DB production** (schema `dashboard`) — syarat Kelompok D:
   prompt v82 (`agent_name_said`, blok AGENT REFERENCE DATA), KB v38 (KB_CL_2, KB_CL_14),
   scorecard dengan SC_CL_43. Sumber: `4-service-telemarketing-qc-system/docs/prompt_cashline_mus_v82.txt`,
   `cashline_kb_v38.txt`, `cashline_scorecard_v31.txt`. Bandingkan dulu dengan isi DB saat ini
   (bisa saja sudah diedit lewat UI setelah v79) — pembacaan DB production dari sesi ini ditolak
   classifier izin, jadi perbandingan ini belum dilakukan.
4. `docker compose up -d --build` **api dan worker bersamaan** (nama stage `klasifikasi_llm` →
   `cek_nama_agent`; worker lama mengimpor fungsi yang dihapus). Container api menjalankan
   `alembic upgrade head` → 0054–0057. `pip install gunicorn` butuh akses jaringan saat build.
5. Dashboard: `docker compose up -d --build` di `telemarketing-qc-dashboard`.
6. Env opsional worker: `PARALLEL_RECORDING_EVAL` (default `true`), `PARALLEL_RECORDING_MAX_WORKERS`
   (default `3`), `DWH_API_FAIL_TTL_SEC` (default `60`).
7. Setelah deploy: SPQ Head tekan Refresh di Stats (signature `v25` membuang cache lama otomatis);
   cek satu tiket multi-rekaman dan satu tiket tunggal.
8. Rollback: jalankan image `pre-merge-4service`, lalu `alembic downgrade 0053`
   (0057 → 0054 punya downgrade; 0055 membuat ulang index yang di-drop). Downgrade belum diuji —
   uji di stack e2e sebelum dijadikan jalur rollback.

## 8. Hasil merge

### 8.1 Branch & isi

Branch `merge/4service-21092026` di keempat repo (dikerjakan di git worktree, folder production
tidak disentuh):

| Repo | Isi |
|---|---|
| telemarketing-qc-core | `src/qc_core`: 11 modul ter-merge + `recording_validation.py` baru; `services/data_dwh.py` (§8.2); 6 tes baru + 5 tes ter-update |
| telemarketing-qc-api | `core/` (salinan identik qc_core, impor datar); `api/main.py` (GZip), `api/Dockerfile` + `requirements.txt` (gunicorn), `api/permissions.py`, `api/routers/stats.py` (cache ber-scope, `/export_categories`, `fase:<phase>`, XLSX 100/36.75/13.25); migrasi 0054–0057; `tests/test_progress_table.py`; e2e (§8.3); dokumen ini |
| telemarketing-qc-worker | `core/` (salinan identik); `worker/tasks/process_transcript.py`, `worker/celery_app.py`, `worker/config.py` (`parallel_recording_eval`, `parallel_recording_max_workers=3`) |
| telemarketing-qc-dashboard | 13 file + `SlaCountdown.vue`; `package.json`/lock dan header cache nginx production **dipertahankan** |

Tiga salinan core diverifikasi identik: api/core = worker/core (byte), qc_core = api/core setelah
prefiks `qc_core.` dibuang (kecuali `compliance/documents.py` — hack `sys.path` vendored yang memang
dipertahankan).

### 8.2 Perubahan tambahan di luar A

* **`services/data_dwh.fetch_bundle_checked()`** — membedakan "DWH menjawab: data tidak ada" (404)
  dari "DWH tidak bisa dihubungi" (network/timeout/HTTP non-404/non-JSON). Kegagalan tidak lagi
  di-cache 300 dtk sebagai data kosong; hanya diingat 60 dtk (`DWH_API_FAIL_TTL_SEC`).
  `fetch_bundle()` tetap berperilaku sama untuk pemanggil lain.
* **Worker**: gerbang PENDING memanggil `fetch_bundle_checked`; bila DWH tidak bisa dihubungi, tiket
  di-set `failed` dengan pesan "DWH API tidak dapat dihubungi … reprocess tiket setelah DWH pulih",
  bukan PENDING tanpa dinilai.
* `_resync_critical` dikembalikan di mode PARALEL; saklar PARALEL dijadikan field setting sungguhan.
* Kunci cache stats ber-scope: `None` → `"*"`, dibedakan dari `[]`.
* Signature cache stats `"v25"`.

### 8.3 Verifikasi

| Uji | Hasil |
|---|---|
| qc-core `pytest` (image qc-api, `pip install ".[test]"`) | **313 passed, 5 skipped** (sebelum merge 257) |
| api `pytest` (`PYTHONPATH=core:.`, cwd di luar `/app`) | **276 passed, 140 skipped** (sama dengan sebelum merge) |
| Smoke worker (DB/S3/LLM/DWH palsu, PDF asli) | 1 PDF → 1 panggilan; 5 PDF → 4 dibuang, 1 panggilan; 4 PDF → 1 dibuang, 3 panggilan bersamaan; data acuan kosong → PENDING, 0 panggilan; **DWH down → `failed`, 0 panggilan** |
| Dashboard | `vite build` OK, `npm test` **51/51**, `nginx -t` OK |
| E2E `e2e/jalankan.sh` (stack terisolasi, 4 repo dari branch merge) | **34 passed** |
| Smoke API di stack e2e | `/export_categories`, `/stats`, `/stats/my_overview`, `/stats/failure_reasons(_hierarchy)`, `/stats/ai_status_timeseries` → 200; `stats_snapshots.scope_key` terisi; `spq_head`/`team_leader_qc` memegang `results.export.verification`; gunicorn 2 worker berjalan |

E2E pertama gagal (2 failed, 17 error) — semuanya karena e2e belum mengikuti perilaku baru, bukan
bug kode: stub LLM tidak mengirim `cashline_data_extraction`/`card_holder_extraction` (kini wajib
lewat `required_keys` bila data acuan ada — prompt production v79 dan v82 sama-sama memintanya),
stub tidak punya route GET DWH, kepala alembic kini 0057, dan skor maksimal kini 136,75
(SC_CL_43). Keempatnya diperbarui di `e2e/`.

Catatan: grup "Fase Percakapan" di Export Agregat diambil dari `conversation_phases` di KB
campaign; di e2e daftarnya kosong karena KB stub minimal.

### 8.4 Yang belum / tidak dikerjakan

* Deploy ke production (§7) dan update campaign Cashline di DB.
* Dokumen `docs/` milik A (API_REFERENCE, ERROR_CODE_CATALOG, CAMPAIGN_SCORING, dll.) tidak disalin
  utuh — isinya menggambarkan arsitektur A (tms_cashline lokal, dsb.).
* Temuan di luar delta (§5) dibiarkan.
