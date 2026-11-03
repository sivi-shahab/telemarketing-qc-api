# Perbaikan Memori API (OOM di kube) — 3 November 2026

Branch: `perf/hemat-memori-api` di repo **api**, **core**, dan **worker** (salinan
vendored `core/` ikut diubah supaya ketiganya tetap identik).

## 1. Masalah

API di kube berkali-kali kena *out of memory* walau limitnya 8 GiB. Di server
docker lokal gejalanya juga terlihat: worker gunicorn mencapai puncak **2,8 GB per
proses** dan kena `WORKER TIMEOUT` hampir setiap hari sekitar pukul 15.03 WIB.

Penyebabnya bukan kebocoran memori. Beberapa endpoint memuat hasil evaluasi
(`result_data.result_json`) **semua tiket sekaligus** ke memori Python:

| Endpoint / menu | Fungsi yang memuat semua evaluasi |
|---|---|
| Pending Check, Results dengan filter AI/Manual Status, Transcripts dengan filter AI Status | `ai_status_map` → `crud.result_json_map(semua tiket done)` |
| Statistics (snapshot, Overview TL, timeseries AI Status, QC performance, team agents) | `compute_stats_snapshot`, `compute_scoped_overview`, `compute_ai_status_timeseries`, `compute_qc_performance`, `compute_team_agents` |
| Failure Reason (agregat & hierarki) | `compute_failure_reasons`, `compute_failure_reasons_hierarchy` |
| Export (tiket, kategori verifikasi, fase, nama ibu kandung) | `_iter_export_tickets`, `compute_ticket_export`, `compute_nama_ibu_kandung_rows` |

Ukuran datanya (diukur 3 Nov 2026): 3.976 baris `result_data` dengan total JSON
**±220 MB sebagai teks**. Dari jumlah itu, ±157 MB adalah
`evaluation.scorecard_result`. Isinya didominasi teks per item: `evidence` ±80 MB,
`reason` ±17 MB, `requirement` ±10 MB, dan `dynamic_verification_detail` ±8 MB.
Setelah di-parse menjadi dict Python, ukurannya membengkak beberapa kali lipat.

Ada tiga hal yang memperparahnya:

1. **10 salinan loop yang sama** di `stats_aggregate.py`:
   `db.query(ResultData.result_id, ResultData.result_json).filter(in_(ids)).all()`.
   Loop ini menarik *semua versi* JSON lewat ORM sekaligus, lalu membuang versi lama
   dengan `setdefault`. Loop itu juga tidak memakai cache Redis, sehingga lambat
   (37–45 detik).
2. **`crud.result_json_map`** memang memakai Redis, tetapi memegang teks mentah
   (bytes dari Redis dan string dari Postgres) *bersamaan* dengan hasil parse-nya,
   untuk semua tiket sekaligus.
3. **Python tidak mengembalikan heap ke OS.** Setelah satu request berat, RSS proses
   bertahan di titik tertinggi. Dua request berat yang berjalan bersamaan dalam satu
   proses langsung saling menumpuk.

## 2. Perbaikan

### 2.1 `crud.result_json_map` diproses per batch (poin 3)

`core/db/crud.py`

- Pemilihan baris terbaru per result tidak berubah. Query-nya ringan, hanya `id`.
- Teks JSON diambil per **`RESULT_JSON_BATCH = 200`** baris, dari Redis terlebih
  dahulu lalu dari Postgres untuk yang belum ada di cache. Tiap teks langsung di-parse
  lalu dilepas sebelum batch berikutnya diambil. Puncak memori menjadi hasil parse
  ditambah teks satu batch, bukan teks seluruh tiket.
- Cache Redis tetap menyimpan JSON **utuh** dengan key yang sama (`rj:v1:<id>`).
  Tidak ada perubahan format cache, sehingga tidak perlu flush.

### 2.2 Mode `slim` untuk jalur yang hanya menghitung (pengganti poin 1)

Rencana awal poin 1 adalah menyimpan AI Status per tiket ke tabel. Rencana itu
**tidak** dikerjakan karena AI Status bergantung pada hal yang berubah tanpa ada
penulisan ke tiketnya:

- tenggat H+2 dokumen (berubah hanya karena waktu berjalan);
- banding error code, dokumen yang diunggah, Manual Status beserta approval-nya;
- kekurangan data acuan (DWH).

