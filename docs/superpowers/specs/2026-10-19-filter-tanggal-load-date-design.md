# Filter Tanggal Results & Stats pakai `load_date` App C — Design

Tanggal: 2026-10-19 · Status: disetujui user 2026-10-19

## 1. Tujuan

Tim menghitung lead per hari berdasarkan **hari tiket dimuat ke App C**
(`/tickets-daily`, kolom `load_date` — layar Recording Tickets / Assign Ticket).
Results dan Stats saat ini memakai **Tanggal Agree** (`submit_time` TMS dari
snapshot `reference_data.cashline`), jadi angkanya tidak cocok dengan hitungan tim.

Kasus pemicu (laporan 19 Okt): daftar lead 12–17 Okt berisi 301 tiket; Stats
12–17 menunjukkan 297. Selisih itu bukan tiket hilang: 30 tiket Agree-nya
1–10 Okt tapi dimuat App C di 12–17, dan 26 tiket Agree 17 Okt belum ada di
daftar. Dengan acuan `load_date` App C, 296 dari 301 cocok (5 sisanya dimuat
App C 10 Okt — data di luar periode, diterima user).

Setelah perubahan ini, filter 12–17 Okt di Results **dan** Stats memberi
himpunan tiket yang sama dengan report `Report_Lead_301_12-17Okt2026.xlsx`
(296 tiket CashLine dari daftar + tiket App C lain yang dimuat di periode itu).

### Keputusan user (2026-10-19)

| Topik | Keputusan |
|---|---|
| Acuan tanggal | `load_date` App C, menggantikan Tanggal Agree |
| Cakupan | Results **dan** Stats (keduanya harus tetap sama angkanya) |
| Tiket dimuat lebih dari sekali | **Filter:** tiket masuk bila **salah satu** `load_date`-nya ada di rentang (sama dengan report, 296) |
| Tanggal tunggal tiket (grafik per hari, tanggal default menu Results) | `load_date` **terakhir** |
| Delete All & Reprocess berdasarkan filter | Pakai `load_date` **terakhir** saja (bukan "salah satu"), supaya tiket yang dimuat ulang di luar rentang tidak ikut terhapus/diproses |

Konsekuensi yang sudah dijelaskan ke user dan diterima: tiket yang dimuat ulang
di luar rentang (contoh `141248zgZn`, load 14/16/19 Okt) ikut di filter 12–17,
tapi tercatat di tanggal 19 Okt pada grafik per hari — total grafik untuk
rentang bisa sedikit lebih kecil dari jumlah baris tabel. Saat ini 91 dari
5.164 tiket App C pernah dimuat lebih dari sekali.

## 2. Di luar cakupan

- Mengubah script luar `/data/app_scheduler` (JOB-3).
- Mengubah cara Assign Ticket / Recording Tickets memakai `load_date` (sudah benar).
- Menghapus konsep Tanggal Agree — tetap tersimpan dan tetap tampil di detail
  tiket bila sekarang tampil; hanya tidak lagi jadi acuan filter/grafik.
- **Batas dokumen H+2 tetap memakai Tanggal Agree** (`submit_time`): `_doc_sla_expired`,
  countdown Pending Check (`crud.tms_submit_time_map`, `SlaCountdown.vue`) dan
  `_submit_agent_map` (Risk Base) tidak berubah. Vonis PASS/FAIL/PENDING harus
  identik sebelum dan sesudah. *(keputusan builder/Claude, bukan user)*
- Kolom "Tanggal Submit" di Stats → Tiket Saya dan tanggal di export tiket tetap
  Tanggal Agree; tidak ada kolom tanggal baru. *(keputusan builder/Claude)*
- Collection Stats (`stats_collection`, `CollectionView`) — campaign Collection
  tidak ada di App C tickets-daily; perilakunya tidak berubah.

## 3. Aturan tanggal baru

Untuk satu tiket (`ticket_id` = prefix sebelum `_` dari source file pertama,
sama dengan `_customer_id()` / `QcAssignment.ticket_id`):

