# Skema Data & Migrasi — Telemarketing QC System

Referensi model database (PostgreSQL, SQLAlchemy) dan alur migrasi Alembic.
Sumber: `db/models.py` (**18 tabel**), `alembic.ini`, `db/migrations/`.
Revisi HEAD saat ini: **`0040_user_campaigns_admin_only_administration`**.

> Catatan desain: **tidak ada `relationship()` SQLAlchemy** — semua keterkaitan berupa kolom
> **foreign key** atau **join by string key**. Tidak ada tipe `Enum` DB — kolom berkode
> memakai `String` biasa.

---

## 1. Daftar Tabel (18)

### Auth & Otorisasi

| Tabel | Model | Fungsi | Kunci penting |
|---|---|---|---|
| `users` | User | User lintas hierarki Sales & QC | PK `id`; `username` (=NIP, unik), `email` unik, `hashed_password`, `role`, `is_active`, `created_by`→`users.id` |
| `roles` | Role | Definisi role: permission + cakupan data | PK `id`; `key` unik, `label`, `is_system` (10 role bawaan, tak bisa dihapus), `base_role`, `data_scope`, `permissions` JSONB |
| `role_campaigns` | RoleCampaign | Campaign yang boleh dilihat sebuah role | PK `id`; `role_id`→`roles.id` (CASCADE), `campaign`. **Tanpa baris = semua campaign** |
| `user_campaigns` | UserCampaign | Pembatasan campaign per ORANG (tab "Assign Role") | PK `id`; `user_id`→`users.id` (CASCADE), `campaign`. Tanpa baris = tak dibatasi di tingkat orang |

> `user_campaigns` hanya bisa **mempersempit**: campaign efektif = **irisan** dari
> `role_campaigns`, `user_campaigns`, dan (untuk cakupan sales) tag Dedicated di Sales
> Database — tidak pernah gabungan. Lihat `api/rbac.py::effective_campaigns_for`.

### Campaign & Evaluasi

| Tabel | Model | Fungsi | Kunci penting |
|---|---|---|---|
| `campaigns` | Campaign | Bundel konfigurasi evaluasi | PK `id`; `name` unik; `prompt_text`, `scorecard_text`, `kb_text` (+ `*_filename`), `is_active`; **RIPLAY**: `kb_text_raw`, `riplay_filename`, `riplay_product_name`, `riplay_similarity`, `riplay_extraction` JSONB, `riplay_applied` JSONB, `riplay_uploaded_at` |
| `results` | Result | Satu tiket QC / run upload | PK `id` **UUID**; `campaign` (str), `source_files` JSONB, `status`, `uploaded_*`, `generated_at`, `completed_at`, `processing_sec` |
| `result_data` | ResultData | Payload JSON evaluasi | PK `id`; `result_id`→`results.id` (CASCADE); `result_json` JSONB (scorecard + tabel error code) |
| `documents` | Document | Dokumen pendukung + OCR | PK `id`; `result_id`→`results.id` (CASCADE); `doc_type`, `object_path`, `status`, `ocr_json` |
| `stats_snapshots` | StatsSnapshot | Cache payload dashboard Statistics | PK `id`; `snapshot_date` (unik, WIB `YYYY-MM-DD`); `payload` JSONB (memuat `_signature`) |

> `kb_text_raw` menyimpan KB persis seperti diunggah; `kb_text` adalah teks itu dengan
> **overlay RIPLAY** ditumpangkan (`compliance/riplay.py`), sehingga overlay selalu bisa
> dibangun ulang dari basis yang bersih.

### Workflow QC (banding, Manual Status, assignment)

| Tabel | Model | Fungsi | Kunci penting |
|---|---|---|---|
| `qc_status_requests` | QcStatusRequest | Manual Status **terkini** (1 baris per result, ditimpa) | PK `id`; `result_id`→`results.id` **unik** (CASCADE); `requested_status`; field review berjenjang |
| `qc_status_events` | QcStatusEvent | Jejak audit **append-only** tiap perubahan Manual Status | PK `id`; `result_id`→`results.id` (CASCADE, indexed); `event`, `actor_username`, `actor_role`, `requested_status`, `status_before`, `status_after`, `comment` |
| `error_code_appeals` | ErrorCodeAppeal | Banding per baris error code (append-only) | PK `id`; `result_id`→`results.id` (CASCADE); `error_code`, `item_code`, snapshot `ai_*`, `qc_*`, `appeal_kind`, `add_source`, `origin`, field review |
| `qc_assignments` | QcAssignment | TL QC assign tiket ke QC (1 tiket→1 QC) | PK `id`; `ticket_id` unik (=customer id prefix), `qc_username`, `assigned_by_username` |
| `qc_manual_checks` | QcManualCheck | Audit "tiket dicek manual oleh QC" (append-only) | PK `id`; `result_id`→`results.id` (CASCADE); `checked_by_username`, `note` |