Nilai tersimpan akan basi tanpa ada pemicu yang jelas, dan bug "angka di layar beda
dengan filter" sudah beberapa kali terjadi di proyek ini. Penggantinya adalah
**`result_json_map(..., slim=True)`**. Mode ini membuang field teks berikut dari
setiap item `evaluation.scorecard_result`:

```
SLIM_SCORECARD_DROP = {"evidence", "reason", "requirement",
                       "point_of_improvement", "dynamic_verification_detail"}
```

Field yang menentukan vonis dan angka (`item_code`, `status`, `tolerable`,
`item_score`, `weight`, `category`, dan sebagainya) tetap ada. Blok lain seperti
`card_holder_verification`, `cashline_data_verification`, `badword_check`, dan
`reference_data` tidak disentuh.

Pemakaian `slim` per fungsi:

| `slim=True` (hanya menghitung) | `slim=False` (teks tampil/diekspor) |
|---|---|
| `ai_status_map` (Pending Check, filter AI Status) | `compute_failure_reasons` |
| `_missing_docs_map` (bila dipanggil tanpa evaluasi) | `compute_failure_reasons_hierarchy` |
| `compute_scoped_overview` | `_iter_export_tickets` |
| `compute_stats_snapshot` | `compute_ticket_export` |
| `compute_ai_status_timeseries` | `compute_nama_ibu_kandung_rows` |
| `compute_qc_performance` | `ai_status_for_result` (1 tiket) |
| `compute_team_agents` | tabel Results per halaman (`list_results`) |

### 2.3 Hanya versi terbaru dan lewat satu helper (poin 2)

`core/compliance/stats_aggregate.py`

Kesepuluh loop pada §1 diganti satu helper, `_latest_eval_map(db, ids, slim=...)`,
yang memanggil `crud.result_json_map`. Efeknya:

- hanya versi **terbaru** per result yang dimuat (aturannya sama dengan sebelumnya:
  `created_at` terbaru);
- lewat cache Redis, sehingga jauh lebih cepat;
- diproses per batch (§2.1) dan memakai `slim` sesuai tabel di §2.2.

Import `ResultData` di `stats_aggregate.py` dihapus karena tidak dipakai lagi.

## 3. Pembuktian

### 3.1 Hasil tidak berubah: uji pembanding atas seluruh data prod

Script read-only dijalankan di container sementara dari image `local/qc-api` dengan
kode branch ini, di dalam satu transaksi `REPEATABLE READ` yang di-rollback. Setiap
fungsi dijalankan dua kali, dengan evaluasi utuh dan dengan evaluasi slim, lalu
keluarannya dibandingkan sebagai JSON. Populasi: **3.913 tiket `done`, 1.563 ticket
ID**.

| Fungsi | Kandidat A (dipakai) | B: tanpa evidence/POI/dyn | C: tanpa reason/req/POI/dyn | D: tanpa POI/dyn |
|---|---|---|---|---|
| ai_status_map | SAMA | SAMA | SAMA | SAMA |
| compute_scoped_overview | SAMA | SAMA | SAMA | SAMA |
| compute_stats_snapshot | SAMA | SAMA | SAMA | SAMA |
| compute_ai_status_timeseries | SAMA | SAMA | SAMA | SAMA |
| compute_qc_performance | SAMA | SAMA | SAMA | SAMA |
| compute_team_agents | SAMA | SAMA | SAMA | SAMA |
| compute_failure_reasons | beda | beda | beda | SAMA |
| compute_failure_reasons_hierarchy | beda | beda | beda | SAMA |

Failure Reason membaca `reason`, `requirement`, dan juga `evidence`. Karena itu
fungsi ini tetap memakai `slim=False`. Kandidat D hanya menghemat ±9 MB untuk
Failure Reason, sehingga tidak sepadan dengan menambah level slim kedua.

> **Aturan ke depan:** jangan menambah field ke `SLIM_SCORECARD_DROP`, dan jangan
> mengubah fungsi baru menjadi `slim=True`, tanpa uji pembanding yang sama. Contoh
> pembacaan field yang tidak kentara: `error_codes.py` memakai *keberadaan*
> `evidence.quote` sebagai syarat.

### 3.2 Memori dan waktu: lama vs baru

Diukur di proses baru per fungsi (`ru_maxrss`), atas data prod yang sama.

