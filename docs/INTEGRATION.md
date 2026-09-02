# Integrasi & Ingestion — Telemarketing QC System

Menjelaskan **cara data masuk & diproses**: webhook ingestion, konvensi nama file, alur
worker (Celery), integrasi **LLM** dan **OCR**, serta endpoint upload dari dashboard.

Sumber: `api/routers/webhook.py`, `worker/tasks/process_transcript.py`,
`worker/tasks/process_document.py`, `worker/celery_app.py`, `compliance/ocr.py`,
`compliance/riplay.py`, `compliance/pdf_parser.py`, `compliance/reference_data.py`.

---

## 1. Konvensi Nama File PDF

```
<prefix>_<YYYYMMDDHHMMSS>.pdf      contoh: 130220dkIM_20260519132045.pdf
```

| Istilah | Nilai (contoh) | Cara turun |
|---|---|---|
| `ticket_id` | `130220dkIM_20260519132045` | nama file tanpa `.pdf` |
| `id` / customer id | `130220dkIM` | prefix sebelum `_` (dari PDF paling awal) → `rsplit("_", 1)[0]` |

Beberapa PDF satu sesi diurutkan **ascending** berdasarkan timestamp pada nama file.
Customer id inilah kunci yang menghubungkan `results` ↔ `tms_cashline.result_id` ↔
`qc_assignments.ticket_id`. Parser: `compliance/pdf_parser.py` & `compliance/reference_data.py`.

---

## 2. Webhook Ingestion

Endpoint utama untuk memasukkan tiket dari sistem hulu (mis. n8n phase-1):

```
POST /webhook/process_ticket        (Content-Type: application/x-www-form-urlencoded)
  ticket_id: str   (wajib)
  product:   str   (wajib — dipetakan ke campaign aktif, case-insensitive)
```

Alur (`api/routers/webhook.py`):
1. Validasi `ticket_id` & `product` (422 bila kosong).
2. `product` → campaign aktif via `get_active_campaign_ci` (422 bila tak ada).
3. Turunkan `customer_id` dari `ticket_id`.
4. Scan **bucket transcripts** untuk PDF sesi ini; 404 bila tak ada.
5. `create_result(...)`, lalu **copy** tiap PDF ke `{result_id}/{basename}` (set `transcript_path = {result_id}/`).
6. Scan **bucket documents** untuk customer id yang sama; klasifikasi tipe dokumen; copy ke `{result_id}/{doc_type}.pdf`; `create_document(...)`.
7. Enqueue Celery: **selalu** `process_transcript`; `process_document` **hanya bila** ada dokumen.
8. Balas `WebhookProcessResponse` (`status="pending"`, `phase_2_enqueued=true`, `phase_3_enqueued=<ada dokumen?>`).

> ⚠️ **Webhook ini PUBLIC (tanpa auth).** Router dibuat tanpa dependency (`APIRouter()`),
> meniru webhook hulu. Mesin `X-API-Key` ada di `api/dependencies.py` tapi **tidak dipasang**
> di endpoint ini. **Rekomendasi handover:** lindungi di reverse proxy (allowlist IP / secret
> path) atau tambahkan `verify_api_key`.

### Source prefix MinIO

- `MINIO_TRANSCRIPTS_SOURCE_PREFIX` / `MINIO_DOCUMENTS_SOURCE_PREFIX` (saran `.env.example`: `inbox/`).
- `_find_session_objects` melist objek `.pdf` di prefix tsb, cocokkan customer id.
- **Objek yang sudah diproses dilewati**: bila segmen path pertama adalah UUID (`{result_id}/`),
  objek dianggap sudah masuk dan **tidak** di-ingest ulang (`_is_result_folder`).

> ⚠️ Kedua variabel ini **tidak ada di `.env` production**, sehingga jatuh ke default `""` =
> **scan seluruh bucket**, bukan hanya `inbox/`. Tambahkan keduanya bila ingest memang harus
> dibatasi ke satu folder.

---

## 3. Worker (Celery)

`worker/celery_app.py`: app `bank_qa`, broker+backend = `REDIS_URL`. Config: `timezone=Asia/Jakarta`,
`task_acks_late=True`, `task_time_limit=1800`, `task_soft_time_limit=1500`, concurrency =
`CELERY_CONCURRENCY` (default 8; **production saat ini 24**).

Dua task:

### `worker.tasks.process_transcript.process_transcript(result_id)`
1. Status result → `processing`.
2. Download PDF dari `transcripts/{result_id}/` ke `/tmp`.
3. `build_transcript(pdf_paths)` (pdfplumber) → `sorted_filenames, messages, audio_duration`; ambil `generated_at` dari header PDF. Error bila messages kosong.
4. Ambil campaign aktif; `build_reference_data(customer_id, db)` di-append ke `scorecard_text`.
5. `evaluate(...)` → panggil LLM.
6. Rakit `final_json` (evaluation + metadata).
7. Upload JSON ke bucket **results** (`{result_id}.json`) + simpan ke Postgres (`save_result_data`).
8. Status → `done` (isi `result_path`, `completed_at`, `processing_sec`, `generated_at`).
9. Bila error → status `failed` (+ `error_message`); `/tmp` dibersihkan.

### `worker.tasks.process_document.process_document(result_id)`
Untuk tiap `Document` berstatus `pending`: status→processing → ambil PDF dari bucket documents
→ `build_document_reference` (acuan) → `build_ocr_request(doc_type, reference)` → `ocr_document(...)`
(Mistral) → simpan `ocr_json` (`set_document_result`) atau `set_document_failed`.

---

## 4. Integrasi LLM

- Client: `openai.OpenAI` (OpenAI-compatible) — `OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=LLM_TIMEOUT)`.
- Dipanggil via `compliance.evaluator.evaluate(...)` dengan `prompt_text`, `messages`, `kb_text`,
  `scorecard_text` (+ reference data), `model`, `temperature`, `seed`, `reasoning_effort`.
- **Prompt diambil fresh dari DB** (`campaigns.prompt_text`) setiap task — perubahan campaign langsung berlaku.

### Format transkrip: tag panggilan `[Pn]` (13 Agustus 2026, prompt v54)

`compliance/evaluator.py::format_transcript_for_llm` mencap **setiap baris** dengan tag
panggilan dan membuka transkrip dengan legenda (hanya bila `source_files` tersedia):

```
=== DAFTAR PANGGILAN (pakai tag [Pn] di tiap baris untuk mengisi evidence.ticket_id) ===
P1 = 030808fLO1_20260709111836   (waktu: 2026-07-09 11:18:36)
P2 = 030808fLO1_20260710160335   (waktu: 2026-07-10 16:03:35)
=== AKHIR DAFTAR PANGGILAN ===
=== Panggilan ke-2 (ticket_id: …) ===
[P2] [Agent] [31:39.32 - 32:31.01] Iya. Ya itu nggak ada susahnya kok…
```

> Legenda ini sempat membawa penanda tanggal per panggilan (`[VERIFIKASI STATIK: SAH /
> TIDAK SAH]` di v56–v57, lalu `[TANGGAL SUBMIT]` / `[H±n]` di v58) untuk aturan tanggal
> verifikasi statik. Aturan itu **dicabut pada v59** atas konfirmasi Bank Mega, jadi
> penandanya ikut dibuang — menyisakannya hanya mengundang model memberi bobot pada
> sesuatu yang bukan lagi aturan. Lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1.

Sebelumnya `ticket_id` hanya ada di penanda `=== Panggilan ke-N ===`, jadi mengisi
`evidence.ticket_id` menuntut model mengingat header yang bisa puluhan ribu karakter di
atas. Gagalnya persis seperti yang bisa ditebak: pada tiket `030808fLO1` kutipan **32.515
karakter** di bawah header-nya (tapi hanya ~51 baris di atas header BERIKUTNYA) diklaim
milik panggilan sesudahnya, sementara kutipan 7.290 karakter di bawah header yang sama
tercatat benar. Audit 12 tiket multi-panggilan menemukan 2 evidence lain yang timestamp-nya
mustahil ada di panggilan yang disebutnya — jadi bug ini mengenai evidence scorecard dan
error code, bukan hanya badword.

Dengan tag menempel pada barisnya, model tidak lagi butuh memori jarak jauh: jawabannya ada
di baris yang sedang dikutip. Biaya ~5 karakter per baris (<3% transkrip besar). Prompt v54+
(§`INPUT SCHEMA` → "TAG PANGGILAN PER BARIS") mewajibkan `ticket_id` diambil dari tag `[Pn]`
baris yang dikutip, dengan larangan eksplisit menyalin penanda `=== Panggilan ke-N ===`
terdekat. Diuji di `tests/test_evaluator.py`.

Env vars (worker):

