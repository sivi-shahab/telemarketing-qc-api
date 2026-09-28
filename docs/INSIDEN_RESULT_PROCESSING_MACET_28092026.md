# Result tertahan `processing` di halaman Results — debug & perbaikan (28 September 2026)

Status: **pembersih ter-deploy dan terverifikasi di produksi** (28 Sep 2026, 03:27 UTC).
Akar masalah di sisi **worker kube (10.158.3.13)** belum diperbaiki — lihat bagian 6.

| Langkah | Hasil |
|---|---|
| Lokalisasi: dashboard / api / worker lokal / pihak lain? | **worker kube** yang memakai DB yang sama (bagian 2–3) |
| Pola macet | task berhenti sesudah `unduh_pdf`/`cek_nama_agent`, dikirim ulang Redis tiap 60 menit (bagian 4) |
| Pembersih `processing` basi (worker + beat) | **ter-deploy**, menutup 16 baris pada 03:27 UTC (bagian 5) |
| Revisi ambang 60 → 55 menit | wajib — ambang 60 menit tidak pernah menangkap apa pun (bagian 5b) |
| Siklus kirim-ulang kube | terbukti: 16 baris yang ditutup 03:27 kembali `processing` 03:31 (bagian 5c) |

---

## 1. Gejala

Halaman Results menampilkan **56 result** dengan status "sedang diproses" yang tidak
pernah selesai. Semuanya Cashline, diunggah `22050660` (admin), dalam empat gelombang:

| `uploaded_at` (WIB) | Jumlah macet |
|---|---|
| 24 Sep 11:00 | 12 |
| 24 Sep 13:00 | 18 |
| 26 Sep 05:00 | 16 |
| 27 Sep 05:00 | 10 |

`current_stage` berhenti di `unduh_pdf` (51 baris), `cek_nama_agent` (4), atau
`rangkai_transkrip` (1). Tidak satu pun sampai ke `penilaian_llm`.

## 2. Bukan dashboard, bukan api/worker lokal

- **Dashboard** hanya menampilkan isi `dashboard.results.status`. Tidak ada yang salah di sana.
- **Worker lokal** (`telemarketing-qc-worker-worker-1`) sehat. Task terakhirnya 25 Sep
  12:55 UTC dan selesai normal, lalu log-nya kosong. Redis lokal (`:6378`) juga kosong:
  tidak ada key `celery` maupun `unacked`.
- **API lokal** tidak menerima upload gelombang 26 dan 27 Sep. Sejak API di-restart
  (25 Sep 12:05 UTC), log-nya hanya berisi 60 `POST /upload_transcript` pada 25 Sep
  12:16/12:25 UTC, yaitu batch yang sudah `done`. Result `done` dari gelombang 26 Sep
  juga tidak ada di log worker lokal.
- **Tapi `started_at` tetap berubah.** Ke-56 baris mendapat `started_at` baru pada
  28 Sep 02:08–02:11 dan 02:31 UTC. Satu-satunya penulis kolom itu adalah
  `process_transcript.py` (langkah "mark processing"). Worker lokal
  (`concurrency=8`, `prefetch=1`) tidak mungkin memulai 56 task dalam 3 menit, dan
  host ini tidak menjalankan container lain pada jam tersebut.

## 3. Pelakunya: worker kube 10.158.3.13

`pg_stat_activity` di DB `da` menunjukkan 14 koneksi dari **10.158.3.13**, dengan pola
`COMMIT`/`ROLLBACK` khas SQLAlchemy. Koneksi barunya muncul pukul 09:11 dan 09:34 WIB,
berdekatan dengan waktu reset `started_at`.

Menurut pemilik sistem, 10.158.3.13 adalah **worker di Kubernetes yang sengaja diarahkan
ke Postgres/schema `dashboard` yang sama untuk keperluan debug**, dengan **Redis
sendiri**. Konsekuensinya:

- Task yang diantrekan di Redis kube tidak terlihat dari stack lokal, dan sebaliknya.
- Task yang diambil kube tetap menulis ke `dashboard.results` yang dibaca dashboard lokal.

## 4. Pola macet: dikirim ulang tiap 60 menit

Pengamatan pada 28 Sep (UTC):

| Kelompok | `started_at` awal | Di-reset ke |
|---|---|---|
| 40 baris | 02:08–02:11 | **03:08–03:11** (tepat +60 menit, sebaran per menit sama) |
| 16 baris | 02:31 | (ditutup pembersih 03:27, lihat bagian 5b) |