| Fungsi (menu) | Lama | Baru |
|---|---|---|
| `ai_status_map` (Pending Check / filter AI Status) | +1.013 MB, 13 dtk | **+403 MB**, 13 dtk |
| `compute_stats_snapshot` (Statistics) | +771 MB, 37 dtk | **+328 MB**, 22 dtk |
| `compute_scoped_overview` (Overview TL) | +740 MB, 45 dtk | **+305 MB**, 26 dtk |
| `compute_failure_reasons` (tetap utuh) | +741 MB, 40 dtk | **+306 MB**, 21 dtk |

Hanya bagian pemuatan evaluasi (3.876 tiket):

| Cara | Kenaikan memori | Waktu |
|---|---|---|
| Lama (loop ORM, semua versi) | 767 MB | 40,6 dtk |
| Baru, utuh, per batch | 573 MB | 2,4 dtk |
| Baru, slim | 377 MB | 2,7 dtk |

Secara kasar, setiap request berat kini memakan **±40–55 %** dari sebelumnya.
Statistics dan Failure Reason juga 40–50 % lebih cepat karena memakai cache Redis.

### 3.3 Test

- API: **822 lulus, 7 dilewati**. Suite dijalankan di atas commit prod (`f955762`)
  ditambah patch ini, karena `main` sudah membawa migrasi 0071 yang belum ada di DB.
- Test baru: `tests/test_result_json_slim.py` (5 test). Isinya: batch kecil tetap
  mengembalikan semua tiket dan tersimpan ke cache; slim hanya membuang field di
  daftar; blok lain dan item non-dict tidak disentuh; cache tetap utuh setelah
  pemanggilan slim; JSON tanpa evaluasi aman.
- Core: 385 lulus, 1 gagal (`test_data_dwh_cashline_ids`). Test ini **juga gagal di
  `main` tanpa patch** (3 gagal bila file itu dijalankan sendiri). Penyebabnya
  bergantung pada env/urutan test dan tidak berkaitan dengan perubahan ini.

### 3.4 Script untuk mengulang uji

Kedua script ada di repo ini. Cara menjalankannya lengkap ada di docstring
masing-masing: worktree dari commit prod, env dari container API, lalu container
sementara dengan kode di-mount. Keduanya hanya membaca.

| Script | Kegunaan |
|---|---|
| `scripts/perf_slim_equal.py` | Uji kesamaan utuh vs slim untuk 8 fungsi × kandidat di `CANDIDATES` (±45 menit). `mem <kandidat>` / `mem old` mengukur pemuatan evaluasi saja. **Wajib** sebelum mengubah `SLIM_SCORECARD_DROP` atau menjadikan fungsi lain `slim=True`. |
| `scripts/perf_peak_memory.py <fungsi>` | Puncak RSS satu fungsi di proses baru. Jalankan dengan worktree lama dan baru untuk membandingkan. |

Uji ulang 3 Nov dari versi repo: `ai_status_map` +404 MB, `mem A_all_text` +378 MB.
Angka ini cocok dengan §3.2.

## 4. Yang tidak berubah

- Tidak ada migrasi DB dan tidak ada perubahan format cache Redis.
- Tidak ada perubahan API atau respons. Tabel Results per halaman, detail tiket,
  dan export tetap menerima JSON utuh.
- Menu Collection Results (`crud.collection_results_query`) tidak diubah. Datanya
  jauh lebih kecil.

## 5. Yang masih perlu dilakukan di kube (konfigurasi, terpisah dari PR ini)

Perbaikan kode ini mengurangi memori per request. Proses tetap tidak mengembalikan
memori ke OS, jadi lakukan juga langkah berikut:

1. Jalankan API dengan gunicorn, bukan CMD bawaan `Dockerfile` (`uvicorn` satu
   proses):
   `gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 2 --timeout 300 --max-requests 200 --max-requests-jitter 50`
   Opsi `--max-requests` membuat worker diganti berkala sehingga RSS kembali ke awal.
2. Tambahkan env `MALLOC_ARENA_MAX=2` untuk mengurangi fragmentasi dari threadpool
   endpoint sync.
3. Resource API: `requests.memory: 2Gi`, `limits.memory: 4Gi` (perhitungannya di §6).
   Sampai PR ini di-deploy di kube, biarkan limit 8Gi.

## 6. Kebutuhan memori per repo setelah perubahan ini