> `qc_status_events` **tidak dipakai menghitung apa pun** — Manual Status yang berlaku tetap
> dibaca dari `qc_status_requests`. Tabel ini murni untuk ditampilkan sebagai riwayat
> (`GET /qc_status_events/{result_id}`).

### Data Acuan & Upload

| Tabel | Model | Fungsi | Kunci penting |
|---|---|---|---|
| `tms_cashline` | TmsCashline | Mirror export CASHLINE (data acuan) | PK `id`; `result_id` (=customer id, indexed) + ~80 kolom `Text` (mis. `cust_name`, `agent_id`, `submit_time`) |
| `ascend_custp` | AscendCustp | Mirror export Card Holder (Ascend) | PK `id`; `cust_local_name` (`CUST_LOCAL_NAME`, key match) + ~115 kolom `Text` UPPERCASE |
| `sales_databases` | SalesDatabase | Upload XLSX database sales (pola newest-active) | PK `id`; `object_path`, `is_active`, `uploaded_by_*` |
| `qc_databases` | QcDatabase | Upload XLSX database QC | PK `id`; `object_path`, `is_active`, `uploaded_by_*` |

`tms_cashline.submit_time` juga menjadi **basis tenggat H+2** untuk AI Status `PENDING`
(lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7).

---

## 2. Relasi Antar Entitas

```
roles ──1:N── role_campaigns                users (created_by → users)
  ▲ (string: users.role == roles.key,          │
  │  tanpa FK)                                 └──1:N── user_campaigns
  └──────────────────────────────────────────────┘

campaigns
    ▲ (string: results.campaign == campaigns.name, tanpa FK)
    │
results (UUID) ──1:1── result_data (result_json)
   │  ├──1:N── error_code_appeals        (FK, CASCADE)
   │  ├──1:1── qc_status_requests         (FK unik, CASCADE)
   │  ├──1:N── qc_status_events           (FK, CASCADE)
   │  ├──1:N── qc_manual_checks           (FK, CASCADE)
   │  └──1:N── documents                  (FK, CASCADE)
   │
   └── customer id (prefix nama file) ──(string key, tanpa FK)──►
           tms_cashline.result_id  ≡  qc_assignments.ticket_id  ≡  ticket id di list Results

tms_cashline.cust_name ──(trim+lower, tanpa FK)──► ascend_custp.CUST_LOCAL_NAME
```

Poin penting:
- **User ↔ Role**: dicocokkan string `users.role` = `roles.key` (tanpa FK). Role yang tidak
  ada di tabel `roles` = tanpa permission sama sekali.
- **Result ↔ Campaign**: hanya cocokkan string `results.campaign` = `campaigns.name` (tanpa FK).
- **TmsCashline / Assignment / Results-list**: dijembatani **customer id** (prefix sebelum `_`
  dari nama PDF paling awal). Bukan relasi DB.
- **Hierarki Sales**: TIDAK dimodelkan sebagai FK. Level = `users.role`; relasi
  agent→TL→AM→telesales head berada di **`sales_databases`** (XLSX) dan diresolusi runtime di
  `api/sales_lookup.py`. `users.created_by` hanya mencatat pembuat akun.

---

## 3. Nilai Kolom Berkode (String, bukan Enum DB)

| Kolom | Nilai |
|---|---|
| `users.role` / `roles.key` | Bawaan — Sales: `sales_agent`, `team_leader`, `area_manager`, `telesales_head` · QC: `qc`, `team_leader_qc`, `qc_support`, `spq_head` · Khusus: `admin`, `demo`. **Role buatan sendiri boleh apa saja** (dibuat via Manage Role) |
| `roles.data_scope` | `all`, `qc_assigned`, `qc_support_own`, `sales_am`, `sales_tl`, `sales_agent` |
| `results.status` / `documents.status` | `pending`, `processing`, `done`, `failed` |
| `qc_status_requests.requested_status` | `PASS`, `FAIL`, `PENDING` |
| `qc_status_events.event` | `usul`, `konfirmasi`, `set_langsung`, `tl_approve`, `tl_reject`, `tl_escalate`, `spq_approve`, `spq_reject` |
| `error_code_appeals.appeal_kind` | `remove`, `change`, `add` |
| `error_code_appeals.add_source` | `scorecard`, `cashline_data`, `card_holder`, `others` (NULL untuk remove/change) |
| `error_code_appeals.origin` | `qc`, `tl_direct`, `spq_direct` |
| `tl_qc_status` (2 tabel) | `pending`, `approved`, `rejected`, `escalated` |
| `approval_status` (2 tabel, tier SPQ Head) | `pending`, `approved`, `rejected` |