60 menit adalah **`visibility_timeout` bawaan Redis (3600 s)**. Dengan
`task_acks_late=True`, task yang tidak di-ack dalam selang itu dikirim ulang, dan
worker menulis `started_at` baru. Artinya, di worker kube task-nya **tidak pernah
selesai, tidak pernah gagal, dan tidak pernah dihentikan batas waktu**. Worker lokal
punya `task_time_limit=3000`, yang seharusnya menghentikan task sebelum 60 menit.

Dugaan yang perlu dicek di kube (belum terbukti tanpa log pod):

- Pool worker kube `threads`/`solo`. Di kedua pool ini `task_time_limit` **tidak berlaku**,
  jadi task yang hang dibiarkan selamanya.
- Pod di-restart atau OOM sebelum task selesai, sehingga pesan kembali ke antrean.
- Yang tergantung sesudah `unduh_pdf` adalah `_assigned_name_online` (lookup
  TMS/DWH API) atau `transcript_plain_text`. Periksa apakah pod kube bisa menjangkau
  `DWH_API_BASE_URL` (di lokal: `http://host.docker.internal:8002`, alamat yang tidak
  berlaku di dalam kube).

## 5. Perbaikan: pembersih `processing` basi

Sebelum ini tidak ada mekanisme apa pun, di api maupun worker, yang menutup baris
`processing` milik worker yang mati. Jalur `except` di `process_transcript` tidak
pernah dilewati kalau prosesnya di-SIGKILL, OOM, atau pod-nya diganti.

- **`crud.fail_stale_processing_results(db, now=None)`** (core; salinan identik di
  api, worker, `qc_core`). Baris `processing` dengan `started_at` lebih lama dari
  `STALE_PROCESSING_AFTER` diubah jadi `failed`, dengan `error_message`:
  *"Proses terhenti di tahap '<current_stage>' tanpa kabar lebih dari 55 menit
  (worker kemungkinan mati). Silakan proses ulang."*
  - `now` dihitung **UTC dari Python**. `started_at` ditulis worker dalam UTC naive,
    sedangkan `now()` Postgres adalah WIB; memakai `now()` akan menutup baris 7 jam
    terlalu cepat.
  - `SELECT … FOR UPDATE SKIP LOCKED`: baris yang sedang ditulis worker mana pun
    (lokal atau kube) dilewati dan dicoba lagi di putaran berikutnya.
- **Task `worker.tasks.maintenance.fail_stale_processing_results`**, dijadwalkan
  `beat_schedule` tiap **120 detik**.
- **Service `beat` baru** di `docker-compose.yml` repo worker. Cukup satu replika.
  Karena operasinya idempoten, beat kedua yang mengarah ke DB yang sama tetap aman.

### 5b. Kenapa 55 menit, bukan 60

Versi pertama memakai 60 menit (`task_time_limit` + 10). Putaran pertamanya di
produksi (03:16 UTC) menutup **0 baris**, karena 40 baris sudah di-reset kube pukul
03:08–03:11. Ambang yang sama dengan `visibility_timeout` tidak pernah bisa menang.

Syarat yang sekarang dijaga test:

```
task_time_limit (3000 s)  <  STALE_PROCESSING_AFTER (3300 s)
STALE_PROCESSING_AFTER + interval beat (120 s)  <  visibility_timeout (3600 s)
```

`broker_transport_options={"visibility_timeout": 3600}` kini ditulis eksplisit di
`celery_app.py` (nilainya sama dengan bawaan) supaya syarat itu bisa diuji.

### 5c. Verifikasi di produksi

- 03:23 dan 03:25 UTC: `{'failed': 0}`. Kelompok 02:31 belum mencapai 55 menit.
- **03:27 UTC: `{'failed': 16}`**. Ke-16 baris kelompok 02:31 ditutup, dengan tahap
  terakhir `unduh_pdf` (15) dan `rangkai_transkrip` (1).
- **03:31 UTC**: kube mengirim ulang ke-16 task itu (tepat 60 menit sesudah 02:31) dan
  barisnya kembali `processing` dengan `started_at` 03:31. Ini membuktikan siklus
  `visibility_timeout` pada bagian 4. Pembersih akan menutupnya lagi sekitar 04:27.
- 40 baris kelompok 03:08–03:11 akan tertutup sekitar 04:03–04:07 UTC.

### 5d. Test

- **worker** `tests/test_stale_processing_reaper.py`: jadwal beat, ambang di atas
  `task_time_limit`, ambang + interval di bawah `visibility_timeout`, dan task yang
  menutup sesinya. Hasil: 6 passed.
