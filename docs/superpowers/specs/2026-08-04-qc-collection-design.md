# QC Collection: Results & Transkrip untuk campaign penagihan

Tanggal: 2026-08-04
Bahan sumber: `campaigns/` (`prompt_collection_qc_7indikator_v2.txt`, `kb_col_v2.txt`,
`scorecard_collection.txt`, `qc_collection_dashboard.html`)

## Tujuan

Menambah dukungan QC panggilan penagihan (collection) berbasis POJK 22/2023 —
checklist 7 indikator YA/TIDAK — ke sistem yang sekarang hanya menangani QC
telemarketing (cashline, scorecard berbobot).

Batasan yang mengikat rancangan ini:

1. Hanya **dua fitur baru**: Results Collection dan Transkrip Collection.
2. Fitur lain (Statistics, Campaigns, Upload Campaign / Transkrip / Audio,
   Assign Ticket, Banding, Manual Check) **tidak ditambah dan tidak diubah**.
3. Rilis pertama bersifat **read-only**: daftar + filter + detail + cetak.
   Tanpa banding, tanpa manual status, tanpa assign ticket, tanpa statistik.

## Kondisi awal

### Yang sudah mendukung collection tanpa perubahan

| Komponen | Alasan |
|---|---|
| `db/models.py:Campaign` | sudah generik: `prompt_text` / `scorecard_text` / `kb_text` |
| `compliance/evaluator.py` | schema-agnostic — merangkai TRANSCRIPT/KB/SCORECARD lalu parse JSON apa pun yang dikembalikan model |
| `POST /upload_transcript` | sudah punya dropdown campaign |
| `POST /upload_audio` (App A `save_dashboard`) | sudah menerima field `campaign` |
| `GET /transcript_pdf/{result_id}` | generik, tidak bergantung bentuk evaluasi |
| Menu Upload Campaign | prompt/KB/scorecard collection di-upload lewat sini apa adanya |

### Yang tidak cocok

| Lokasi | Masalah |
|---|---|
| `worker/tasks/process_transcript.py:153-160` | selalu menempel reference data CASHLINE + CARD HOLDER ke `scorecard_text`; tidak relevan untuk collection dan mengotori prompt |
| `compliance/scoring.py` | menghitung skor dari `scorecard_result` + `passing_grade`; output collection tidak punya keduanya |
| `compliance/error_codes.py` | membangun tabel Error Code dari item `SC_CL_*` |
| `dashboard/src/components/EvaluationView.vue` | 1354 baris, murni cashline (skor maksimal, batas lulus, verifikasi data) |
| `GET /list_results`, `GET /list_transcripts` | tiket collection akan muncul dengan kolom Skor / AI Status / Error Code kosong |

### Bentuk output collection

Dari `prompt_collection_qc_7indikator_v2.txt` (OUTPUT FORMAT, dikunci ketat):

```json
{
  "call_id": "string | null",
  "deskcoll_name": "string | null",
  "cardholder_name": "string | null",
  "checklist_result": [
    { "no": 1, "kb_code": "KB_COL_1", "indikator": "...", "pasal": "...",
      "status": "YA | TIDAK", "catatan": "...",
      "evidence": { "timestamp": "string | null", "quote": "string | null" } }
  ],
  "total_terpenuhi": 6,
  "total_dinilai": 7,
  "hasil_akhir": "COMPLIANT | TIDAK COMPLIANT",
  "ringkasan": "..."
}
```

Tidak ada skor, tidak ada bobot, tidak ada partial credit. `hasil_akhir` =
`COMPLIANT` hanya bila ketujuh indikator `YA`.

## Rancangan

### 1. Penanda campaign

Satu sumber kebenaran, dibaca API maupun worker:

```
.env
COLLECTION_CAMPAIGNS=collection_v2      # comma-separated
```

Modul baru `compliance/campaign_kind.py`:

```python
def parse_collection_campaigns(raw: str) -> frozenset[str]:
    """'a, B ,' -> frozenset({'a', 'b'}) — trim + casefold, buang yang kosong."""

def is_collection(name: str | None, allowed: frozenset[str]) -> bool:
    """True bila nama campaign (trim + casefold) ada di allowed."""
```

