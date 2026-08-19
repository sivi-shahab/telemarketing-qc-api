# Referensi API & Autentikasi — Telemarketing QC System

Ringkasan endpoint REST, mekanisme autentikasi, dan **permission guard**. Dokumentasi
interaktif lengkap tersedia otomatis:

- **Swagger UI**: `http://<host>:4010/docs`
- **ReDoc**: `http://<host>:4010/redoc`
- **OpenAPI JSON**: `http://<host>:4010/openapi.json`

> Ingat: dari host, API di **port 4010** (di dalam Docker: 4000). Judul app:
> "Bank Call Center QA System" v1.0.0. Saat ini terdaftar **68 operasi** pada **65 path**.

> Diverifikasi 12 Agustus 2026 dengan introspeksi langsung `app.routes` + `route.dependant`
> pada container `api` yang berjalan — bukan pembacaan manual. Bila menambah endpoint,
> perbarui tabel §4.

---

## 1. Autentikasi

### JWT (utama)

- **Login**: `POST /auth/login` — form `username` + `password` (OAuth2 password flow) →
  `{ access_token, refresh_token }`. Payload token: `{"sub": <user_id>, "type": "access"|"refresh"}`.
- **Refresh**: `POST /auth/refresh` — body `{ refresh_token }` → access token baru.
- **Algoritma**: `HS256`, secret `JWT_SECRET_KEY`. Library: `python-jose`.
- **Expiry**: access `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 60), refresh `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (default 7).
- **Transport**: header `Authorization: Bearer <token>`, atau query `?token=<token>` (fallback untuk
  navigasi langsung/iframe, mis. viewer PDF transkrip).
- **Password**: di-hash bcrypt (passlib `CryptContext(schemes=["bcrypt"])`).

### X-API-Key (sistem / integrasi)

- Header `X-API-Key` dibandingkan dengan `API_KEY`. Bila valid, `get_current_user`
  mengembalikan `SystemUser` sintetis (id=0, role `spq_head`, `data_scope: all`, tanpa
  pembatasan campaign). Dicek **lebih dulu** dari JWT.
- Karena `SystemUser` berjalan sebagai `spq_head`, ia **tidak** punya `admin.user.write` /
  `admin.role.write` — endpoint Manage User & Manage Role tetap tertutup untuk integrasi
  (lihat §2).
- ⚠️ Endpoint **webhook** (`/webhook/process_ticket`) saat ini **tanpa auth sama sekali**
  (bukan X-API-Key, bukan JWT). Lindungi via reverse proxy. Lihat [`INTEGRATION.md`](./INTEGRATION.md).

### CORS

`allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.

---

## 2. Model Otorisasi: Capability, bukan Nama Role

Sejak migrasi `0031_roles_permissions`, gate **tidak lagi** membandingkan `user.role` dengan
daftar string. Otorisasi dipecah tiga:

| Dimensi | Menjawab | Sumber |
|---|---|---|
| **permission** (capability) | boleh melakukan APA | tabel `roles.permissions`, seed di `api/permissions.py::DEFAULT_ROLES` |
| **data_scope** | boleh melihat tiket SIAPA | `roles.data_scope` → `api/qc_scope.py` |
| **campaign** | boleh melihat campaign MANA | `role_campaigns` + `user_campaigns` → `api/rbac.py::effective_campaigns_for` |

Guard endpoint memakai `require("<permission>")` (`api/dependencies.py::_require` →
`api/rbac.py::permissions_for`). Gagal → **403** `"Akses ditolak: role Anda tidak memiliki izin
untuk tindakan ini"`.

Peninggalan lama `get_*_user` masih ada untuk dua kasus saja:

| Dependency | Dipakai di | Perilaku |
|---|---|---|
| `get_current_user` | semua endpoint ber-auth | resolve JWT/X-API-Key → user |
| `get_agent_error_summary_user` | `GET /agent_error_summary/{result_id}` | login saja, sengaja terbuka untuk semua role |

> Dokumen lama menyebut `get_spq_head_user`, `get_tl_qc_or_spq_head_user`,
> `get_document_uploader_user`, dsb. **Guard-guard itu sudah tidak dipakai lagi** sebagai
> gate endpoint — jangan dijadikan acuan.

### Pembatasan campaign berlaku di ATAS data_scope