| Var | Default kode | Production saat ini |
|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:11444/v1` | Azure AI Foundry (`…/openai/v1`) |
| `LLM_API_KEY` | `dummy` | key Foundry Bank Mega |
| `LLM_MODEL` | `gpt-oss-120b` | `gpt-5.4-mini` |
| `LLM_TEMPERATURE` / `LLM_SEED` | `1.0` / `42` | sama |
| `LLM_REASONING_EFFORT` / `LLM_TIMEOUT` | `medium` / `1800` | sama |

> Default kode masih menunjuk container gpt-oss-120b lokal; deployment Bank Mega memakai
> endpoint Azure AI Foundry. Keduanya OpenAI-compatible, jadi tidak ada perbedaan kode.

### Ekstraksi RIPLAY (saat upload campaign, bukan saat evaluasi)

`compliance/riplay.py` merender RIPLAY PDF jadi gambar halaman lalu mengirimkannya ke model
vision untuk diekstraksi, kemudian menumpangkan hasilnya ke KB campaign.

| Var | Default | Arti |
|---|---|---|
| `RIPLAY_MODEL` | *(kosong)* | model vision; kosong = ikut `LLM_MODEL` |
| `RIPLAY_MAX_PAGES` | `20` | batas halaman yang dirender |
| `RIPLAY_RENDER_SCALE` | `2.0` | skala render halaman → gambar |
| `RIPLAY_MIN_SIMILARITY` | `50.0` | ambang kemiripan nama produk RIPLAY vs nama campaign |

Detail perilakunya: [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §2.

---

## 5. Integrasi OCR (opsional)

- Provider: **Mistral Document AI** (endpoint Azure-hosted), `compliance/ocr.py`.
- `ocr_document(pdf_bytes, prompt, schema, base_url, api_key, model)`: PDF di-base64 →
  `POST` JSON `{model, document:{document_url:"data:application/pdf;base64,..."}, document_annotation_format, document_annotation_prompt}` dengan header `Authorization: Bearer <key>` → ambil `document_annotation`.
- **Kapan dipakai**: task `process_document` (setelah `/upload_document` atau webhook phase-3),
  untuk OCR + verifikasi KTP/KK/NPWP/Cover Buku Tabungan vs data acuan bank.
- Env vars: `OCR_BASE_URL`, `OCR_MODEL` (`mistral-document-ai-2512`), `OCR_API_KEY` (+ `OCR_TEMPERATURE/SEED/REASONING_EFFORT`). String kosong → dianggap None (OCR dinonaktifkan).

---

## 6. Endpoint Upload (dashboard-driven)

| Endpoint | Method | Permission | Keterangan |
|---|---|---|---|
| `/upload_transcript` | POST | login | Upload PDF transkrip → buat result → enqueue evaluasi |
| `/upload_audio` | POST | login | Simpan audio (belum ada pipeline STT) |
| `/upload_document` | POST | `results.document.upload` | Upload dokumen pendukung customer (TL Sales & Admin) |
| `/upload_detail_campaign` | POST | `admin.campaign.write` | Upload konfigurasi campaign + RIPLAY opsional |
| `/upload_sales_database` | POST | `admin.sales_database.write` | Upload XLSX database sales |
| `/upload_qc_database` | POST | `admin.qc_database.write` | Upload XLSX database QC |

> Menu-nya dijaga permission `menu.upload_*` yang terpisah dari permission aksinya.

Detail auth & seluruh endpoint: [`API_REFERENCE.md`](./API_REFERENCE.md).

---

## 7. Bucket MinIO

| Bucket | Isi |
|---|---|
| `transcripts` | PDF transkrip (mentah di `MINIO_TRANSCRIPTS_SOURCE_PREFIX`, terproses di `{result_id}/`) |
| `results` | Hasil evaluasi JSON (`{result_id}.json`) |
| `campaigns` | Arsip file campaign (`{campaign}/{prompt,knowledge_base,scorecard}.txt`) |
| `documents` | Dokumen pendukung customer |
| `audio` | File audio |
| `sales-database`, `qc-database` | XLSX database yang di-upload |

Semua bucket dibuat otomatis saat api start (`ensure_buckets()`).

---

## Referensi terkait
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — apa yang dinilai LLM
- [`API_REFERENCE.md`](./API_REFERENCE.md) — endpoint & auth
- [`DATA_MODEL.md`](./DATA_MODEL.md) — tabel results/documents/tms_cashline
- [`DEPLOYMENT.md`](./DEPLOYMENT.md) — env var LLM/OCR/MinIO