- **api** `tests/test_stale_processing_reaper.py`: dijalankan terhadap DB sungguhan
  dalam transaksi yang selalu di-rollback. Datanya bertahun 2000 dengan `now` di tahun
  2000, jadi baris produksi tidak ikut tersentuh. Mencakup: basi → `failed` beserta
  tahapnya; masih dalam batas → tidak disentuh; `done`/`pending`/`started_at` NULL →
  tidak disentuh.
- Suite penuh: api 473 passed / 6 skipped, core 313 passed / 5 skipped.

## 6. Yang tersisa

1. **Worker kube.** Selama task-nya masih tergantung di Redis kube, task yang sama akan
   dikirim ulang tiap jam dan menandai baris itu `processing` lagi. Pembersih lalu
   menutupnya lagi 55 menit kemudian. Ini membuat status tetap jujur, tapi sumbernya
   harus dibereskan di kube: cek pool (`--pool`), `task_time_limit`, restart pod, dan
   jangkauan `DWH_API_BASE_URL`, lalu kosongkan antrean Redis kube.
2. **Proses ulang ke-56 tiket** lewat worker lokal (tombol Reprocess), **sesudah**
   antrean kube dikosongkan. Kalau dilakukan sebelumnya, kedua worker akan berebut
   baris yang sama.
3. **`error_message` basi saat task diulang.** `update_result_status(..., "processing")`
   tidak mengosongkan `error_message`. Baris yang dikirim ulang kube tampil
   `processing` tapi masih membawa pesan "Proses terhenti…" dari penutupan sebelumnya.
   Ini perilaku lama (berlaku juga untuk retry biasa) dan belum diubah.
4. **Zona waktu campur.** `uploaded_at` tersimpan dalam WIB (`server_default=now()`),
   sedangkan `started_at`/`completed_at` dalam UTC. Akibatnya sebuah result bisa
   terlihat "mulai sebelum diunggah". Belum diubah.

---

## 7. Temuan lanjutan: zona waktu WIB vs UTC

Saat menganalisis kasus ini, ditemukan bahwa timestamp tersimpan dalam dua zona:

| Sumber penulis | Zona tersimpan |
|---|---|
| `server_default=func.now()` / `func.now()` (Postgres, `TimeZone = Asia/Jakarta`) | **WIB** |
| `datetime.utcnow()` / `_utcnow()` di Python | UTC |
| `datetime.now()` di Python (TZ container api/worker = UTC) | UTC |

Contoh data: `results.uploaded_at` (WIB) vs `started_at` (UTC), dan `reprocess_jobs.created_at`
(WIB) vs `reprocess_job_items.started_at` (UTC). Keputusan pemilik sistem:
**semua memakai WIB.**

### 7a. Diperbaiki (branch `fix/waktu-wib-sla-reproses`)

Dua tempat yang **salah hitung**, bukan sekadar salah tampil:

1. **Tenggat reproses "tersangkut"** (`crud._reprocess_item_active_clause`).
   `reprocess_jobs.created_at` (WIB) dibandingkan dengan `datetime.now()` (UTC) − 6 jam,
   sehingga jendela 6 jam efektif menjadi **13 jam**.
2. **Tenggat dokumen H+2** (`stats_aggregate._doc_sla_expired` dan 12 pemanggilnya, ditambah
   `api/routers/stats.py` dan `api/routers/transcript.py`). `submit_time` TMS adalah WIB
   (contoh: rekaman `…_20260924124130.pdf` → submit `2026-09-24 12:55:27`), tetapi
   "sekarang" dihitung dari UTC. Akibatnya tiket yang kekurangan dokumen baru jatuh ke
   **FAIL 7 jam terlambat**.

Perbaikannya adalah helper `crud.now_wib()`, yang mengembalikan jam dinding WIB (naive) dari
`datetime.now(timezone.utc)`. Hasilnya tidak bergantung pada TZ container, sehingga juga
benar di kube. Test `telemarketing-qc-core/tests/test_waktu_wib.py` (TZ proses dipaksa UTC)
menjaga: `now_wib`, tenggat H+2 lewat/belum lewat, larangan `datetime.now()` di
`stats_aggregate`, dan batas reproses.

Test api `test_reprocess_active_flag.py` dan `test_reprocess_kill.py` sebelumnya membuat job
dengan `created_at=datetime.now()` (UTC), sehingga ikut mengunci asumsi lama. Keduanya kini
memakai `crud.now_wib()`, sesuai dengan isi kolom di produksi.