Field `collection_campaigns: str = ""` ditambahkan ke `api/dependencies.py:Settings`
**dan** `worker/config.py:WorkerSettings`, masing-masing dengan properti turunan
yang memanggil `parse_collection_campaigns`.

Nilai default kosong berarti fitur mati total dan perilaku existing tidak
berubah sama sekali — ini juga perilaku saat rollback.

Alasan memilih konfigurasi ketimbang kolom `campaigns.kind`: kolom baru
mengharuskan perubahan pada form Upload Campaign, yang termasuk "fitur lain".

### 2. Worker — satu percabangan

`worker/tasks/process_transcript.py`, menggantikan langkah 4b:

```python
if is_collection(result.campaign, settings.collection_campaign_set):
    scorecard_text = campaign.scorecard_text     # tanpa reference data
    reference_raw = None
else:
    customer_id = customer_id_from_filenames(sorted_filenames)
    reference_text, ref_warnings, reference_raw = build_reference_data(customer_id, db)
    for warn in ref_warnings:
        logger.warning(...)
    scorecard_text = f"{campaign.scorecard_text}\n\n{reference_text}"
```

`final_json` ditambah dua field:

- `"kind": "collection" | "sales"` — supaya API dan frontend memilih renderer
  tanpa perlu membaca konfigurasi lagi
- `"speaker_stats": [...]` — lihat bagian 3

Langkah lain (evaluator, upload MinIO, `save_result_data`, transisi status,
penanganan gagal) tidak berubah.

### 3. Parser — metrik speaker (additive)

`compliance/pdf_parser.py:28` sudah menangkap gender dan emosi dari header
`AGENT_BM (female) [NETRAL]:` lalu membuangnya. Perubahan:

1. simpan `gender` dan `emotion` sebagai key **tambahan** pada tiap message
2. fungsi baru `speaker_stats(messages) -> list[dict]`:

```python
[{"speaker": "AGENT_BM", "gender": "female",
  "emotions": {"NETRAL": 12}, "seconds": 92.2, "pct": 70.4}]
```

Signature `build_transcript()` tetap mengembalikan 3 nilai, dan
`format_transcript_for_llm()` hanya membaca `speaker` / `timestamp` / `text` —
sehingga evaluasi sales tidak terpengaruh. `speaker_stats` dipanggil di worker
dari `messages` yang sudah ada, tanpa mem-parse ulang PDF.

Message yang gender/emosinya tidak ada (format header lama `[SPEAKER_1]:`)
menghasilkan `None`; frontend menampilkannya sebagai "tidak tersedia".

### 4. Backend — router baru + eksklusi

Router baru `api/routers/collection.py`. Akses: `qc`, `team_leader_qc`,
`qc_support`, `spq_head`, `admin` (sama dengan Recording Tickets; ditegakkan di
router, bukan hanya di frontend).

| Endpoint | Isi |
|---|---|
| `GET /collection/list_results` | param: `ticket_id`, `date_start`, `date_end`, `status`, `hasil` (`COMPLIANT`\|`TIDAK_COMPLIANT`), `page`, `limit`. Item: `result_id`, `id` (ticket), `campaign`, `status`, `uploaded_at`, `generated_at`, `num_calls`, `audio_duration`, `hasil_akhir`, `total_terpenuhi`, `total_dinilai`, `failed_indicators` (daftar `no`) |
| `GET /collection/list_transcripts` | `crud.list_transcripts(..., campaigns_in=<set>)`; bentuk respons sama dengan `/list_transcripts` |
| `GET /collection/result/{result_id}` | `result_json` apa adanya — **tanpa** `_with_error_code_table()` yang cashline-specific |

`hasil` dan `failed_indicators` diturunkan dari `result_json` di Python (tidak
tersimpan sebagai kolom), mengikuti pola filter `ai_status` di `/list_results`.

Perubahan additive di `db/crud.py` — mengikuti pola `exclude_uploaded_by_role`
yang sudah ada di kedua fungsi:

```python
def list_results(..., campaigns_in=None, exclude_campaigns=None)
def list_transcripts(..., campaigns_in=None, exclude_campaigns=None)
```