- `load_dates(t)` = himpunan `load_date` semua baris App C dengan `id == t`.
- **Masuk filter `[start, end]`** bila ada `d ∈ load_dates(t)` dengan
  `start ≤ d ≤ end` (batas inklusif, salah satu boleh kosong).
- **Tanggal tunggal** = `max(load_dates(t))`.
- **Cadangan** bila `load_dates(t)` kosong (upload manual, Megapay PDF lama,
  campaign di luar App C, tiket yang belum tersinkron): pakai aturan lama
  persis — Tanggal Agree → `generated_at` → tanggal WIB `uploaded_at`
  (`_series_date_expr` / `_submit_date_map` + `_series_date`). Untuk tiket
  cadangan, filter dan tanggal tunggal memakai tanggal yang sama itu.

## 4. Sumber data: tabel `ticket_load_dates` (baru)

`load_date` belum tersimpan di DB. Satu tiket bisa punya banyak `load_date`,
dan `results` berisi banyak baris per tiket (setiap proses ulang = baris baru),
jadi datanya disimpan **per tiket**, bukan per result:

```
ticket_load_dates
  ticket_id   varchar(100)  not null
  load_date   date          not null
  campaign    varchar(100)            -- campaign App C baris itu (info/debug)
  synced_at   timestamp     not null default now()
  primary key (ticket_id, load_date)
  index (load_date)
```

Migration baru di `api` (nomor berikutnya setelah head prod 0068), schema
`dashboard`. Upsert idempoten (`ON CONFLICT DO NOTHING`/update `synced_at`).

### Pengisian

- **Task beat baru di worker** `sync-ticket-load-dates`: memanggil
  `services.tickets_daily.fetch_all(load_date=D)` untuk hari ini (WIB) dan
  beberapa hari ke belakang (usul: 3 hari), upsert semua `(id, load_date)`.
  Jadwal usul: tiap 30 menit. Semua campaign App C disimpan (bukan hanya
  CashLine) — murah, dan Results/Stats campaign App C lain ikut benar.
- **Backfill sekali jalan** (script / perintah manual, bukan migration):
  loop `load_date` dari tanggal App C paling awal yang tersedia sampai hari ini.
- App C membatasi `limit` 100/halaman; `fetch_all` sudah mempaginasi. Bug
  pagination App C (ORDER BY tanpa tie-breaker) sudah diperbaiki 13 Okt.
- Kube worker (10.158.3.13) berbagi DB prod dan punya beat sendiri: kalau
  ikut menjalankan task ini, upsert idempoten membuatnya aman, tapi image/env
  kube worker harus konsisten (lihat catatan deploy di memori proyek).

## 5. Titik yang berubah

### core (`core/db/crud.py`, `core/compliance/stats_aggregate.py`) — salin ke api & worker

Core masih vendored di api dan worker; perubahan disinkronkan manual ke kedua
salinan dan ke `qc_core`.

- **Results** — `crud.list_results` (+ varian di sekitarnya yang memakai
  `_series_date_expr`, baris ±565–780) dan `crud.latest_result_date`:
  - filter: `EXISTS (ticket_load_dates WHERE ticket_id = cid AND load_date
    BETWEEN …)` **ATAU** (tiket tanpa baris `ticket_load_dates` DAN ekspresi
    cadangan lama di rentang).
  - `latest_result_date`: maksimum dari tanggal tunggal baru (max load_date,
    cadangan bila kosong) — tanggal default menu Results.
- **Stats** — semua tempat yang menaruh tiket di tanggal atau menyaring per
  tanggal: `_submit_date_map`, `_submit_time_map` (bagian tanggal),
  `ticket_chart_dates`, dan pemanggil `chart_dates.get(r.id) or _series_date(r)`
  (baris ±1467, ±1819, ±2548, ±2746, ±3401). Aturannya:
  - filter rentang = aturan "salah satu load_date" §3;
  - posisi di grafik per hari = tanggal tunggal (max load_date) §3.