**Dampak saat di-deploy:** tiket PENDING yang tenggat H+2-nya sudah lewat menurut jam WIB
akan langsung tampil FAIL, maju hingga 7 jam dibanding sebelumnya.

### 7b. Konvensi ditetapkan: simpan UTC, tampilkan WIB (branch `fix/simpan-utc-tampil-wib`)

Keputusan pemilik sistem: **pengguna melihat WIB di mana-mana, DB menyimpan UTC**. Ini
adalah konvensi yang sudah dipakai kode, yaitu 25 penulis `utcnow()`, 11 konversi
UTC→WIB di core, dan 13 file dashboard yang menambah `'Z'` lalu merender Asia/Jakarta.
Yang melanggarnya hanya Postgres produksi: `TimeZone = Asia/Jakarta` membuat 17 kolom
`server_default=func.now()` terisi WIB. Akibatnya `results.uploaded_at` terkonversi dua
kali (upload sesudah 17:00 WIB masuk hari berikutnya di filter tanggal dan statistik)
dan tampil 7 jam maju di dashboard.

Perbaikan:

1. **Sesi DB dipaksa `timezone=UTC`** di `api/dependencies._make_engine` dan
   `worker/config.db_connect_args`, sehingga `now()`/`server_default` menulis UTC.
   Kode core dan dashboard **tidak perlu diubah**.
2. **Migrasi 0060** (`0060_timestamp_simpan_utc.py`) menggeser −7 jam nilai lama yang
   terbukti WIB (dry-run di produksi, transaksi di-rollback):

   | Tabel.kolom | Baris |
   |---|---|
   | `results.uploaded_at` | 547 |
   | `result_data.created_at` | 489 |
   | `results.started_at`/`completed_at` jalur salin (`started_at = completed_at`) | 90 |
   | `reprocess_jobs.created_at` | 35 |
   | `reprocess_jobs.finished_at` (yang `>= created_at`; id dicatat di `_tz0060_job_finished_wib`) | 26 |
   | `roles` 10, `sales_databases` 6, `campaigns` 2+2, `users` (dibuat sesudah 2026-09-03 13:52 WIB) 3 | |

   Sesudah dry-run: median `result_data.created_at − results.completed_at` berubah dari
   +7 jam menjadi 0, dan `started_at − uploaded_at` dari −7 jam menjadi +11 menit.
   Tidak disentuh: `qc_assignments` (sudah UTC), `stats_snapshots.computed_at` (tidak
   pernah dibaca), `app_settings.updated_at` (1 baris, asal tak pasti),
   `qc_status_requests`/`error_code_appeals`/`documents` (kosong).
   Pengaman: data hanya digeser bila TimeZone bawaan server = WIB. DB UTC (stack e2e)
   dilewati. Rantai upgrade → downgrade → upgrade sudah diuji pada Postgres WIB dan UTC.
3. **Batas reproses tersangkut dibalik ke UTC** (`datetime.utcnow()`), karena
   `created_at` kini UTC. Tenggat H+2 **tetap** `crud.now_wib()`, karena `submit_time`
   TMS adalah WIB dari hulunya.

Test: api `tests/test_simpan_utc.py` (sesi UTC, default `uploaded_at` UTC, migrasi
maju/mundur pada baris sintetis), worker `tests/test_sesi_db_utc.py`, core
`test_waktu_wib.py` (batas reproses UTC). Suite: api 476 passed, core 318, worker 8.

**Syarat deploy:** worker dan beat dihentikan dulu, API di-deploy (alembic menjalankan
0060 saat start), baru worker yang baru dinyalakan. Dengan begitu tidak ada baris WIB
yang tertulis di sela migrasi. **Worker kube** (image lama) masih menulis WIB lewat
default DB, misalnya `result_data.created_at` saat task-nya selesai, sampai image-nya
diperbarui.

Sisa kecil: nama file export di `stats.py` memakai jam container (UTC).

---

## 8. Supaya worker kube aman saat di-deploy ulang

Kube berjalan di server lain dan belum bisa dilihat log-nya dari sini. Karena itu
perbaikannya ditujukan pada **pola kegagalan** yang teramati dari DB, bukan pada satu
dugaan penyebab.

### 8a. Pola yang teramati

- 56 task dimulai hampir bersamaan (16/8/8/8 per menit), jauh di atas `concurrency`
  satu worker. Artinya beberapa pod/replika, atau concurrency tinggi.
- Semuanya berhenti di tahap awal (`unduh_pdf` 50, `cek_nama_agent` 5, `baca_teks_pdf` 1),
  yaitu tahap parsing PDF dan roster yang paling boros memori.
