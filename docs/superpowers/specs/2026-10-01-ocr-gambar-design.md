# OCR Gambar — Design

Tanggal: 2026-10-01 · Status: disetujui secara lisan, menunggu review spec

## 1. Tujuan

Alat OCR **mandiri** untuk Admin dan user campaign **Complaint Handling**: upload satu
atau beberapa gambar, sistem mengeluarkan teks yang tertulis di gambar itu apa
adanya, dan teksnya bisa disalin atau diunduh. Gambar dan teks disimpan sebagai
riwayat yang bisa dibuka lagi.

Tidak terhubung ke tiket, result, maupun penilaian QC.

### Keputusan user (2026-10-01)

| Topik | Keputusan |
|---|---|
| Kegunaan | Alat OCR mandiri (bukan bahan QC, bukan lampiran tiket) |
| Penyimpanan | Simpan riwayat (gambar + teks) |
| Jumlah per upload | Beberapa gambar sekaligus |
| Visibilitas riwayat | User melihat miliknya sendiri; Admin melihat semua |
| Format output | Teks apa adanya (markdown; baris & tabel dipertahankan) |
| Mesin OCR | Model vision LLM yang sudah ada (`LLM_*`, Azure `gpt-5.4-mini`) |
| Format | Semua gambar raster yang terbaca Pillow + HEIC/HEIF (revisi 2026-10-01, lihat §5a); SVG tidak |
| Multi-halaman | TIFF multi-halaman dipecah: tiap halaman satu entri; GIF animasi/MPO hanya frame pertama |
| Batas | maks 10 file asli × 10 MB, DAN maks 10 entri hasil pecahan per upload |
| Retensi | Tanpa batas waktu (tidak ada penghapusan otomatis) |

### Mengapa LLM vision, bukan `compliance.ocr`

`OCR_BASE_URL`/`OCR_MODEL` kosong di worker prod dan tabel `documents` belum pernah
berisi baris — pipeline Mistral Document AI belum pernah jalan di server ini.
Spike 2026-10-01 (gambar sintetis tanpa data nasabah) lewat
`worker.tasks.process_transcript._llm_client()`: deployment menerima gambar,
±2,5 detik, ±265 token input + 60 output, teks dan tabel markdown tersalin benar.

## 2. Di luar cakupan

- OCR file PDF.
- SVG / gambar vektor.
- Ekstraksi field terstruktur (nama, no. kartu, dst.).
- Penghapusan riwayat otomatis.
- Mengubah pipeline OCR dokumen pendukung (`process_document`).
- Menawarkan `menu.ocr_image` sebagai checkbox di Manage Role.

## 3. Akses

- Permission baru `menu.ocr_image` (`MENU_OCR_IMAGE` di `api/permissions.py`,
  `P.MENU_OCR_IMAGE` di `telemarketing-qc-dashboard/src/permissions.js`).
- **Admin / Demo** (`ADMIN_LIKE_ROLES`): masuk `_ADMIN_PERMISSIONS`, dan migrasi
  `0064` menambahkannya ke baris `roles` `admin` dan `demo` yang sudah ada.
  `menu.ocr_image` juga masuk `ADMIN_ONLY_PERMISSIONS`, sehingga tidak bisa
  diberikan ke role lain lewat Manage Role.
- **User lain**: dihitung saat request di `api.rbac.permissions_for` — ditambahkan
  bila campaign efektif user (`effective_campaigns_for`) beririsan, case-insensitive,
  dengan env baru `OCR_IMAGE_CAMPAIGNS` (api `.env`, dipisah koma, dibaca tiap
  panggilan seperti `collection_campaigns_from_env`). Prod:
  `OCR_IMAGE_CAMPAIGNS=Complaint Handling`.
  - Kosong = hanya Admin/Demo yang punya; itu juga bentuk rollback.
  - Grup virtual `Telemarketing` TIDAK dihitung sebagai anggota — hanya nama
    campaign yang tertulis eksplisit di `user_campaigns`/`role_campaigns`.
- Tidak masuk `PERMISSION_GROUPS` (tidak bisa dicentang di Manage Role), supaya
  sumber pemberiannya hanya dua di atas.
- Karena `permissions_for` memberi makan `/auth/me` (menu) dan `require(...)`
  (endpoint), menu dan endpoint tertutup bersamaan.

## 4. Data

### Tabel `dashboard.ocr_images` (migrasi `0064_ocr_images`)

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | int FK `users.id`, not null, index | pengunggah |
| `batch_id` | uuid, not null, index | satu request upload |
| `filename` | varchar(255) | nama asli |
| `object_path` | varchar(512) | `ocr-images/{id}.{ext}` |
| `mime_type` | varchar(64) | `image/jpeg` / `image/png` |
| `size_bytes` | int | |
| `status` | varchar(16), not null, default `pending` | `pending` / `processing` / `done` / `failed` |
| `text` | text, null | hasil OCR |
| `error_message` | text, null | |
| `token_usage` | json, null | bentuk sama dengan `_extract_usage` |
| `created_at` | DateTime (naive, UTC — sama dengan tabel lain) | |
| `started_at` | DateTime (naive, UTC — sama dengan tabel lain) | |
| `finished_at` | DateTime (naive, UTC — sama dengan tabel lain) | |