> Rename historis: `admin → spq_head` (migrasi 0008), `user → sales_agent` (migrasi 0009).
> Sejak `0031` nama role tidak lagi menentukan akses — yang menentukan `roles.permissions`.

---

## 4. Migrasi (Alembic)

- **Config**: `alembic.ini` → `script_location = db/migrations`, `prepend_sys_path = .`.
- **URL DB**: `db/migrations/env.py::get_url()` menyusun URL **langsung dari env** (`POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` default 5432, `POSTGRES_DB`) dan
  meng-override `sqlalchemy.url` di ini. `target_metadata = Base.metadata` dari `db.models`.
- **Chain**: linear `0001 → … → 0040` (**40 revisi**, HEAD `0040_user_campaigns_admin_only_administration`).
  `down_revision = None` di `0001`.
- **Seed admin**: `0001_initial.py` menambah user admin bila belum ada, dari
  `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`ADMIN_EMAIL`.

### Tonggak migrasi yang perlu diketahui

| Revisi | Isi |
|---|---|
| `0027_campaign_riplay` | Kolom RIPLAY pada `campaigns` (+ `kb_text_raw`) |
| `0030_qc_status_events` | Tabel audit `qc_status_events` |
| `0031_roles_permissions` | Tabel `roles` + `role_campaigns`; awal model capability |
| `0033_sales_roles_cashline_scope` | `data_scope` untuk role sales |
| `0034_sales_campaign_from_roster` | Campaign sales diturunkan dari tag Dedicated roster |
| `0039_perm_export_verification` | Permission `results.export.verification` (export + `/get_nama_ibu_kandung`) |
| `0040_user_campaigns_admin_only_administration` | Tabel `user_campaigns`; menu Administration jadi milik `admin` saja |

### Menjalankan migrasi

```bash
# Docker (otomatis saat api start; manual):
docker compose exec api alembic upgrade head
docker compose exec api alembic current      # revisi aktif
docker compose exec api alembic history      # riwayat
```

```bash
# Bare-metal (dari root repo, env ter-export):
set -a; . ./.env; set +a
alembic upgrade head
```

### Membuat migrasi baru

Migrasi di repo ini **ditulis tangan** (bukan autogenerate), dengan ID zero-padded `00NN`:

```bash
alembic revision -m "deskripsi singkat"
# lalu edit file baru di db/migrations/versions/:
#   - set revision = "0041", down_revision = "0040"
#   - isi upgrade()/downgrade() (op.add_column, dsb.)
alembic upgrade head
```

> Autogenerate dimungkinkan (metadata sudah ter-wire), tapi pola yang dipakai adalah manual.
> Selalu naikkan nomor revisi berurutan dan set `down_revision` ke HEAD sebelumnya
> (kesalahan urutan menyebabkan error "Multiple head revisions").
>
> Migrasi yang **menambah permission** juga harus menuliskannya ke role yang relevan di
> tabel `roles` (lihat pola `0035`–`0040`) — menambah konstanta di `api/permissions.py` saja
> tidak memberi akses ke role yang sudah ada.

---

## 5. Persistensi & Penyimpanan

| Data | Lokasi |
|---|---|
| Semua tabel di atas | PostgreSQL (`./data/postgres`) |
| PDF transkrip, hasil JSON, campaign, dokumen, audio, XLSX database | MinIO (`./data/minio`) |
| Broker/antrian Celery | Redis (`./data/redis`) |

`result_data.result_json` (Postgres) dan `results/{result_id}.json` (MinIO) menyimpan payload
evaluasi yang sama; dokumen fisik hanya di MinIO (kolom `object_path` menunjuk ke sana).

### Cache snapshot Statistics

`stats_snapshots.payload` menyimpan `_signature` — sidik jari **data**, bukan versi kode.
Snapshot dipakai ulang selama signature-nya cocok. Konsekuensinya: **mengubah logika
perhitungan (mis. sakelar SLA H+2) tidak otomatis meng-invalidate cache.** Paksa hitung
ulang lewat `POST /stats/refresh` atau `crud.get_or_build_stats_snapshot(db, force=True)`
(lihat [`RUNBOOK.md`](./RUNBOOK.md) §11).

---

## Referensi terkait
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — isi `roles.permissions` & `data_scope`
- [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) — detail `error_code_appeals`
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — isi `result_json` & `campaigns`
- [`INTEGRATION.md`](./INTEGRATION.md) — bagaimana `results`/`documents` terisi
- [`RUNBOOK.md`](./RUNBOOK.md) — backup/restore & migrasi manual