- Tidak ada yang sempat ditandai `failed`, dan `task_time_limit` tidak pernah terpicu.
- Task muncul lagi **tepat tiap 60 menit** (`visibility_timeout` Redis).

Semua pemanggilan jaringan di tahap itu punya timeout (DWH API 10 s, MinIO boto3
connect 5 s / read 30 s), jadi task **bukan hang menunggu jaringan**. Yang paling
cocok adalah **proses worker mati mendadak** (OOM-kill atau pod restart): SIGKILL tidak
melewati `except`, pesan yang belum di-ack baru dikembalikan Redis setelah 60 menit,
lalu burst yang sama mati lagi.

### 8b. Perbaikan di kode (berlaku otomatis begitu image kube diperbarui)

| Perbaikan | Efek di kube |
|---|---|
| Pembersih `processing` basi, 55 menit via beat (bagian 5) | row macet ditutup `failed` sebelum Redis mengirim ulang |
| **`process_transcript` melewati row `done`/`failed`** (worker, branch `fix/tolak-result-tertutup`) | pengiriman ulang pesan basi tidak lagi membuka row yang sudah ditutup, sehingga siklus bolak-balik tiap jam putus |
| Sesi DB `timezone=UTC` (bagian 7b) | kube menulis timestamp dengan konvensi yang sama |
| `visibility_timeout` eksplisit 3600, dijaga test terhadap ambang pembersih | tidak ada celah pembersih kalah cepat |

Pengaman kedua aman untuk alur normal. Satu-satunya jalur sah ke `process_transcript`
adalah upload (`api/routers/transcript.py`, `webhook.py`) dan reproses (pemanggilan
langsung dengan row baru), dan keduanya membawa row `pending`. Row `processing`
(pengiriman ulang sebelum pembersih jalan) tetap boleh dicoba lagi. Test:
`telemarketing-qc-worker/tests/test_tolak_result_tertutup.py`.

### 8c. Checklist saat deploy ulang kube

1. Pakai image worker dari branch-branch di atas (sudah termasuk pembersih, pengaman,
   dan sesi UTC). Tidak ada env baru yang wajib diisi.
2. **Jalankan beat tepat 1 replika** (`celery -A worker.celery_app beat`) bila kube
   memakai DB-nya sendiri. Selama kube memakai DB yang sama dengan server ini, beat di
   server ini sudah cukup; beat kedua pun aman (idempoten + `SKIP LOCKED`).
3. **Pool worker harus `prefork`** (bawaan). Pada pool `threads`/`gevent`/`solo`,
   `task_time_limit` tidak berlaku.
4. **Cek memori:** `kubectl describe pod` → `Last State: OOMKilled`? Kalau ya, turunkan
   `CELERY_CONCURRENCY` per pod atau naikkan limit memori. Di server ini satu child idle
   ±250 MB, dan puncak parsing PDF bisa beberapa kali lipat.
5. **`DWH_API_BASE_URL` wajib diisi** alamat yang terjangkau dari pod. Nilai bawaan
   compose (`host.docker.internal`) tidak berlaku di kube. Kalau salah, task tidak hang
   (timeout 10 s), tetapi nama agent/TMS kosong.
6. **Kosongkan antrean Redis kube** dari pesan lama sebelum menyalakan worker baru,
   supaya burst lama tidak diulang.

---

## 9. Reproses result yang gagal/macet (28 September 2026)

Atas permintaan pemilik sistem, semua result `failed`/`processing` diproses ulang lewat
worker di server ini: job `d27d6a67-d40f-43cc-a33d-aa13503c7573`, `scope="campaign"`, dibuat
dengan fungsi dan pengaman yang sama dengan tombol Reprocess All
(`crud.reprocess_plan_for_tickets`, `active_reprocess_item_for_ticket`, tolak kalau ada job
massal lain).

**Pemilihan tiket:** 45 tiket yang **belum punya hasil `done` sama sekali**:
- 44 tiket kube yang macet (54 row);
- 1 tiket Collection non-kube dari 22 Sep ("Transkrip kosong").

Dua tiket yang sudah punya hasil `done` **tidak** direproses, supaya hasil yang mungkin
sudah dilihat QC tidak berubah.

**Hasil** (04:26–04:56 UTC, ±30 menit, 8 paralel):

| Status | Tiket | Keterangan |
|---|---|---|
| `done` | **44** | 55 row lama (macet + duplikat upload berkas yang sama) diganti satu row baru per tiket. Rata-rata 5,1 menit per tiket, terlama 8,4 menit |
| `failed` | 1 | "Syafira Putrianti" (Collection): transkrip PDF kosong, sama seperti sebelumnya. Row lama tetap utuh |