Eksklusi di dua endpoint existing (masing-masing satu argumen tambahan):

- `GET /list_results` → `exclude_campaigns=<collection set>`
- `GET /list_transcripts` → `exclude_campaigns=<collection set>`

Ini bersifat menahan data, bukan menambah fitur: tanpa itu, baris collection
muncul di tabel sales dengan kolom Skor / AI Status / Error Code kosong dan ikut
terhitung pada "Total".

`GET /transcript_pdf/{result_id}` dipakai ulang tanpa perubahan.

### 5. Frontend

**File baru (4):**

| File | Isi |
|---|---|
| `views/collection/CollectionResultsView.vue` | filter bar (ticket id, tanggal, status, hasil) + tabel + baris expand berisi `CollectionEvaluationView` |
| `views/collection/CollectionTranscriptsView.vue` | daftar PDF transkrip collection + `PdfViewer.vue` existing |
| `views/collection/collectionSummary.js` | fungsi murni penurun summary dari `evaluation` (dipisah agar bisa diuji tanpa DOM) |
| `components/CollectionEvaluationView.vue` | renderer laporan |

`CollectionEvaluationView.vue` mengikuti mockup `qc_collection_dashboard.html`:

1. **Summary row** — Hasil akhir (COMPLIANT / TIDAK COMPLIANT), Total terpenuhi
   `X / 7`, Indikator gagal (nomor + label pendek), Durasi audio
2. **Identitas panggilan** — kartu deskcoll dan cardholder dari `deskcoll_name` /
   `cardholder_name`, dilengkapi `speaker_stats` (gender, durasi bicara + %,
   profil emosi). Kartu "perusahaan yang dihubungi" / "institusi disebut" pada
   mockup **tidak dibuat** — itu hasil interpretasi manual, bukan field pada
   skema output.
3. **Checklist 7 indikator** — per item: `no` · `pasal`, teks `indikator`, badge
   YA/TIDAK, `catatan`, dan kutipan `evidence.quote` + `evidence.timestamp`.
   Item TIDAK diberi border penegas seperti pada mockup.
4. **Ringkasan** — paragraf `ringkasan` dari model
5. **Footer disclaimer** — hasil AI, wajib direview manusia, bukan keputusan
   resmi kepatuhan

Warna dan tipografi mengikuti `assets/mega.css` dan komponen dashboard yang ada,
bukan palet mentah file mockup, supaya menyatu dengan halaman lain. Layout
mendukung cetak (`@media print`).

**File existing yang disentuh (2):**

- `router/index.js` — dua route (`/dashboard/collection/results`,
  `/dashboard/collection/transcripts`) dan satu aturan guard role.
  Prefiks `/dashboard` wajib: guard existing pada `router/index.js:100`
  memulangkan role `qc` dari setiap path yang bukan diawali `/dashboard`, jadi
  route di luar prefiks itu akan mengunci QC dari fiturnya sendiri
- `components/SidebarMenu.vue` — satu grup menu "QC Collection" berisi dua item

### 6. Penanganan error

| Kondisi | Perilaku |
|---|---|
| `result_json.evaluation` berisi `{"error": ...}` (guard prompt: kb bukan 7 item / input kosong) | banner "Hasil tidak dapat dibaca" + pesan mentah; baris tetap ada di daftar |
| Tidak ada key `checklist_result` | sama seperti di atas — tidak crash, tidak render sebagian |
| `total_dinilai != 7` | ditampilkan apa adanya + badge peringatan |
| `checklist_result` kurang/lebih dari 7 item | dirender sesuai isi, diurutkan `no` menaik; badge peringatan |
| `evidence.quote` / `timestamp` `null` | tampilkan "Tidak ada kutipan (lihat catatan)" |
| status `pending` / `processing` / `failed` | baris tampil dengan badge status; area detail kosong beserta pesan status |
| `COLLECTION_CAMPAIGNS` kosong | kedua daftar kosong; tidak ada perubahan perilaku di fitur existing |

### 7. Testing