Index `(user_id, created_at desc)` untuk daftar riwayat.

Migrasi yang sama menambahkan `menu.ocr_image` ke `permissions` role `admin` dan
`demo`; downgrade membuang keduanya dan men-drop tabel.

### Model ORM

`OcrImage` ditambahkan ke `core/db/models.py` di **tiga** salinan yang harus identik:
`telemarketing-qc-api/core`, `telemarketing-qc-worker/core`, dan
`telemarketing-qc-core/src/qc_core` (core tetap vendored, sinkron manual).

### Penyimpanan file

Bucket `MINIO_BUCKET_DOCUMENTS` yang sudah ada, prefix `ocr-images/`. Tanpa bucket
atau env MinIO baru.

## 5. API (`api/routers/ocr_image.py`, semua `require(MENU_OCR_IMAGE)`)

| Method & path | Perilaku |
|---|---|
| `POST /ocr_images` | multipart `files[]`. Validasi + normalisasi SEMUA file dulu (1–10 file asli, ≤10 MB per file, isi terbaca sebagai gambar, ≤10 entri setelah pemecahan halaman — §5a); satu gagal → 422, tidak ada yang disimpan. Lalu per file: put MinIO, insert baris `pending`, `send_task(...)`. Bila menyimpan ke MinIO/DB gagal di tengah jalan, semua yang sudah tersimpan dibersihkan (rollback DB, hapus objek MinIO) dan API mengembalikan 503 "Gagal menyimpan gambar, silakan coba lagi". Bila antrian task gagal untuk satu baris, baris itu ditandai `failed` dengan pesan error "Gagal masuk antrean proses — klik Proses ulang" dan respons tetap 200 (batch partial). Respons: `batch_id` + daftar `{id, filename, status}`. |
| `GET /ocr_images?page=&page_size=` | Riwayat terbaru dulu, tanpa kolom `text` (ringkas). Non-admin: hanya `user_id` = dirinya. Admin: semua + `uploader_name`. |
| `GET /ocr_images/{id}` | Detail termasuk `text`, `error_message`. |
| `GET /ocr_images/{id}/image` | Stream gambar asli dari MinIO dengan `mime_type`. Header Content-Disposition: `inline; filename="<ascii fallback>"; filename*=UTF-8''<percent-encoded>` (RFC 6266/5987). |
| `POST /ocr_images/{id}/retry` | Hanya bila `failed`: reset ke `pending`, kirim ulang task. Bila antrian gagal, baris ditandai `failed` lagi dan API mengembalikan 503 "Gagal masuk antrean proses, silakan coba lagi". |
| `DELETE /ocr_images/{id}` | Hapus objek MinIO + baris. |

Kepemilikan: baris milik user lain → **404** (bukan 403) untuk non-admin, pada
semua endpoint per-id.

## 5a. Normalisasi gambar & pesan error

Dijalankan API saat upload, sebelum apa pun disimpan; worker, model, dan browser
hanya pernah menerima JPEG/PNG/WEBP.

- Validasi berdasarkan ISI file (Pillow `open`), bukan ekstensi. HEIC/HEIF lewat
  `pillow-heif==1.8.0` (`register_heif_opener()`), dependency baru di
  `api/requirements.txt` + `api/constraints.txt`.
- Halaman: format `TIFF` dengan `n_frames > 1` → satu entri per halaman, nama
  tampilan `"<nama asli> (hal. i/n)"`. Format lain → frame pertama saja.
- Satu halaman disimpan APA ADANYA bila formatnya JPEG/PNG/WEBP, file tunggal
  (satu frame), dan sisi terpanjang ≤ 4096 px. Selain itu dikonversi: orientasi
  EXIF diterapkan, transparansi diratakan ke latar putih, sisi terpanjang
  diperkecil ke ≤ 4096 px, disimpan JPEG kualitas 90 (`image/jpeg`, `.jpg`).
  JPEG dipilih — bukan PNG — supaya foto HEIC/TIFF besar tidak membengkak melewati
  batas request model.
- `size_bytes` = ukuran hasil normalisasi yang disimpan.

**Kode error:**