Sesudahnya **tidak ada lagi row `processing`**. Karena row lama kube sudah dihapus, pesan
yang masih tersisa di Redis kube tidak lagi punya baris untuk di-reset (`get_result` →
None → task gagal dan di-ack).

**Row duplikat yang dibuang:** `230224vC1k` — row `processing` `26c3c68c…` memakai berkas
yang sama persis (`230224vC1k_20260923142405.pdf`) dengan row `done`-nya. Tiket kini tinggal
satu row `done`.

**Tidak dihapus: "Everd Francis Bartholemeus"** (Collection). Row `failed` `fdd3795d…` adalah
**rekaman yang berbeda** (`…-103719-…pdf`) dari ketiga row `done`, bukan duplikat. Row ini
satu-satunya jejak bahwa rekaman itu gagal dibaca ("Transkrip kosong"). PDF-nya perlu
diekspor ulang dari sumber.

**Catatan Collection:** "tiket" Collection dikelompokkan per **nama agent**
(`split_part(source_files[0], '_', 1)`), sehingga satu tiket bisa berisi beberapa rekaman
berbeda. Tombol Reprocess/Delete per tiket di Collection mengenai **semua** rekaman agent
itu. Sebelum job dijalankan sudah diperiksa: item job yang punya >1 row lama semuanya berkas
Cashline yang sama (upload ganda), dan satu-satunya item Collection hanya punya satu rekaman.

Sisa 2 row `failed` (Collection, transkrip kosong) membutuhkan PDF yang benar dari sumber.

---

## 10. Optimasi waktu load halaman (28 September 2026)

Permintaan: halaman Results, Stats, Transkrip, Assign Ticket, Manual Check dan Pending Check
tidak boleh lama; boleh cache Redis ber-TTL 1 bulan.

### 10a. Temuan (diukur, bukan diduga)

1. **Cache DWH praktis tidak pernah kena.** `.env` api/worker mengisi
   `DWH_API_CACHE_TTL_SEC=5` (bawaan kode 300), dan cache itu per proses gunicorn. Results
   menembak **±300 request DWH** per load (5,6–28 detik).
2. **JSON hasil evaluasi diambil ulang dari Postgres tiap load.** `crud.result_json_map`
   mentransfer **18 MB** JSON dari Postgres remote (3,6–5,5 detik; parse-nya hanya 0,15 detik).
   Pending Check (395 result) memanggilnya dua kali per request: **7,7–9,3 detik**.
3. Latensi satu panggilan DWH hanya ±52 ms, jadi masalahnya jumlah panggilan, bukan
   kecepatan DWH.

### 10b. Perubahan

| Perubahan | PR |
|---|---|
| **Cache DWH dua lapis:** L1 memori + **L2 Redis bersama**. Data ditemukan 30 hari, 404 1 jam, gagal tidak disimpan. Redis bermasalah → HTTP (timeout 0,5 s, jeda 30 s). **Worker evaluasi tidak membaca L2** (selalu data segar) tetapi menulisnya | core #14, worker #18, api #27 |
| `.env` api & worker: `DWH_API_CACHE_TTL_SEC` 5 → 300 (backup `.env.bak.20260928-115724`) | — (di luar git) |
| **Cache JSON hasil evaluasi di Redis** per id baris `result_data` (30 hari). Aman tanpa invalidasi: baris tidak pernah diubah, reproses menambah baris baru | core #15, api #28, worker #19 |
| Hasil task Celery di Redis 30 hari (`CELERY_RESULT_EXPIRES_DAYS`); task pembersih `ignore_result` | worker #17 |

### 10c. Hasil di produksi (sesudah deploy, 05:27 UTC)

| Halaman | Endpoint terlambat | Sebelum | Sesudah |
|---|---|---|---|
| Results | `/list_results` (100 baris) | 5,6–28 s | **1,3–1,4 s** |
| Pending Check | `/list_results?manual_status_pending` | 7,7–9,3 s | **2,6 s** |
| Stats | `/stats/failure_reasons(_hierarchy)` saat pertama | 6,4–7 s | **0,16–0,25 s** |
| Manual Check | `/list_results?banding_pending` | 0,3 s | 0,35 s |
| Transkrip | `/tickets_daily` | 0,4–0,5 s | 0,1–0,4 s |
| Assign Ticket | `/qc_assignments`, `/qc_assignment/*` | < 0,3 s | < 0,25 s |

