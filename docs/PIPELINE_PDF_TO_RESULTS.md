# Alur PDF → Results — Telemarketing QC System

Perjalanan satu tiket sejak PDF transkrip masuk sampai barisnya tampil di halaman
**Results**. Dokumen ini menyambung tiga dokumen lain: ingestion-nya dirinci di
[`INTEGRATION.md`](./INTEGRATION.md), tabel yang disentuh ada di
[`DATA_MODEL.md`](./DATA_MODEL.md), dan aturan skor/status di
[`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md). Yang dijelaskan di sini adalah
**urutan kejadiannya** — siapa memanggil siapa, dan di titik mana data berpindah proses.

Ada **tiga fase yang berjalan di proses berbeda**. Memahami batas antar-fase ini penting:
kegagalan di fase 2 tidak pernah terlihat sebagai error HTTP di fase 1, dan angka yang
dilihat pengguna di fase 3 bukan angka yang disimpan di fase 2.

---

## 0. Peta Singkat

```
FASE 1 — UPLOAD (sinkron, container `api`)
  Browser / sistem hulu
      │  POST /upload_transcript   ATAU   POST /webhook/process_ticket
      ▼
  INSERT results (status=pending)          ← baris tabel Results lahir di sini
  PUT MinIO transcripts/{result_id}/*.pdf
  Celery send_task ──────────┐
                             ▼ Redis (broker)
FASE 2 — EVALUASI (async, container `worker`)
  status→processing → download PDF → parse → rakit transkrip
      → tarik reference data (DWH App A) → 1× panggilan LLM
      → tulis MinIO results/{id}.json + INSERT result_data → status→done

FASE 3 — TAMPIL (sinkron, tiap kali halaman dibuka)
  GET /list_results → scope role → ambil result_json
      → HITUNG ULANG skor & AI Status → enrich → items[]
      → render tabel (digrup per ticket ID) + polling 7 detik bila masih berjalan
```

---

## 1. Fase 1 — PDF masuk (sinkron)

Ada **dua pintu masuk**, keduanya berakhir sama: satu baris `results` + PDF di bucket
`transcripts` + satu task Celery.

### 1a. Upload manual dari dashboard

`POST /upload_transcript` — `api/routers/transcript.py:53`, dipakai
`dashboard/src/views/upload/UploadTranscriptView.vue`.

| Langkah | Kode | Catatan |
|---|---|---|
| Validasi semua file `.pdf` | `transcript.py:69` | 422 bila ada yang bukan PDF |
| Validasi campaign aktif | `transcript.py:77` | 422 bila campaign tidak ada/nonaktif |
| Cari hasil lama yang bisa di-clone | `transcript.py:92` | lihat §1d |
| `INSERT results` (`status=pending`) | `transcript.py:96` | **selalu baris baru** |
| `PUT` tiap PDF ke `transcripts/{result_id}/{nama}.pdf` | `transcript.py:114` | `transcript_path = "{result_id}/"` |
| `send_task(process_transcript, [result_id])` | `transcript.py:145` | respons balik `status=pending` |

Setiap upload **selalu** membuat baris `results` baru. Satu ticket ID yang di-upload dua
kali menghasilkan dua baris — penggabungannya terjadi di frontend (§3c), bukan di DB.

### 1b. Webhook dari sistem hulu (jalur produksi)

`POST /webhook/process_ticket` — `api/routers/webhook.py:128`. Ini pintu masuk yang dipakai
n8n phase-1: yang dikirim hanya `ticket_id` + `product`, **bukan** file-nya.

1. `product` → campaign aktif (case-insensitive), `customer_id` diturunkan dari `ticket_id`.
2. Scan bucket `transcripts` untuk PDF sesi ini (`webhook.py:158`) — 404 bila tidak ketemu.
3. `create_result(...)` (`:177`), lalu **copy** tiap PDF ke `{result_id}/{basename}` (`:188`).
4. Scan bucket `documents` untuk customer id yang sama, klasifikasi tipe, copy + `create_document` (`:199`–`:220`).
5. Enqueue: **selalu** `process_transcript` (`:233`); `process_document` **hanya bila** ada dokumen (`:238`).

> ⚠️ Endpoint ini **public tanpa auth** — lihat peringatan di [`INTEGRATION.md`](./INTEGRATION.md) §2.

### 1c. Asal isi `transcripts/{result_id}/` — siapa yang menulis

Folder inilah yang di-download worker di Fase 2. Isinya **selalu ditulis di Fase 1**, tidak
pernah oleh worker: worker hanya `list_objects` dengan prefix `{result_id}/` lalu
`fget_object`, dan tidak tahu siapa yang menaruhnya. Ada dua penulis:

| Pintu masuk | Operasi | Byte-nya dari mana |
|---|---|---|
| `/upload_transcript` | `put_object` (`transcript.py:114`) | benar-benar diunggah lewat multipart — dari komputer pengunggah |
| `/webhook/process_ticket` | `copy_object` (`webhook.py:188`) | **sudah lebih dulu ada di bucket `transcripts`**, ditaruh sistem hulu (service transkripsi/STT) |

Jalur webhook — yang dipakai produksi — **menemukan** file, bukan menerimanya. n8n phase-1 hanya
mengirim `ticket_id` + `product`; penyalinannya server-side, tidak ada byte yang melewati proses
`api`:

| Tahap | Kode | Mekanisme |
|---|---|---|
| Turunkan `customer_id` dari `ticket_id` | `webhook.py:78` | `130220dkIM_20260519132045` → `130220dkIM` |
| List semua `.pdf` di bucket | `webhook.py:113` | prefix = `MINIO_TRANSCRIPTS_SOURCE_PREFIX` |
| Cocokkan per file | `webhook.py:88` | `customer_id` diambil dari **basename** tiap objek, lalu dibandingkan |
| Lewati yang sudah diproses | `webhook.py:94` | segmen path pertama berupa UUID = sudah pernah masuk |
| Salin ke folder kerja | `webhook.py:188` | `copy_object` → `{result_id}/{basename}` |

Pencocokannya **murni dari nama file**, bukan dari database. Satu sesi bisa punya beberapa
panggilan, dan semua PDF dengan prefix customer id yang sama ikut terkumpul — itulah kenapa
konvensi nama file (lihat [`INTEGRATION.md`](./INTEGRATION.md) §1) bukan sekadar kerapian.

> ⚠️ **Prefix sumbernya kosong di produksi.** `minio_transcripts_source_prefix` default `""`
> (`api/dependencies.py:48`) dan variabelnya tidak ada di `.env`, jadi `_find_session_objects`
> **men-scan seluruh bucket**, bukan hanya folder `inbox/` seperti saran `.env.example`. Hasilnya
> tetap benar karena folder `{result_id}/` di-skip, tapi biayanya naik seiring bucket membesar:
> tiap panggilan webhook melist seluruh isi bucket.

**Jalur ketiga yang TIDAK berakhir di sini.** `POST /webhook/register_stt_result`
(`webhook.py:283`) membuat baris `results` dengan `status="done"` langsung, `campaign = NULL`, dan
`transcript_path` diisi nama file PDF di S3 lain (port 8010) — **tanpa** menyalin apa pun ke bucket
`transcripts` dan **tanpa** enqueue task apa pun. Itu jalur audio mandiri untuk mencatat hasil STT,
bukan tiket QC, jadi worker tidak pernah menyentuhnya. Endpoint ini juga idempoten: `result_id` =
`job_id` dari STT, dan register ulang untuk id yang sama tidak membuat baris duplikat.

### 1d. Jalur pintas "reuse" (tanpa LLM)

Bila customer ID itu **sudah pernah** punya hasil `done`, defaultnya hasil lama di-**clone**
ke baris baru tanpa memanggil LLM sama sekali (`transcript.py:127`): evaluasi, banding, dan
approval SPQ Head ikut tersalin, JSON-nya di-mirror ke bucket `results`, dan responsnya
langsung `status=done, reused=true`. Kirim `reuse=false` di form untuk memaksa proses ulang.

### 1e. Catatan: upload audio belum tersambung

`POST /upload_audio` (`transcript.py:167`) menyimpan file ke bucket `audio` dan membuat baris
`results`, tapi **tidak ada task yang di-enqueue** (`transcript.py:235` masih TODO). Barisnya
akan bertahan `pending` selamanya sampai pipeline audio→transkrip dibuat.

---

## 2. Fase 2 — Evaluasi di worker (async)

`worker/tasks/process_transcript.py:113`. Sepuluh langkah, semuanya dalam satu
`try/except/finally`.

| # | Langkah | Kode |
|---|---|---|
| 1 | `status → processing`, set `started_at` | `:121` |
| 2 | Download semua PDF `transcripts/{result_id}/` ke `/tmp` (isinya ditulis di Fase 1 — §1c) | `:128` |
| 3 | `build_transcript(pdf_paths)` → `messages` + durasi audio | `:133` |
| 4 | Load campaign aktif: `prompt_text` + `scorecard_text` + `kb_text` | `:149` |
| 4b | `build_reference_data()` → data TMS/Ascend, ditempel ke scorecard | `:178` |
| 5 | `evaluate()` → **satu** panggilan LLM → JSON evaluasi | `:188` |
| 6 | Rakit `final_json` | `:203` |
| 7 | `PUT` MinIO `results/{result_id}.json` | `:227` |
| 8 | `INSERT result_data.result_json` (JSONB) | `:236` |
| 9 | `status → done` + `completed_at` + `processing_sec` + `generated_at` | `:239` |
| 10 | `except` → `status=failed` + `error_message`; `finally` → bersihkan `/tmp` | `:254` |

### Parsing PDF — `compliance/pdf_parser.py`

`build_transcript()` (`:212`) mengurutkan PDF **ascending** berdasarkan timestamp di nama file
(fallback: mtime, lalu urutan asli), lalu tiap file di-parse `parse_transcript_pdf()` (`:116`)
dengan pdfplumber menjadi segmen `{speaker, timestamp, text}`. Semua segmen digabung jadi satu
transkrip berurutan; tiap file dapat `call_index` 1..N sehingga LLM bisa membedakan panggilan
yang timestamp-nya sama-sama mulai dari `00:00`.

Dari nama file diturunkan dua identitas berbeda yang mudah tertukar:

| Istilah | Contoh | Cara turun |
|---|---|---|
| `ticket_id` | `130220dkIM_20260519132045` | stem nama file, tanpa `.pdf` & tanpa suffix ` (1)` — `pdf_parser.py:102` |
| `customer_id` / `id` | `130220dkIM` | prefix sebelum `_` → `ticket_id.rsplit("_", 1)[0]` |

`customer_id` inilah kunci yang menyambungkan `results` ↔ `tms_cashline.result_id` ↔
`qc_assignments.ticket_id`.

### Reference data — `compliance/reference_data.py:184`

`customer_id` dipakai menarik baris **CASHLINE** + **CARD HOLDER** dari DWH Aplikasi A,
dirender jadi blok teks JSON, lalu **ditempel di belakang `scorecard_text`**
(`process_transcript.py:181`) supaya LLM bisa mencocokkan ucapan agent dengan data
sebenarnya. Baris mentahnya juga ikut disimpan ke `final_json["reference_data"]` — dengan
begitu halaman Results bisa membaca `customer_name` / `account_number` / `change_flags`
langsung dari `result_json` tanpa menembak App A lagi setiap dashboard dibuka.

Fungsinya mengembalikan `(text, warnings, raw)`. Baris referensi yang tidak ketemu **tidak**
menggagalkan tiket — nilainya jadi `null` + satu warning di log, dan LLM menandainya
`SKIPPED_NULL`.

### Panggilan LLM — `compliance/evaluator.py:117`

Satu chat completion, tanpa tool-calling:

- **system** = `campaign.prompt_text` (berisi aturan QC + format output JSON yang ketat)
- **user** = `TRANSCRIPT:\n… \n\nKB:\n… \n\nSCORECARD:\n…` (`evaluator.py:100`)

Transkrip dirender `format_transcript_for_llm()` (`:19`): tiap panggilan diberi penanda
`=== Panggilan ke-N (ticket_id: …, id: …, file: …, waktu: …) ===`, tiap baris berformat
`[SPEAKER] [timestamp] teks`.

Output **wajib** JSON. Bila tidak parseable, di-retry sampai 2× (total 3 percobaan), lalu
`ValueError` → tiket `failed`.

### Dua penjaga "gagal keras"

Sengaja melempar error alih-alih mengirim input kosong ke LLM — karena input kosong akan
menghasilkan evaluasi sampah yang tetap berstatus `done`:

1. **Transkrip kosong** (`:139`) — tidak ada satu pun segmen yang bisa di-parse, biasanya
   karena format diarization hulu berubah dan header speaker tidak dikenali lagi.
2. **Campaign belum dikonfigurasi** (`:167`) — campaign placeholder yang dibuat agar bisa
   ditugaskan ke role, tapi `prompt`/`scorecard`/`KB`-nya masih kosong.

### Persistensi ganda

JSON hasil ditulis ke **dua** tempat: MinIO `results/{id}.json` (arsip) dan Postgres
`result_data.result_json` bertipe JSONB. **Yang dibaca dashboard adalah yang di Postgres.**

---

## 3. Fase 3 — Tampil di Results (sinkron, tiap request)

### 3a. Yang paling sering disalahpahami: AI Score & AI Status tidak disimpan

Keduanya **dihitung ulang setiap request** di dalam loop `list_results`
(`api/routers/stats.py:355`, loop mulai `:571`), dari `result_data.result_json`. Alasannya:
banyak hal berubah **setelah** evaluasi selesai, dan angka yang tersimpan akan basi.

Urutan penerapannya:

1. `normalize_static_verification()` — zona abu-abu ditegakkan di kode, bukan diserahkan ke LLM.
2. Banding Error Code yang **di-approve** → item scorecard dibalik jadi SESUAI (skor naik).
3. Banding jenis **`add`** → error baru ditempelkan (skor turun).
4. **AI Score dihitung deterministik dari scorecard** (skor maksimal − bobot item BELUM_SESUAI,
   + verifikasi + kritis) — bukan angka yang disebut LLM. Ini yang membuat kolom AI Score
   konsisten dengan XLSX export.
5. `AI Status = PASS bila ai_score >= passing_grade`, else FAIL. (Fallback ke `ai_status` dari
   LLM hanya bila skor/passing grade tidak tersedia.)
6. **Override** Manual Status yang sudah di-approve QC.
7. **Aturan terakhir, dicek paling belakang**: satu saja item *non-tolerable* yang masih
   BELUM_SESUAI memaksa **FAIL** — mengalahkan skor lolos maupun approval QC.

Detail bobot & precedence-nya ada di [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md).

### 3b. Scope & enrichment

Sebelum loop di atas, daftar tiket dipersempit berlapis dan **tidak pernah melebar**:

```
campaign milik role  ∩  scope data role (_scoped_customer_ids)  ∩  filter hierarki AM/TL/TLO
   ∩  isolasi QC Support  ∩  filter tanggal / ticket id / campaign
```

Karena AI Status & Manual Status **diturunkan** (tidak ada kolomnya di SQL), filter kedua
dropdown itu tidak bisa dikerjakan di SQL: `list_results` memuat seluruh hasil `done` yang
cocok lalu menyaringnya di Python dengan helper yang sama persis dipakai menu Results, Manual
Check, dan Pending Check — supaya "Qualified" berarti hal yang sama di ketiga menu.

Setelah baris halaman ini didapat, enrichment-nya dilakukan **batched, bukan N+1**: waktu &
tipe dokumen, permintaan Manual Status, banding, flag perubahan TMS, `submit_time` (basis SLA
H+2), assignment QC, dan riwayat Manual Status — masing-masing satu query untuk seluruh halaman.

### 3c. Frontend — `dashboard/src/views/dashboard/ResultsView.vue`

| Bagian | Kode | Perilaku |
|---|---|---|
| Ambil data | `fetchItems()` `:915` | `GET /list_results` dengan parameter dari `buildParams()` `:890` |
| Grouping | `groupFlat()` `:739` | beberapa result dengan ticket ID sama → satu baris yang bisa di-expand; `primary` = `generated_at` terbaru |
| Paginasi | `:515`, `:516` | default grouping di sisi client, 20 grup/halaman (`VITE_RESULTS_GROUPING=server` memindahkannya ke backend) |
| Auto-refresh | `:996`, `:1022` | **polling tiap 7 detik** selama masih ada baris `pending`/`processing`, berhenti sendiri saat semua selesai — tidak ada websocket, dan polling berhenti saat tab tidak terlihat |
| Detail baris | `fetchResult()` `:967` | `GET /result/{id}` (`transcript.py:388`), hanya untuk role yang boleh melihat detail evaluasi |

Kolom yang tampil berbeda per role, dan ditentukan **capability**, bukan nama role — mis.
`RESULTS_EVALUATION_DETAIL`, `MANUAL_STATUS_COLUMN`, `RESULTS_CRITICAL_FAILURE`. Lihat
[`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md).

---

## 4. `generated_at` vs `uploaded_at`

Dua stempel waktu yang beda arti dan sering tertukar:

| Kolom | Asal | Dipakai untuk |
|---|---|---|
| `uploaded_at` | waktu server saat baris dibuat | filter tanggal di Results, fallback chart |
| `generated_at` | header **"Generated"** di dalam PDF, diambil yang paling baru antar-PDF satu tiket (`pdf_parser.py:92`) | sumbu-x chart AI Status di Statistics, dan urutan grup di Results (`resultTs()`) |

`generated_at` boleh `NULL` (PDF lama tanpa header itu) — di chart Statistics ia jatuh ke
`uploaded_at`.

---

## 5. Di mana melihat kalau ada yang salah

| Gejala | Kemungkinan | Cek |
|---|---|---|
| Baris tetap `pending` selamanya | task tidak pernah sampai ke worker, atau ini upload **audio** | log `worker`, Flower (port 4005), §1e |
| `failed` — "Transkrip kosong" | format PDF hulu berubah | `compliance/pdf_parser.py`, uji `parse_transcript_pdf` pada file itu |
| `failed` — "belum punya konfigurasi QC" | campaign placeholder | Upload Campaign (prompt/scorecard/KB) |
| `done` tapi kolom customer kosong | reference data tidak ketemu | warning `reference data (…)` di log worker; allowlist field cache App A |
| Skor berubah tanpa evaluasi ulang | memang begitu — banding/Manual Status dihitung saat baca | §3a |

---

## Referensi terkait
- [`INTEGRATION.md`](./INTEGRATION.md) — konvensi nama file, webhook, konfigurasi Celery & LLM, bucket MinIO.
- [`DATA_MODEL.md`](./DATA_MODEL.md) — skema `results`, `result_data`, dan tabel workflow QC.
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — model scoring & precedence status PASS/FAIL/PENDING.
- [`API_REFERENCE.md`](./API_REFERENCE.md) — kontrak `/upload_transcript`, `/list_results`, `/result/{id}`.
- [`RUNBOOK.md`](./RUNBOOK.md) — operasi harian, restart worker, refresh snapshot Statistics.
