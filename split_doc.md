# Analisis Divergensi `telemarketing-qc-api` vs `telemarketing-qc-system`

Dokumen ini menjawab: **kenapa kode `telemarketing-qc-api` banyak berubah dari
`telemarketing-qc-system` setelah pemisahan repo?**

Pembanding: `telemarketing-qc-system` @ `fa2c268` (branch `dev`, working tree bersih)
lawan `telemarketing-qc-api` @ `e183184`.

---

## Ringkasan

Divergensi terpusat di direktori `api/`. Kode bersama tidak berubah:

| Area | Status |
|---|---|
| `core/db/crud.py`, `core/db/models.py` | **identik** dengan `system/db/` |
| `core/compliance/*` (17 berkas) | identik, kecuali `stats_aggregate.py` |
| `core/services/*` | identik, kecuali `multi_bucket_minio.py` |
| `api/` | 15 berkas berbeda |

Dari 15 berkas `api/` yang berbeda, **14 adalah adaptasi wajib** akibat pemisahan
repo, dan **1 adalah regresi nyata** (`api/dependencies.py`) yang membuat API gagal
start. Bagian [Bug](#bug-yang-ditemukan) menjelaskan yang terakhir.

---

## Kenapa kode harus berubah: bentuk repo berubah

Di monorepo `telemarketing-qc-system`, semuanya satu pohon:

```
telemarketing-qc-system/
├── api/         ├── worker/      ├── dashboard/
├── db/          ├── compliance/  ├── services/     ├── prompt/
└── api/sales_lookup.py
```

Setelah split, `telemarketing-qc-api` hanya memuat `api/` + submodule `core/`:

```
telemarketing-qc-api/
├── api/
├── core/            <- git submodule -> telemarketing-qc-core
│   ├── db/  compliance/  services/  prompt/  sales_lookup.py  core_config.py
└── db/migrations/   <- API pemilik tunggal migrasi Alembic
```

`api/Dockerfile` menyalin isi `core/` **datar** ke `/app`, supaya import tetap
`from db import crud` (bukan `from core.db import crud`):

```dockerfile
COPY core/db         /app/db
COPY core/compliance /app/compliance
COPY core/services   /app/services
COPY core/sales_lookup.py /app/sales_lookup.py
COPY api             /app/api
```

Dua konsekuensi inilah sumber mayoritas perubahan.

### 1. `api/sales_lookup.py` pindah ke `core/` → prefix `api.` hilang

`sales_lookup` dipakai bersama API dan worker, jadi ia naik ke `core/`. Di image
API ia mendarat di `/app/sales_lookup.py`, bukan `/app/api/sales_lookup.py`.

```python
- from api.sales_lookup import active_sales_map
+ from sales_lookup import active_sales_map
```

**10 lokasi**: `api/qc_scope.py` (2), `api/rbac.py`, `api/routers/agent_error.py`,
`campaign.py`, `role.py`, `sales_database.py`, `stats.py`, `transcript.py`,
`core/compliance/stats_aggregate.py`.

Perubahan lain di `rbac.py` dan `stats_aggregate.py` hanyalah teks docstring yang
menyebut nama modul lama — bukan perubahan perilaku.

### 2. Kode worker tidak ada di image API → `api/celery_client.py`

Monorepo memakai `from worker.celery_app import celery_app` untuk mengirim task.
Modul `worker` tidak ada di repo API. Karena API **hanya mengirim** task by name
(`send_task("worker.tasks...")`) dan tidak pernah mengeksekusinya, ia cukup punya
instance Celery sendiri yang menunjuk broker yang sama:

```python
- from worker.celery_app import celery_app
+ from api.celery_client import celery_app
```

**6 lokasi** di `document.py`, `reprocess.py` (3), `transcript.py`, `webhook.py`.
Konfigurasi serializer/timezone di `api/celery_client.py` disamakan dengan
`worker/celery_app.py` agar pesan yang dikirim identik.

---

## Perubahan karena cutover infrastruktur produksi

Ini bukan konsekuensi split, melainkan keputusan deployment yang kebetulan
dilakukan bersamaan (commit `3179c38`). Postgres pindah ke DWH `10.155.32.28`
schema `dashboard`, MinIO pindah ke `cdn.bankmega.local` dengan kredensial
per-bucket.

### `POSTGRES_SCHEMA` — tabel tidak boleh mendarat di `public`

Schema DWH dipakai bersama tim lain. Model tidak menyebut schema sama sekali,
jadi `search_path` yang mengarahkan:

- `api/dependencies.py` → `_make_engine()` mengirim
  `connect_args={"options": "-csearch_path=<schema>,public"}`
- `db/migrations/env.py` → `SET search_path` + `version_table_schema=SCHEMA`,
  supaya `alembic_version` juga tidak menulis ke `public`
- `db/migrations/env.py` juga meng-escape `%` → `%%` pada URL, karena nilai itu
  masuk ke `ConfigParser`; password yang URL-encoded (mis. `%40`) membuat alembic
  gagal total tanpa escape ini

### MinIO kredensial per-bucket

`core/services/multi_bucket_minio.py` mendapat `build_minio_client(settings)`
sebagai satu-satunya jalan membuat client: mengembalikan `MultiBucketMinioClient`
kalau `.env` mengisi `MINIO_ACCESS_KEY_<BUCKET>`, dan `Minio` tunggal kalau belum
(deployment lokal lama). API-nya sama, pemanggil di routers tidak berubah.

`ensure_buckets()` kini membungkus `make_bucket` dengan `try/except` + log
warning: di CDN, bucket sudah disiapkan tim infra dan kredensialnya tidak punya
hak `makeBucket`. Startup API tidak boleh mati karena itu.

### Bucket `qc-database` dinonaktifkan

Bucket ini belum punya kredensial di CDN, jadi dimatikan konsisten di empat
tempat: setting `minio_bucket_qc_database` (comment), `ensure_buckets()`,
`_BUCKET_CREDENTIAL_FIELDS` di `multi_bucket_minio.py`, endpoint
`upload_qc_database` di `api/routers/qc_database.py`, dan `include_router` di
`api/main.py`. Endpoint `list/download/delete` tetap hidup.

### `_submit_agent_map` membaca snapshot, bukan `tms_cashline`

Di `core/compliance/stats_aggregate.py`, sumber `submit_time` + `agent_id`
dialihkan dari tabel `tms_cashline` ke `crud.cashline_agent_index()` (snapshot
`reference_data` di `result_json`). Tabel itu tidak terisi lagi sejak reference
data pindah ke DWH API — query-nya tetap jalan tanpa error tapi **selalu
mengembalikan kosong**, sehingga tenggat H+2 dianggap lewat untuk semua tiket dan
pelunakan new joiner tidak pernah aktif. Perubahan ini menyusul
`_submit_time_map` / `_submit_date_map` / `compute_stats_snapshot` yang sudah
lebih dulu dialihkan.

> Catatan: `core/` (submodule) di beberapa titik **lebih maju** dari monorepo —
> `build_minio_client`, `fget_object`, `is_configured` belum ada di
> `telemarketing-qc-system/services/multi_bucket_minio.py`. Divergensi di sini
> arahnya monorepo yang tertinggal, bukan repo API yang menyimpang.

---

## Berkas yang hanya ada di satu sisi

| Berkas | Keterangan |
|---|---|
| `api/celery_client.py` (hanya API) | pengganti `worker.celery_app`, lihat di atas |
| `api/main_old.py`, `api/schemas/auth_old.py`, `db/crud_old.py`, `db/crud_22072026.py`, `compliance/*_old.py`, `services/data_dwh_23072026.py` (hanya system) | arsip versi lama, sengaja tidak ikut dibawa |
| `api/sales_lookup.py` (hanya system) | pindah ke `core/sales_lookup.py` |

---

## Bug yang ditemukan

### 🔴 `api/dependencies.py` tertimpa versi lama pra-RBAC — API gagal start

**Gejala:** working tree berisi `api/dependencies.py` yang berbeda jauh dari HEAD
maupun dari `telemarketing-qc-system`.

**Root cause:** isinya bukan hasil adaptasi split, melainkan **salinan versi lama
sebelum refactor RBAC** yang ter-paste menimpa berkas hasil split. Buktinya, ia
mengembalikan gate berbasis role literal yang sudah dihapus di **kedua** repo, dan
ikut mematikan setting yang masih dipakai luas.

Tiga akibat, dua di antaranya fatal:

**1. `ImportError` saat aplikasi diimpor — API tidak pernah menyala**

Berkas itu menghapus `get_manual_status_setter_user`, padahal masih diimpor:

```
api/routers/qc_status.py:4  ->  get_manual_status_setter_user
```

`api/main.py` mengimpor `qc_status`, jadi ini gagal sebelum uvicorn sempat bind.

**2. `AttributeError` di `ensure_buckets()` — startup lifespan mati**

Seluruh setting MinIO di-comment (`minio_endpoint`, `minio_access_key`,
`minio_bucket_*`), padahal masih dirujuk **31 kali** di 9 berkas — termasuk
`ensure_buckets()` yang dipanggil `lifespan` di `api/main.py:13`. Ironisnya
berkas yang sama justru meng-*uncomment* `settings.minio_bucket_qc_database` di
`ensure_buckets()`, satu-satunya yang memang harus mati.

Perlu ditegaskan karena mudah disalahpahami: **field yang di-comment tidak
tergantikan oleh `.env`**, walaupun `.env` mengisi `MINIO_ENDPOINT`,
`MINIO_BUCKET_TRANSCRIPTS`, dst. Penyebabnya `class Config` di
`api/dependencies.py`:

```python
class Config:
    env_file = ".env"
    case_sensitive = False
    extra = "ignore"        # <- env var tanpa deklarasi field DIABAIKAN
```

Dengan `extra = "ignore"`, pydantic-settings hanya membaca env var yang punya
field-nya. Dijalankan langsung terhadap `.env` asli, `class Settings` versi lama
itu memberi:

```
settings.minio_bucket_transcripts -> AttributeError: 'Settings' object has no attribute 'minio_bucket_transcripts'
settings.minio_endpoint           -> AttributeError: 'Settings' object has no attribute 'minio_endpoint'
...  (11 field, semuanya AttributeError)
```

Versi hasil split, `.env` yang sama, terbaca normal:

```
minio_endpoint = 'cdn.bankmega.local'      minio_secure = True
minio_bucket_transcripts = 'transcripts'   minio_transcripts_source_prefix = 'inbox/'
postgres_host = '10.155.32.28'             postgres_schema = 'dashboard'
kredensial per-bucket terisi? True
```

Satu-satunya perbedaan substantif di `class Settings` antara kedua versi adalah
11 baris MinIO tersebut; sisanya komentar dan whitespace. Nilai config-nya
sendiri — host DWH, schema `dashboard`, endpoint CDN, default kredensial
Postgres yang kosong — memang sudah benar dan tidak diubah.

**3. Regresi perilaku senyap (tidak crash, tapi salah)**

- `get_db()` kehilangan `refresh_doc_sla_cache()` dan
  `refresh_hidden_tickets_cache()` → kebijakan SLA H+2 dan penyaringan tiket
  tersembunyi berhenti bekerja
- Gate role kembali ke daftar literal (`if current_user.role not in (...)`) →
  role buatan operator lewat menu Manage Role otomatis ditolak semua endpoint,
  persis masalah yang refactor `api/permissions.py` + `api/rbac.py` selesaikan
- 6 fungsi gate mati (`get_spq_head_user`, `get_qc_user`, `get_sales_agent_user`,
  `get_team_leader_qc_user`, `get_tl_qc_or_spq_head_user`,
  `get_qc_or_spq_head_user`) ikut terbawa — tidak dipakai router mana pun

**Perbaikan:** `api/dependencies.py` dikembalikan ke versi hasil split (HEAD),
dengan **empat default kredensial Postgres dipertahankan kosong** sesuai config
yang sudah benar — nilainya hanya boleh datang dari `.env`, yang memang sudah
mengisi semuanya:

```python
postgres_host:     os.getenv("POSTGRES_HOST", "")
postgres_db:       os.getenv("POSTGRES_DB", "")
postgres_user:     os.getenv("POSTGRES_USER", "")
postgres_password: os.getenv("POSTGRES_PASSWORD", "")
```

---

## Verifikasi

`minio` tidak terpasang di host, jadi aplikasi utuh belum bisa diimpor.
Verifikasi dilakukan secara statis dengan AST — termasuk mensimulasikan layout
datar `/app` persis seperti `COPY` di `api/Dockerfile` — ditambah satu uji
runtime nyata: `class Settings` diekstrak dan dijalankan sendiri terhadap `.env`
asli (`pydantic-settings` dan `python-dotenv` memang tersedia), sehingga
AttributeError di poin 2 di atas terbukti, bukan sekadar dugaan dari pembacaan
kode.

| # | Cek | Sebelum | Sesudah |
|---|---|---|---|
| 1 | `settings.X` dipakai tapi tidak dideklarasikan di `Settings` | **12 atribut / 31 pemakaian** | 0 |
| 2 | Nama diimpor dari `api.dependencies` tapi tidak ada | **1** (`get_manual_status_setter_user`) | 0 |
| 3 | Syntax seluruh `api/`, `core/`, `scripts/`, `db/` | 0 | 0 |
| 4 | Modul internal tak resolve di layout `/app` | 0 | 0 |

Cek 4 juga mengonfirmasi tidak ada sisa `from worker...`, `from api.sales_lookup...`,
atau `from core....` di mana pun, dan semua import pihak ketiga
(`pdfplumber`, `openpyxl`, `requests`, `minio`) tercakup
`core/requirements.txt` + `api/requirements.txt`.

**Belum diverifikasi runtime.** Uji end-to-end masih perlu dijalankan di
lingkungan yang punya akses ke DWH dan CDN:

```bash
docker compose build api && docker compose up -d api
docker compose logs -f api      # alembic upgrade head + uvicorn harus lolos
curl -f http://localhost:4000/health
```