Redis total 27 MB (sebelumnya 1,85 MB).

**Sisa yang belum dioptimasi:** hitung ulang snapshot Statistics ±6,5 detik (turun dari 11).
Snapshot dihitung ulang setiap kali signature data berubah, jadi pengguna Stats pertama
sesudah ada perubahan menunggu segitu. Sisanya komputasi CPU (pencocokan nama, penilaian
ulang status AI). Memo `levenshtein` sudah diukur dan hanya memberi ±8%, jadi tidak
diambil.

**Ditindaklanjuti (10e):** snapshot kini dihitung ulang di latar belakang.

### 10d. Insiden saat deploy: dependensi tidak terkunci

Deploy pertama cache DWH (05:00 UTC) membuat **API dan worker gagal start ±6 menit**
(`ModuleNotFoundError: No module named 'psycopg'`). Keduanya segera di-rollback ke image
`pre-cache-dwh`. Tidak ada upload yang masuk selama gangguan, dan tidak ada result yang
tertahan.

- **Penyebab:** `core/requirements.txt` tidak mengunci versi. Menambah baris `redis`
  membatalkan cache layer pip, sehingga rebuild menarik **SQLAlchemy 2.1.1**, yang mengganti
  driver bawaan `postgresql://` ke `psycopg` v3 (tidak terpasang). Ikut naik tanpa diuji:
  openai 3.16→3.19, starlette, uvicorn, boto3, flower.
- **Perbaikan:** `api/constraints.txt` dan `worker/constraints.txt` = `pip freeze` image yang
  terbukti jalan, dipakai `pip install -c` di Dockerfile. Rebuild kini identik (0 perbedaan
  paket).
- **Prosedur deploy baru:** tag `pre-*` → `TAG=cand docker compose build` → bandingkan
  `pip freeze` (harus 0 perbedaan) → smoke test di container sementara (alembic, `/health`,
  endpoint, koneksi DB worker) → `docker tag cand latest` → `up -d --no-build`.
- **Temuan ikutan:** partisi `/` penuh 100% karena image store containerd
  (`/var/lib/containerd`, 13 GB) berada di partisi root, bukan `/data`. `docker builder
  prune` membebaskan ±8 GB (kini 86%). Perlu dipantau; pertimbangkan memindahkan data-root
  containerd ke `/data`.

### 10e. Snapshot Statistics dihitung ulang di latar belakang (core #16, api #29, worker #20)

- **Stale-while-revalidate** di `crud.get_or_build_stats_snapshot(session_factory=...)`,
  berlaku untuk semua pemakai snapshot: overview, hierarchy, campaigns_monthly,
  failure_reasons (+ hierarchy), ai_status_timeseries, my_overview, di semua scope pengguna.
  - Bila data berubah dan snapshot lama dengan versi format sama sudah ada, snapshot lama
    langsung disajikan dan yang baru dihitung di thread dengan sesi DB sendiri.
    Refresh otomatis 30 detik halaman Stats lalu menampilkan angka baru.
  - Snapshot yang belum pernah ada, versi format berbeda, atau tombol Refresh SPQ Head
    (`force`) tetap dihitung langsung.
  - Kunci Redis per scope (`lock:stats-snapshot:*`, 10 menit, fail-open) mencegah dua
    proses gunicorn menghitung scope yang sama.
- **Beat worker `refresh_stats_snapshot` tiap 2 menit** menyegarkan snapshot global secara
  proaktif (0,5–0,8 detik bila data tidak berubah). Signature data api dan worker sudah
  diverifikasi identik, jadi keduanya tidak saling menimpa.
- **Di produksi (08:09 UTC):** seluruh endpoint Stats 0,07–0,35 detik. Pengguna tidak lagi
  menunggu ±6,5 detik sesudah data berubah; yang masih dihitung langsung hanya kombinasi
  filter yang belum pernah diminta hari itu (mis. timeseries bulanan pertama kali: ±9,5 s).
- Deploy memakai prosedur 10d (kandidat → 0 perbedaan paket → smoke → retag). Image
  rollback: `local/qc-api:pre-snapshot-latar`, `local/qc-worker:pre-snapshot-latar`.

---

## 11. Merge ke main, rebuild dashboard, dan pemindahan data-root containerd (28 September 2026)

### 11a. Semua PR di-merge ke `main`

Seluruh rantai PR bertumpuk di-merge berurutan dari yang paling bawah. Tiap PR berikutnya
dialihkan base-nya ke `main` sebelum di-merge. Semua memakai merge commit, dan branch
tidak dihapus.