Sejak 12 Agustus 2026, `scoped_customer_ids` mengiris **semua** cakupan dengan campaign yang
boleh dilihat role/user (`narrow_to_campaigns`). Artinya role ber-`data_scope: all` yang
diberi tag campaign tertentu tidak lagi melihat tiket, statistik, maupun export di luar
campaign itu. Sebelumnya irisan ini hanya terpasang di `list_results`.

Endpoint yang ikut dibatasi campaign: `/list_results`, `/list_transcripts`, `/stats*`,
`/stats/qc_performance`, `/stats/failure_reasons[_hierarchy]`, `/stats/ai_status_timeseries`,
`/export_verification_xlsx`, `/get_nama_ibu_kandung`.

---

## 3. Daftar Permission (51)

Dikelompokkan sesuai form **Manage Role** (`GET /roles/catalog`).

> 🔒 Sejak 14 Agustus 2026 **19 dari 51 permission bersifat admin-only** dan
> **tidak dikembalikan** oleh `GET /roles/catalog` — form Manage Role hanya menawarkan 32.
> `POST /roles` & `PUT /roles/{id}` menolak `422` bila permission itu dikirim untuk role
> selain `admin`. Daftar & alasannya: `ADMIN_ONLY_PERMISSIONS` di `api/permissions.py`,
> [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §4.1.

| Kelompok | Permission |
|---|---|
| **Menu** | `menu.stats`, `menu.results`, `menu.transcripts`, `menu.assign_ticket`, `menu.manual_check`, `menu.pending_check`, `menu.role_hierarchy`, 🔒 `menu.campaigns`, 🔒 `menu.sales_database`, 🔒 `menu.qc_database`, 🔒 `menu.upload_campaign`, 🔒 `menu.upload_audio`, 🔒 `menu.upload_transcript`, 🔒 `menu.get_result`, 🔒 `menu.upload_sales_database`, 🔒 `menu.upload_qc_database`, 🔒 `menu.delete_campaign`, 🔒 `menu.manage_user`, 🔒 `menu.manage_role` |
| **Results** | `results.evaluation_detail`, `results.critical_failure`, `results.category_score`, `results.manual_status.column`, `results.manual_status.set`, `results.manual_status.direct`, `results.manual_status.review_tl`, `results.manual_status.review_spq`, `results.error_code.appeal`, `results.error_code.direct_edit`, `results.error_code.review_tl`, `results.error_code.review_spq`, `results.document.upload`, `results.document.view`, `results.document.verification`, `results.manual_check.approve`, `results.filter.qc_side`, `results.export.verification`, `results.export.tickets` |
| **Stats** | `stats.qc_performance`, `stats.failure_reason`, `stats.risk_base`, `stats.risk_system_new` |
| **Upload** | 🔒 `transcript.upload`, 🔒 `audio.upload` |
| **QC** | `qc.assignment.write` |
| **Admin** | `admin.ticket.delete`, 🔒 `admin.campaign.write`, 🔒 `admin.user.write`, 🔒 `admin.role.write`, 🔒 `admin.sales_database.write`, 🔒 `admin.qc_database.write` |

Pemetaan permission → role bawaan: [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §4.

---

## 4. Daftar Endpoint per Router

Kolom **Guard** = permission efektif hasil introspeksi. `login` = hanya `get_current_user`
(cakupan datanya tetap dipersempit `data_scope` + campaign).

### Auth — `/auth`
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /auth/login` | Login → access+refresh token | publik |
| `POST /auth/refresh` | Tukar refresh → access baru | publik |
| `GET /auth/me` | Info user saat ini | login |
| `POST /auth/create_user` | Buat user | `admin.user.write` |
| `GET /auth/users` | Daftar user | `admin.user.write` |
| `DELETE /auth/users/{user_id}` | Hapus user | `admin.user.write` |

### Role & Permission — `/roles`
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /roles` | Daftar role + permission-nya | `admin.role.write` |
| `POST /roles` | Buat role baru | `admin.role.write` |
| `PUT /roles/{role_id}` | Ubah role (permission, data_scope, campaign) | `admin.role.write` |
| `DELETE /roles/{role_id}` | Hapus role | `admin.role.write` |
| `GET /roles/catalog` | Kosakata form Manage Role (permission, scope, campaign) — **tanpa** permission admin-only | `admin.role.write` |
| `GET /roles/user_campaigns` | Daftar user + campaign khusus per user | `admin.role.write` |
| `PUT /roles/user_campaigns/{username}` | Set campaign seorang user (kosong = tanpa batas) | `admin.role.write` |

> **`422` pada `POST`/`PUT /roles`** bila body memuat permission admin-only untuk role selain
> `admin` — pesan: *"Permission berikut hanya untuk role Admin: …"*. Sebaliknya, menyimpan
> role `admin` lewat form **tidak** mencabut capability admin-only-nya: karena tidak ada di
> katalog, ia tidak ikut terkirim, dan `PUT` membawanya serta apa adanya dari DB.

### Transcript & Result
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /upload_transcript` | Upload PDF transkrip → buat result | login |
| `POST /upload_audio` | Upload audio | login |
| `GET /result/{result_id}` | Detail evaluasi (skor + tabel error code) | `results.evaluation_detail` |
| `GET /list_transcripts` | Daftar transkrip (ter-scope) | login |
| `GET /transcript_pdf/{result_id}` | Stream PDF (mendukung `?token=`) | login |
| `GET /download_transcript/{transcript_id}` | Download PDF asli | login |

### Campaign
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /upload_detail_campaign` | Upload konfigurasi campaign (+ RIPLAY opsional) | `admin.campaign.write` |
| `GET /list_campaigns` | Daftar campaign | login |
| `GET /get_campaign` | Detail campaign (isi teks + nama file asli) | login |
| `DELETE /delete_campaign` | Hapus campaign + arsip MinIO (query `?campaign=`) | `admin.campaign.write` |
| `GET /campaign_readiness` | Kesiapan tiap campaign: konfigurasi QC, roster, akun, data TMS, tiket | `admin.campaign.write` |

> Perubahan penting: upload campaign **tidak lagi** terbuka untuk semua user login — kini
> butuh `admin.campaign.write`, dan sejak 14 Agustus 2026 capability itu **hanya milik
> `admin`** (SPQ Head sudah tidak punya).

### Document
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /upload_document` | Upload dokumen pendukung (KTP/KK/NPWP/buku tabungan) | `results.document.upload` |
| `GET /documents/{result_id}` | Daftar dokumen result | `results.document.view` |
| `GET /document_file/{document_id}` | Ambil file dokumen | `results.document.view` |

> Tabel perbandingan OCR-vs-acuan di modal "View Document" dijaga permission terpisah
> `results.document.verification`. Penyembunyiannya **bukan di frontend**: `/documents/{id}`
> mengosongkan `ocr_json` & `error_message` untuk role tanpa capability itu, jadi datanya
> tidak pernah sampai ke browser. Yang memilikinya hanya **QC, Team Leader QC, SPQ Head** —
> **Admin dan Team Leader Sales bisa membuka dokumennya tetapi tidak melihat vonisnya.**
>
> Sejak 14 Agustus 2026 **Sales Agent tidak punya `results.document.view`** → kedua endpoint
> di atas membalas `403`, dan kolom **Document** di halaman Results hilang untuk role yang
> tidak punya `view` maupun `upload`.

### Webhook
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /webhook/process_ticket` | Ingest PDF sesi by `ticket_id`+`product` → enqueue evaluasi | **TANPA AUTH** ⚠️ |

### Results & Stats
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /list_results` | Daftar result (ter-scope role + campaign) | login |
| `GET /results/hierarchy_options` | Opsi filter hierarki sales | login |
| `GET /stats` · `/stats/overview` · `/stats/daily` · `/stats/campaigns_monthly` · `/stats/hierarchy` · `/stats/role_counts` · `/stats/my_overview` | Agregasi Statistics (snapshot, ter-scope) | login |
| `GET /stats/ai_status_timeseries` | Timeseries AI Status (`granularity`, `start`, `end`, `campaign`, `offset`) | login |
| `GET /stats/failure_reasons` | Kategori scorecard paling sering gagal | `stats.failure_reason` (dicek `has_perm`, bukan `require`) |
| `GET /stats/failure_reasons_hierarchy` | Failure Reason dipecah per hierarki sales | `stats.failure_reason` (idem) |
| `GET /stats/qc_performance` | Tabel assigned/approved/approve-rate per QC | `stats.qc_performance` |
| `POST /stats/refresh` | Paksa recompute snapshot Statistics | login |
| `DELETE /delete_ticket` | Hapus tiket/result (query `?ticket_id=`) | `admin.ticket.delete` |

> `stats.failure_reason` ditegakkan **di dalam** fungsi lewat `has_perm(...)` lalu
> `raise HTTPException(403)`, bukan lewat `Depends(require(...))`. Efeknya sama, tapi
> permission-nya tidak muncul di OpenAPI.

### Export
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /export_result_xlsx/{result_id}` | Export satu hasil evaluasi ke XLSX (3 sheet: `ringkasan_penilaian_ai`, `scorecard`, `errorcard`) | login |
| `GET /export_verification_xlsx` | Export agregat satu kategori verifikasi ke XLSX | `results.export.verification` |
| `GET /export_tickets_xlsx` | Export **semua tiket** pada rentang & filter terpilih ke XLSX | `results.export.tickets` |
| `GET /get_nama_ibu_kandung` | Hasil verifikasi statik nama ibu kandung SEMUA tiket (JSON) | `results.export.verification` |

Detail ketiga endpoint terakhir: §5.

> Baris **"Hasil"** di sheet `ringkasan_penilaian_ai` memakai `ai_status_for_result()` —
> sumber yang **sama** dengan kolom AI Status di `/list_results`, termasuk aturan dokumen H+2
> dan Manual Status yang sudah disetujui. Sebelum 14 Agustus 2026 sheet ini menyimpulkan
> sendiri dari dict evaluasi dan buta terhadap keduanya, sehingga 21 dari 98 tiket ter-export
> "LULUS" padahal Not Qualified. Lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7.2.

### Agent Error
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /agent_error_summary/{result_id}` | Ringkasan error per agent | login (semua role) |

### Manual Status (dulu "QC Status Request")
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /qc_status_request` | Tetapkan/ajukan Manual Status sebuah tiket | `results.manual_status.set` |
| `POST /qc_status_request/{result_id}/tl_review` | TL QC review (approve/reject/escalate) | `results.manual_status.review_tl` |
| `POST /qc_status_request/{result_id}/review` | SPQ Head review final | `results.manual_status.review_spq` |
| `GET /qc_status_events/{result_id}` | Riwayat perubahan Manual Status satu tiket | login (+ `ensure_can_view_result`) |

### QC Manual Check (audit "sudah dicek manual")
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /qc_manual_check/{result_id}` | Catat manual check | `results.manual_check.approve` |
| `GET /qc_manual_check/{result_id}` | Riwayat manual check | login |

### Error Code Appeal (banding)
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /error_reasons` | Katalog master 46 error code (dropdown) | login |
| `POST /error_code_appeal` | QC ajukan banding | `results.error_code.appeal` |
| `POST /error_code_appeal/direct` | Edit langsung (tanpa hierarki) | `results.error_code.direct_edit` |
| `POST /error_code_appeal/{appeal_id}/tl_review` | TL QC review | `results.error_code.review_tl` |
| `POST /error_code_appeal/{appeal_id}/review` | SPQ Head review final | `results.error_code.review_spq` |

### QC Assignment
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /qc_assignment/qc_users` | Daftar QC yang bisa di-assign | `qc.assignment.write` |
| `GET /qc_assignments` | Daftar assignment | `qc.assignment.write` |
| `POST /qc_assignment` | Buat assignment | `qc.assignment.write` |
| `DELETE /qc_assignment/{ticket_id}` | Hapus assignment | `qc.assignment.write` |

### Database (Sales / QC)
| Method & Path | Fungsi | Guard |
|---|---|---|
| `POST /upload_sales_database` | Upload XLSX database sales (jadi satu-satunya aktif) | `admin.sales_database.write` |
| `GET /list_sales_databases` | Daftar database sales | `admin.sales_database.write` |
| `GET /sales_database/roster` | Isi roster database sales yang aktif | `admin.sales_database.write` |
| `POST /upload_qc_database` | Upload XLSX database QC | `admin.qc_database.write` |
| `GET /list_qc_databases` | Daftar database QC | `admin.qc_database.write` |

### Health
| Method & Path | Fungsi | Guard |
|---|---|---|
| `GET /health` | Liveness (`{"status":"ok"}`) | publik |

---

## 5. Endpoint Export

### 5.1 `GET /export_verification_xlsx`

Export agregat **satu kategori** verifikasi sebagai file XLSX: semua baris yang **tidak
cocok** pada tiket **Not Qualified & Pending**.

> Sejak 14 Agustus 2026 guard-nya **hanya Admin** — SPQ Head memakai §5.3.

| Param | Wajib | Nilai |
|---|---|---|
| `category` | ya | `verifikasi_statik` · `verifikasi_dinamik` · `cashline_verification` · `cardholder_verification` |
| `campaign` | tidak | batasi ke satu campaign |

Kolomnya menyesuaikan kategori (mis. Cashline Verification membawa "Ketentuan Produk" yang
tidak ada pada card holder) — lihat `compliance/stats_aggregate.py::compute_verification_export`.

### 5.2 `GET /get_nama_ibu_kandung`

Hasil verifikasi statik **nama ibu kandung** untuk **semua tiket**, sebagai JSON. **Tanpa
parameter apa pun.**

Bedanya dengan `export_verification_xlsx?category=verifikasi_statik`:

| | `/get_nama_ibu_kandung` | `/export_verification_xlsx` |
|---|---|---|
| Format | JSON | XLSX (download) |
| Cakupan tiket | semua tiket `done` yang punya baris `nama_ibu_kandung` | hanya tiket **Not Qualified & Pending** |
| Baris | **MATCH maupun MISMATCH** | hanya baris **MISMATCH** |
| Field | hanya `nama_ibu_kandung` | seluruh field kategori |

Similarity sudah **dihitung ulang di Python** (`normalize_static_verification`, memakai
penyebutan TERBAIK) dan **banding yang disetujui sudah diterapkan**, jadi angkanya sama
persis dengan yang tampil di dashboard — bukan angka mentah LLM. Pada baris yang angkanya
dikoreksi, `reason` **ikut ditulis ulang** supaya tidak menjelaskan vonis lama; baris yang
angkanya sudah benar tetap memakai kalimat LLM. Lihat
[`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1.

Tiket non-Cashline tersaring dengan sendirinya karena tidak punya blok
`card_holder_verification`. `ticket_id` diambil dari `source_files`, bukan langsung dari
`evidence.ticket_id` (LLM kadang menulis id nasabah tanpa timestamp); `evidence.ticket_id`
hanya dipakai bila cocok dengan salah satu file sumber — pada tiket multi-transkrip itulah
satu-satunya penunjuk file mana yang memuat kutipannya.

**Response** (`NamaIbuKandungResponse`):

| Field | Tipe | Arti |
|---|---|---|
| `total` | int | jumlah baris |
| `rows[]` | list | satu baris per tiket |
| `rows[].ticket_id` | str | id + timestamp file PDF |
| `rows[].submit_time` | str? | dari `tms_cashline.submit_time` |
| `rows[].ascend` | str? | acuan bank — `reference_value` pada blok `card_holder_verification` |
| `rows[].transkrip` | str? | penyebutan nasabah, bernomor + menit ke berapa |
| `rows[].match` | str? | `MATCH` · `MISMATCH` · `SKIPPED_NULL` |
| `rows[].evidence` | obj? | `{quote, timestamp, ticket_id}` — kutipan pada scorecard `SC_CL_23_2` |
| `rows[].similarity` | float? | 0–100 |
| `rows[].reason` | str? | alasan bila tidak cocok |

**Contoh:**

```bash
curl -H "X-API-Key: $API_KEY" http://<host>:4010/get_nama_ibu_kandung
```

```json
{
  "total": 99,
  "rows": [
    {
      "ticket_id": "010550Vosa_20260714153335",
      "submit_time": "2026-07-14 16:38:58",
      "ascend": "TRI WAHJOENINGSIH T",
      "transkrip": "1. [06:51] Tri Wahyuningsih Tirtosimono\n2. [07:01] Tri Wahyuningsih Tirtosimono\n3. [09:18] Tri Wahyuningsih Tirtosimono",
      "match": "MISMATCH",
      "evidence": {
        "quote": "… Untuk nama ibu kandungnya buat recordingnya boleh satu kali lagi pelan-pelan / Tri Wahyuningsih Tirtosimono",
        "timestamp": "09:09.60 - 09:21.54",
        "ticket_id": "010550Vosa_20260714153335"
      },
      "similarity": 54.0,
      "reason": "Nama ibu kandung yang disebut nasabah tidak sesuai Ascend …"
    }
  ]
}
```

### 5.3 `GET /export_tickets_xlsx` (14 Agustus 2026)

Export **semua tiket** pada rentang & filter yang sedang dipilih di halaman Results, sebagai
XLSX — **satu baris per tiket**, apa pun statusnya. Pengganti tombol Export Agregat bagi
SPQ Head.

Bedanya dengan §5.1: yang itu menjawab *"tunjukkan semua temuan pada SATU kategori
verifikasi"*, yang ini *"berikan SELURUH tiket periode ini"* — tiket **Qualified pun ikut**,
karena pertanyaannya bukan "apa yang harus ditindaklanjuti".

| Param | Wajib | Arti |
|---|---|---|
| `date_start` / `date_end` | tidak | `YYYY-MM-DD`; dasarnya `tms_cashline.submit_time`, sama dengan filter tanggal di Results |
| `campaign` | tidak | batasi ke satu campaign |
| `ai_status` / `manual_status` | tidak | `PASS` · `FAIL` · `PENDING` |
| `ticket_id` | tidak | pencarian sebagian id |
| `am_nip` / `tl_nip` / `agent_nip` | tidak | filter hierarki AM / TL / TLO |

Semua parameter memakai helper yang **sama** dengan `/results` (cakupan role, batas campaign,
filter hierarki), jadi isi file cocok dengan yang terlihat di layar. Yang tidak ditiru:
paginasi — export selalu mengambil seluruh rentang.

**Kolom** (`TICKET_EXPORT_COLUMNS` di `compliance/stats_aggregate.py`):

| Kolom | Catatan |
|---|---|
| Ticket ID, Tanggal, Campaign | `Tanggal` = `submit_time`; tiket tanpa baris cashline memakai `generated_at` |
| Agent, Team Leader, Area Manager | dari roster Sales Database |
| AI Status, Manual Status | kata yang dibaca manusia (Qualified / Not Qualified / Pending) |
| Passing Grade | dari evaluasi |
| Error Code | semua kode tiket itu, dipisah koma |
| Risk Base | risk base yang **benar-benar dihitung** (satu tertinggi, sudah termasuk pelunakan new joiner & pengecualian L-tolerable). Kosong = tiket tidak menyumbang Total Risk |
| Details Error | deskripsi tiap kode, dipisah baris baru |

Tiga kolom terakhir memampatkan tabel Error Code sebuah tiket ke satu baris, dan `Risk Base`
sengaja memakai definisi yang sama dengan Error Rate di Statistics supaya angkanya sepakat —
lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §8.1.

Ambang kecocokannya (band `>= 90` MATCH, `80..<90` minta dokumen KK, `< 80` MISMATCH)
dijelaskan di [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1.

---

## 6. Catatan Keamanan untuk Handover

1. **Webhook tanpa auth** — `POST /webhook/process_ticket` publik. Lindungi di reverse proxy
   (allowlist IP / secret path) atau tambahkan `verify_api_key`.
2. **CORS `*`** — cocok untuk internal; batasi origin bila diekspos publik.
3. **Rotasi secret** — `JWT_SECRET_KEY` & `API_KEY` wajib diganti dari default `changeme*`.
4. **Hanya `admin` yang bisa mengelola user & role** (sejak 10 Agustus 2026). Pastikan selalu
   ada akun Admin aktif — SPQ Head tidak bisa memulihkannya.
5. **`X-API-Key` = SPQ Head penuh** tanpa pembatasan campaign. Perlakukan sebagai kredensial
   tingkat tertinggi untuk data QC.

> Catatan lama "upload campaign tanpa guard role" sudah **tidak berlaku** — endpoint itu kini
> butuh `admin.campaign.write`.

---

## Referensi terkait
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — role bawaan, matriks permission, data_scope
- [`INTEGRATION.md`](./INTEGRATION.md) — webhook & alur upload
- [`DATA_MODEL.md`](./DATA_MODEL.md) — entitas di balik endpoint