| Endpoint | Status | Pesan |
|---|---|---|
| **`POST /ocr_images`** | **422** | `Pilih minimal satu gambar` |
| | **422** | `Maksimal 10 gambar per upload` |
| | **422** | `File '<nama>' melebihi 10 MB` |
| | **422** | `File '<nama>' bukan gambar yang bisa dibaca` |
| | **422** | `Maksimal 10 gambar per upload (termasuk tiap halaman TIFF; total <n>)` |
| | **503** | `Gagal menyimpan gambar, silakan coba lagi` (storage fail, semua dibersihkan) |
| **`GET /ocr_images/{id}`** | **404** | `Gambar tidak ditemukan` (bukan milik user atau tidak ada) |
| **`GET /ocr_images/{id}/image`** | **404** | `Gambar tidak ditemukan` atau `File gambar tidak ditemukan di storage` |
| **`POST /ocr_images/{id}/retry`** | **404** | `Gambar tidak ditemukan` (bukan milik user atau tidak ada) |
| | **409** | `Hanya gambar berstatus gagal yang bisa diproses ulang` |
| | **503** | `Gagal masuk antrean proses, silakan coba lagi` (queue fail pada retry) |
| **`DELETE /ocr_images/{id}`** | **404** | `Gambar tidak ditemukan` (bukan milik user atau tidak ada) |

## 6. Worker (`worker/tasks/process_ocr_image.py`)

1. Ambil baris; bila tidak ada atau status `done` atau `failed` → selesai (idempoten
   terhadap redelivery). Status `failed` hanya kembali ke `pending` lewat endpoint
   retry yang me-reset ke `pending` sebelum mengirim ulang task.
2. Set `processing` + `started_at`.
3. Unduh gambar dari MinIO, base64.
4. `_llm_client().chat.completions.create(model=LLM_MODEL, messages=[system, user])`:
   - system: *"You are an OCR engine. Transcribe ALL text in the image verbatim,
     preserving line breaks and reading order; render tables as markdown tables.
     Do not translate, summarize, correct, or add commentary. If the image has no
     text, output exactly: (tidak ada teks)"*
   - user: satu `image_url` data URI.
   - TANPA `reasoning_effort` (sama seperti spike: transkripsi tidak butuh
     penalaran; `LLM_REASONING_EFFORT` worker tetap hanya untuk penilaian).
5. Simpan `text`, `token_usage`, `done`, `finished_at`. Exception → `failed` +
   `error_message` (dipotong 1000 karakter), dicatat `logger.exception`; tidak
   ada auto-retry Celery (user memakai tombol Proses ulang).

Didaftarkan di `include=[...]` `worker/celery_app.py`. Kube worker
(10.158.3.13) memakai Redis sendiri, jadi task ini tidak pernah sampai ke sana.

## 7. Dashboard

- Route `/upload/ocr-image` → `views/upload/OcrImageView.vue`, dipetakan ke
  `P.MENU_OCR_IMAGE` di `permissions.js`; entri "OCR Gambar" di `SidebarMenu.vue`
  pada kelompok Upload.
- Halaman:
  - Area drag-drop / pilih file (multi, `accept="image/*,.heic,.heif"`), validasi
    jumlah/ukuran/jenis di klien dengan pesan yang sama seperti API.
  - Tabel riwayat: thumbnail kecil, nama file, waktu, status (badge), pengunggah
    (Admin saja), aksi Lihat / Proses ulang (failed) / Hapus (konfirmasi).
  - Polling `GET /ocr_images` tiap 3 detik selama ada baris `pending`/`processing`
    di halaman yang tampil; berhenti bila tidak ada.
  - Panel detail: gambar asli di kiri, teks di kanan (`<pre>` monospace,
    whitespace dipertahankan), tombol **Salin** dan **Unduh .txt**
    (`<nama-file-tanpa-ekstensi>.txt`).

## 8. Konfigurasi & deploy

- api `.env`: `OCR_IMAGE_CAMPAIGNS=Complaint Handling`. Worker tidak butuh env baru.
- Urutan: migrasi `0064` → api → worker → dashboard. Prosedur biasa: build
  candidate, diff freeze, smoke, retag (constraints.txt untuk pin dependency).
- Pillow sudah ada di image api (12.3.0). Dependency baru: `pillow-heif==1.8.0`
  (HEIC/HEIF), image qc-api harus di-build ulang.
- Rollback: kosongkan `OCR_IMAGE_CAMPAIGNS` dan/atau kembalikan image; tabel boleh
  tetap ada.

## 9. Pengujian

- **api (unit, dijalankan di image qc-api):**
  - `permissions_for`: Admin punya; user dengan campaign `Complaint Handling`
    punya; user `Telemarketing`/`Collection` tidak; env kosong → hanya Admin.
  - Upload: 11 file / file 11 MB / file teks berekstensi `.png` / TIFF 11 halaman → 422 dan tidak ada baris
    tersimpan; upload valid → baris `pending` + `send_task` dipanggil per file
    (celery & MinIO di-stub).
  - Isolasi: user A tidak melihat riwayat user B (list kosong, detail 404);
    Admin melihat keduanya.
  - Retry hanya untuk `failed`; delete menghapus objek MinIO.
- **worker (unit):** LLM di-stub → `done` + teks tersimpan; LLM melempar →
  `failed` + `error_message`; baris `done` tidak diproses ulang.
- **E2E (`./jalankan.sh`, stub LLM):** login user Complaint Handling → upload
  2 gambar → keduanya `done` → teks tampil; user Telemarketing tidak melihat menu
  dan `POST /ocr_images` → 403.