- **Delete All & Reprocess-by-filter** (`_tickets_for_filtered_delete` di
  `api/routers/stats.py`, `reprocess._plan_for_filtered`): saat ini lewat
  `_resolve_filtered_results` → `crud.list_results`. Keduanya harus memakai
  aturan **max(load_date) di rentang** (cadangan lama untuk tiket tanpa App C),
  bukan aturan "salah satu". Butuh parameter/mode eksplisit di `list_results`
  (default = aturan "salah satu" untuk tampilan) — jangan diwarisi diam-diam.
- **Snapshot Stats**: tanda tangan/versi snapshot dinaikkan (perubahan in-place
  harus bump versi supaya snapshot lama tidak dipakai).
- QC Productivity (`crud` ±3253–3320, via `ticket_chart_dates`) otomatis ikut.

### api

- Migration `ticket_load_dates`.
- Model SQLAlchemy di `core/db/models.py` (salinan api).
- Deskripsi Query `date_start`/`date_end` di `api/routers/stats.py` diperbarui
  ("tanggal load App C").

### worker

- Task beat `sync-ticket-load-dates` + entri di `beat_schedule`.
- Salinan core yang sama.

### dashboard

- Label filter tanggal Results & Stats: "Tanggal Load App C" (atau tooltip
  penjelas). Tidak ada perubahan logika di frontend.

## 6. Verifikasi

- Unit test aturan §3: tiket satu load, multi-load (filter any, tanggal max),
  tiket tanpa App C (cadangan), batas inklusif, rentang terbuka satu sisi.
- Uji vonis: snapshot vonis (AI/Manual status per tiket) sebelum dan sesudah
  harus identik — perubahan ini hanya memindahkan tanggal.
- Uji terhadap data nyata setelah backfill, dihitung sebagai **ticket ID unik**
  (Results menghitung baris result; salinan JOB-3 membuat baris > tiket):
  jalur filter Stats (Failure Rate/hierarki, QC Productivity, export per tiket)
  dan ticket ID unik Results untuk 12–17 Okt, campaign CashLine → **330 tiket**, termasuk 296 dari daftar 301; 5 tiket
  load 10 Okt (`071114mH7F`, `070401utlJ`, `090803wMdP`, `100137zGl5`,
  `101257aSoz`) tidak masuk. Angka Results = Stats untuk rentang yang sama.
- Verifikasi angka Stats lewat endpoint HTTP, bukan script (sakelar SLA H+2
  runtime hanya dibaca jalur HTTP).
- E2E `./jalankan.sh` di `telemarketing-qc-api/e2e` (rebuild bundle dashboard dulu).

## 7. Deploy & rollback

- Urutan: migration → backfill → image api/worker/dashboard baru → cek angka.
- **Kube worker 10.158.3.13** menjalankan `refresh_stats_snapshot` ke DB yang
  sama. Ia harus di-update ke image baru **bersamaan** (dilakukan user), atau
  task snapshot di sana dimatikan sebelum deploy — kalau tidak, snapshot versi
  lama & baru saling menimpa. Pilihan final ditanyakan ke user saat deploy;
  deploy tidak dimulai sebelum salah satunya pasti.
- Tag rollback sebelum deploy: `pre-filter-load-date`.
- Rollback: image lama (aturan lama tidak membaca tabel baru, jadi tabel boleh
  tetap ada); downgrade migration opsional.
- Ikuti prosedur deploy proyek: build kandidat, diff freeze dependency, smoke,
  retag; cek `git status` (prod pernah ter-build dari working tree kotor).

## 8. Diserahkan ke builder

- Bentuk SQL persis (EXISTS vs join/CTE) dan performa — tabel kecil
  (±5 rb tiket/bulan), index `load_date` + PK cukup.
- Jumlah hari ke belakang dan interval sync (usul 3 hari / 30 menit).
- Bentuk script backfill (task Celery sekali jalan atau perintah CLI).