Dasar perhitungan: pemakaian container di server docker pada 3 Nov 2026 (`/proc/<pid>`
VmRSS/VmHWM), ditambah angka per request di §3.2. Data saat itu berisi 3.913 tiket
`done`. Angka "baru" untuk API dan worker-stats adalah **perkiraan**, karena belum
di-deploy. Verifikasi setelah deploy dengan melihat VmHWM per proses.

| Repo / service | Proses | Puncak terukur (kode lama) | Perkiraan puncak (kode baru) | requests | limits |
|---|---|---|---|---|---|
| **api** (gunicorn `-w 2`) | 2 worker + master | 2,8 GB dan 1,8 GB per worker, container 3,0 GiB | ±1,2–1,5 GB per worker, container ±3 GB | **2 Gi** | **4 Gi** |
| **api** (kube, `uvicorn` 1 proses) | 1 proses | tidak diketahui (OOM di 8 Gi) | ±1,5–2 GB | 2 Gi | 4 Gi |
| **worker** — `worker` (celery `--concurrency=8`) | parent + 8 child | 2,2 GiB; child ±300–400 MB (pernah 590–840 MB, 21 Okt) | **tidak berubah**, karena tidak memakai kode Statistics | 3 Gi | 8 Gi |
| **worker** — `worker-stats` (`-Q stats`, concurrency 1) | parent + 1 child | 1,15 GB (child), container ±1,0 GiB | ±0,6–0,7 GB | **768 Mi** | **1,5 Gi** |
| **worker** — `beat` | 1 | 142 MB | tidak berubah | 128 Mi | 256 Mi |
| **worker** — `flower` | 1 | 273 MB | tidak berubah | 128 Mi | 384 Mi |
| **core** | library, tidak jalan sendiri | — | — | — | — |

Cara membaca angka API:

- Basis satu proses API setelah import ±120 MB. Setelah melayani request biasa,
  ukurannya ±1,4 GB karena memori tidak dikembalikan ke OS.
- Satu request berat sebelumnya +740 s/d +1.013 MB, sekarang **+305 s/d +403 MB**.
  Puncak lama 2,8 GB per worker setara dengan ±2–3 request berat yang bertumpuk.
  Dengan pola tumpukan yang sama, puncak baru ±1,2–1,5 GB per worker.
- Mode satu proses `uvicorn` (kube) menanggung semua request bersamaan dalam satu
  proses, jadi puncaknya lebih tinggi daripada satu worker gunicorn. Dengan
  `--max-requests` (§5), proses diganti berkala dan RSS kembali ke basis.
- **Limit 4 Gi** memberi ruang sekitar 2× perkiraan puncak, untuk tumpukan request
  yang lebih banyak dan pertumbuhan data.

**Pertumbuhan data:** memori per request berat naik sebanding dengan jumlah tiket
`done`, yaitu ±0,1 MB per tiket (slim) atau ±0,15 MB per tiket (utuh, Failure Reason
/ export). Setiap tambahan 1.000 tiket menambah ±100–150 MB per request berat yang
berjalan bersamaan. JOB-3 meng-upload ulang tiket yang sama beberapa kali sehari, jadi
pantau `count(*)` di `results` dan `result_data`. Jalankan ulang
`scripts/perf_peak_memory.py` bila jumlahnya sudah ±2× angka di atas.

Dibanding rekomendasi `analisa_kebutuhan_ram.md` (21 Okt): limit API turun dari
6 GiB menjadi 4 GiB. Limit worker tetap 8 GiB, karena besarnya ditentukan oleh
pemrosesan PDF/OCR dan concurrency 8, bukan oleh perubahan ini.

## 7. Deploy dan rollback

- Perubahan ini ada di `core/` (api dan worker) serta `qc_core` (core). Worker ikut
  memakai `stats_aggregate` untuk hitung ulang Statistics (`worker-stats`), jadi
  **image api dan worker sama-sama perlu dibangun ulang**.
- **Perhatian:** branch ini bercabang dari `main`, yang sudah memuat fitur "Upload
  akses per user" (migrasi 0071) yang deploy-nya masih ditahan. Deploy dari `main`
  setelah merge berarti fitur itu ikut naik dan migrasi 0071 dijalankan.
- Rollback: tag image `pre-hemat-memori` sebelum deploy. Tidak ada migrasi yang
  perlu di-downgrade.