| Berkas | Cakupan |
|---|---|
| `tests/test_campaign_kind.py` (baru) | parsing daftar campaign: spasi, huruf besar-kecil, entri kosong, string kosong |
| `tests/test_pdf_parser.py` (tambah) | `speaker_stats` atas header `AGENT_BM (female) [NETRAL]:`; header lama `[SPEAKER_1]:` menghasilkan gender/emosi `None`; `messages` tetap kompatibel dengan `format_transcript_for_llm` |
| `tests/test_collection_router.py` (baru) | tiket collection tidak muncul di `/list_results` dan `/list_transcripts`; tiket sales tidak muncul di `/collection/list_results`; filter `hasil`; penolakan role di luar daftar |
| `dashboard/src/views/collection/collectionSummary.test.mjs` (baru) | fungsi murni penurun summary (`hasil_akhir`, `failed_indicators`, urutan checklist) dari `evaluation`, mengikuti pola `views/qc/assignTicketData.test.mjs` |

## Konsekuensi yang diterima

**Statistics tidak disentuh (keputusan eksplisit).** `compliance/stats_aggregate.py`
memindai seluruh result berstatus `done` dan mengelompokkannya per nama campaign.
Karena evaluasi collection tidak punya `scorecard_result`, `passing_grade`,
maupun `ai_status`, `base_ai_status()` mengembalikan `None`. Akibatnya, untuk tiap
tiket collection:

- muncul baris campaign baru pada "Performa Campaign" dan pada dropdown filter
  campaign di halaman Overview;
- `submissions` dan `evaluated` bertambah, sementara `errors`, `approve`, dan
  `return` tetap 0;
- karena pemetaan agen memakai `cid` → sales agent, tiket collection kemungkinan
  besar jatuh ke bucket agen `UNKNOWN`.

Tidak ada error atau crash — hanya angka yang menyesatkan bila jumlah tiket
collection menjadi besar. Bila kelak ingin dibersihkan, satu argumen
`exclude_campaigns` pada pembangun snapshot sudah cukup; itu di luar lingkup
spec ini.

**Tanpa tindak lanjut QC.** Tiket collection tidak bisa dibanding, tidak bisa
diubah statusnya, dan tidak bisa ditugaskan ke QC. Tabel `ErrorCodeAppeal`,
`QcStatusRequest`, dan `QcAssignment` terikat pada kode `SC_CL_*` / Error Code
sales, sehingga menggunakannya untuk collection memerlukan perubahan skema yang
berada di luar batasan "read-only".

**Audio berjalan lewat App A.** Upload Audio memanggil
`/api/v1/speech/stt/save_dashboard` di App A, yang saat ini tidak mengirim field
`campaign` dan jatuh ke `DEFAULT_UPLOAD_TRANSCRIPT_CAMPAIGN`. Agar panggilan
collection masuk sebagai campaign collection, nilai itu harus diatur di sisi App
A — di luar repo ini, dan bukan perubahan pada dashboard. Jalur transkrip PDF
(`/upload_transcript`) sudah bisa memilih campaign tanpa perubahan apa pun.

## Ringkasan dampak berkas

**Baru (9):** `compliance/campaign_kind.py`, `api/routers/collection.py`,
`dashboard/src/views/collection/CollectionResultsView.vue`,
`dashboard/src/views/collection/CollectionTranscriptsView.vue`,
`dashboard/src/views/collection/collectionSummary.js` (+ `.test.mjs`),
`dashboard/src/components/CollectionEvaluationView.vue`,
`tests/test_campaign_kind.py`, `tests/test_collection_router.py`

**Diubah (11):** `.env` + `.env.example`, `api/dependencies.py`,
`worker/config.py`, `worker/tasks/process_transcript.py`,
`compliance/pdf_parser.py`, `db/crud.py`, `api/routers/stats.py` (1 argumen),
`api/routers/transcript.py` (1 argumen), `dashboard/src/router/index.js`,
`dashboard/src/components/SidebarMenu.vue`

Tidak ada migration, tidak ada tabel baru, tidak ada bucket baru.
`EvaluationView.vue`, `ResultsView.vue`, `TranscriptsView.vue`, `StatsView.vue`,
`error_codes.py`, `scoring.py`, `stats_aggregate.py`, dan `evaluator.py` tidak
disentuh.