| Repo | PR | `main` |
|---|---|---|
| core | #10 → #16 | `6734b34` |
| worker | #12 → #20 | `1cb6b52` |
| api | #22 → #29 | `41e4ec9` |
| dashboard | #16 | `08fa71a` |

Terverifikasi: `main` core/worker/api identik (0 perbedaan) dengan kode yang berjalan di
produksi. `main` dashboard = fitur Kill reproses + fix nginx akses IP (PR #15). Keempat
folder repo di server kini di-checkout ke `main`, karena deploy membangun image dari folder.

### 11b. Rebuild dashboard: login lewat IP berfungsi

Fix nginx (`f3332f0`, PR #15) sudah di `main` sejak pagi, tetapi container dashboard belum
di-rebuild. Prosedur 10d dipakai:

- Bundle JS kandidat **identik** (md5 per file) dengan yang tersaji; satu-satunya perubahan
  adalah `nginx.conf`.
- Tujuan proxy sama dengan nginx host: `/api-b/` → API (port 4000), `/api-a/` → App A
  (port 8000), `/api/download` dan `/api/view-streams/` → 8010.
- Smoke test di port sementara 24006 (port 14006 sudah dipakai layanan lain, dan hasil uji
  pertama di sana dibuang).

| Akses lewat `http://10.158.32.26:4006` | Sebelum | Sesudah |
|---|---|---|
| Halaman, `/api-b/health` | 200 | 200 |
| `POST /api-b/auth/login` | **405** | **422** (sampai ke API; kredensial uji ditolak) |

Akses lewat domain `call-qc.bankmega.local` tetap 200. Rollback: `local/qc-dashboard:pre-nginx-ip`.

Catatan: `nginx -t` di luar network `qc-net` gagal pada upstream `api`. Ini alarm palsu,
karena di dalam `qc-net` lolos.

### 11c. Data-root containerd dipindah ke `/data`

**Latar:** Docker memakai containerd image store (`io.containerd.snapshotter.v1`).
`daemon.json` sudah menaruh `data-root` di `/data/docker`, tetapi containerd masih memakai
root bawaan `/var/lib/containerd` di partisi `/` (49 GB). Build berulang membuat `/` penuh 100%
(bagian 10d).

**Langkah:**
1. Salin awal `/var/lib/containerd` (6,4 GB) → `/data/containerd` dengan `rsync -aHAX
   --numeric-ids` selagi semua jalan (1 menit 42 detik).
2. Pastikan tidak ada result `pending`/`processing` dan tidak ada job reproses berjalan.
3. `systemctl stop docker.socket docker containerd` → rsync akhir `--delete` → set
   `root = "/data/containerd"` di `/etc/containerd/config.toml` (backup
   `config.toml.bak.20260928`) → folder lama diganti nama `.bak` → start containerd dan docker.
   **Docker mati ±23 detik.**
4. Verifikasi: containerd hanya membuka file di `/data/containerd`; image dan container
   utuh; dashboard (IP dan domain), API, login, worker, dan beat normal; data Redis utuh
   (194 cache DWH, 395 cache JSON); `qc-collection-app` normal.
5. Hapus `/var/lib/containerd.bak`.

| Partisi | Sebelum | Sesudah |
|---|---|---|
| `/` | 87% (6,5 GB kosong) | **74% (13 GB kosong)** |
| `/data` | 92% (26 GB kosong) | 94% (19 GB kosong) |

**Container tanpa restart policy** (`qc-test-minio/redis/pg/pg2`, `adminer`, `redis-dev`)
tidak hidup sendiri sesudah Docker di-restart, jadi dinyalakan manual. Perlu diingat pada
setiap restart Docker atau reboot.

**`qc-test-dash` dibiarkan mati.** Container uji e2e lama (20 Agustus) ini me-mount
`nginx.conf` langsung dari folder repo dashboard. Sejak folder itu di `main`, file tersebut
memuat proxy ke upstream `api`, yang tidak ada di `qc-test-net`, sehingga nginx gagal start.
Stack ujinya memang sudah tidak berfungsi (`qc-test-api` mati sejak 26 September).
Menyambungkannya ke network produksi akan membuat dashboard uji menembak API produksi, jadi
opsi itu tidak diambil. Bila dibutuhkan, jalankan ulang lewat `./jalankan.sh`.

**Perlu dipantau:** `/data` kini 94% (19 GB kosong), karena beban `/` pindah ke sana.
Pertimbangkan memperbesar volume atau membersihkan image lama (`pre-*`, `cand`) secara berkala.
