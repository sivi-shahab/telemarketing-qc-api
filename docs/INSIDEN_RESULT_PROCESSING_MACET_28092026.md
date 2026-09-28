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
