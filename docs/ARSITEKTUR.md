# Arsitektur Sistem Telemarketing QC

> Dokumen ini menggambarkan sistem sebagaimana kode dan konfigurasinya berada
> pada **2 September 2026**, commit sinkronisasi `fa2c268` (branch `main` di
> keempat repo hasil split).
>
> Semua angka, nama berkas, dan nomor baris di bawah diverifikasi langsung dari
> repositori — bukan dari ingatan atau dokumentasi lama.

---

## Mulai Cepat — Menjalankan Aplikasi

Empat langkah, satu per aplikasi. Versi lengkap dengan penjelasan tiap perintah
dan penanganan kegagalan ada di **bagian 12**.

> `core` "dijalankan" dengan cara **disiapkan sebelum build**, bukan dinyalakan
> jadi container. Dia tetap langkah 1 — hanya perintahnya bukan `docker compose up`.

### Persiapan (sekali saja per host)

```bash
docker network create qc-net

# Bebaskan port 4000/4005/4006/6378 kalau stack monorepo masih jalan
cd /data/scorecard_v2/telemarketing-qc-system && docker compose down
```

### Langkah 1 — CORE

```bash
git -C /data/scorecard_v2/telemarketing-qc-api    submodule update --init --recursive
git -C /data/scorecard_v2/telemarketing-qc-worker submodule update --init --recursive

# Harus ada isinya — kalau kosong, langkah 2 dan 3 pasti gagal
ls /data/scorecard_v2/telemarketing-qc-api/core/compliance
ls /data/scorecard_v2/telemarketing-qc-worker/core/compliance
```

### Langkah 2 — API

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker compose up -d --build
docker compose logs -f api
```

Tunggu di log sampai muncul:

```
Running upgrade 0050 -> 0051, ...
INFO:     Uvicorn running on http://0.0.0.0:4000
```

Lalu `Ctrl+C` dan pastikan:

```bash
curl -sf http://localhost:4000/health && echo " OK"
docker compose exec api alembic current      # harus: 0051 (head)
```

**Berhenti di sini kalau belum `0051 (head)`** — jangan lanjut ke worker.

Naik: container `api` + `redis`.

### Langkah 3 — WORKER

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker compose up -d --build
docker compose exec worker celery -A worker.celery_app inspect registered
```

Harus muncul tiga task: `process_transcript`, `process_document`,
`reprocess_ticket`.

Naik: container `worker` + `flower`.

### Langkah 4 — DASHBOARD

```bash
cd /data/scorecard_v2/telemarketing-qc-dashboard
docker compose up -d --build
```

Paling lama (`npm ci` + `npm run build`). Naik: container `dashboard`.

### Cek akhir

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Lima container hidup:

```
api   redis   worker   flower   dashboard
```

Lima container dari empat langkah — `core` tidak menghasilkan container,
sementara api membawa `redis` dan worker membawa `flower`.

Terakhir: buka dashboard di browser dan **login**. Itu uji tercepat yang
menangkap salah routing. Kalau dijawab 422, `VITE_API_URL` tidak terbawa saat
build — perbaikannya rebuild dashboard, bukan restart.

### Kalau gagal

| Gejala | Tindakan |
|---|---|
| `network qc-net ... could not be found` | Persiapan terlewat |
| `failed to compute cache key: "/core/db"` | `core/` kosong — ulangi langkah 1 |
| `port is already allocated` | Stack monorepo masih jalan |
| `ModuleNotFoundError: compliance` di worker | `docker compose build --no-cache worker` |
| `[minio] Belum ada kredensial per-bucket` | `MINIO_*_KEY_<BUCKET>` tidak terbaca — cek `.env` |
| Login 422 | Rebuild dashboard, jangan cuma restart |

---

## 1. Gambaran Umum

Sistem ini melakukan **quality control otomatis atas panggilan telemarketing**.
Transkrip percakapan (atau audio yang di-STT lebih dulu) dievaluasi oleh LLM
terhadap aturan kepatuhan per-campaign, dokumen pendukung nasabah di-OCR, lalu
hasilnya disajikan sebagai dashboard untuk tim QC, SPQ Head, dan Admin.

Pemrosesan bersifat **asinkron**: API menerima unggahan lalu menitipkan
pekerjaan berat ke antrean Celery, sehingga permintaan HTTP tidak menunggu
panggilan LLM yang bisa berjalan sampai 30 menit
(`task_time_limit=1800` di `worker/celery_app.py`).

### Empat repositori

| Repo | Isi | Bentuk runtime |
|---|---|---|
| `telemarketing-qc-api` | FastAPI, 17 router, migrasi Alembic | Container `api`, port 4000 |
| `telemarketing-qc-worker` | Celery worker + Flower | Container `worker` & `flower`, port 4005 |
| `telemarketing-qc-core` | Kode bersama api & worker | **Bukan container** — ikut ter-`COPY` ke image keduanya |
| `telemarketing-qc-dashboard` | Vue 3 + Vite, disajikan Nginx | Container `dashboard`, port 4006 |

Sumber kebenarannya adalah monorepo `telemarketing-qc-system` (branch `dev`);
keempat repo di atas adalah hasil split yang disinkronkan manual per rentang
commit.

---

## 2. Kenapa `core` Ada di Dua Tempat

Ini bagian yang paling sering disalahpahami, jadi ditaruh di depan.

`compliance/`, `services/`, `db/`, dan `prompt/` dipakai **api maupun worker**:

```
telemarketing-qc-api/api/routers/webhook.py:40
    from compliance.pdf_parser import ticket_id_from_filename

telemarketing-qc-worker/worker/tasks/process_transcript.py:30
    from compliance.call_ownership import filter_calls_by_agent
```

Kalau kode itu di-copy ke dua repo, setiap perbaikan bug harus dikerjakan dua
kali — dan begitu satu terlewat, api dan worker diam-diam berperilaku berbeda.
Karena itu kode bersama tinggal di satu repo (`telemarketing-qc-core`), lalu api
dan worker memasangnya sebagai **git submodule** di folder `core/`.

### Yang sebenarnya disimpan git

Repo api **tidak** menyimpan satu pun berkas `.py` milik core. Yang tercatat
hanya satu baris:

```
$ git -C telemarketing-qc-api ls-files -s core
160000 4856ee5027d5c5aca08d029933b29f6337ed3de0 0	core
```

Mode `160000` adalah penanda submodule. Isinya: *"di posisi `core` ada repo
lain, versi `4856ee5`"*. Folder `core/` juga punya `.git`-nya sendiri:

```
$ cat telemarketing-qc-api/core/.git
gitdir: ../.git/modules/core
```

**Konsekuensi:** `git clone` biasa menghasilkan `core/` yang **kosong**, dan
`docker build` akan berhenti di baris `COPY core/db /app/db`. Karena itu setiap
Jenkinsfile punya baris ini tepat setelah checkout:

```groovy
// Wajib: tanpa ini folder core/ kosong dan build pasti gagal.
sh 'git submodule update --init --recursive'
```

### Nama `core` lenyap saat runtime

Di dalam image, isi `core/` di-`COPY` **datar** ke `/app` — bukan sebagai paket
bernama `core` (lihat `api/Dockerfile`):

```dockerfile
COPY core/db              /app/db
COPY core/compliance      /app/compliance
COPY core/services        /app/services
COPY core/prompt          /app/prompt
COPY core/sales_lookup.py /app/sales_lookup.py
COPY core/core_config.py  /app/core_config.py
```

`core/db` menjadi `/app/db`, bukan `/app/core/db`. Karena itu impornya
`from db import crud`, **bukan** `from core.db import crud`. Di luar Docker,
efek yang sama dicapai dengan `PYTHONPATH=.:core`.

Nama berkas `core_config.py` (bukan `config.py`) juga disengaja: karena isinya
mendarat di root `/app`, nama `config.py` terlalu umum dan berisiko bentrok.

### Aturan ketergantungan

```
        ┌──────────────────┐
        │       core       │   tidak boleh mengimpor api.* maupun worker.*
        └────────┬─────────┘
                 │ dipakai oleh
        ┌────────┴─────────┐
        │                  │
   ┌────▼────┐       ┌─────▼─────┐
   │   api   │       │  worker   │   saling TIDAK mengimpor
   └─────────┘       └───────────┘
```

Sebelum split, `sales_lookup` mengambil Settings dan MinIO client dari
`api.dependencies`, yang membuat core (dan lewat `compliance.stats_aggregate`
juga worker) tidak bisa jalan tanpa folder `api/`. Penggantinya adalah
`core/core_config.py` — `CoreSettings` minimal yang hanya berisi field MinIO
yang benar-benar dipakai kode bersama.

Batasan ini ditegakkan CI, bukan sekadar konvensi:

```groovy
// Jenkinsfile api — stage 'No Worker Import'
sh '! grep -rn --include=*.py -E "^[[:space:]]*(from|import)[[:space:]]+worker\b" api scripts tests'

// Jenkinsfile worker — stage 'No API Import'
sh '! grep -rn --include=*.py -E "^[[:space:]]*(from|import)[[:space:]]+api\b" worker'
```

API mengirim task **by name**, jadi ia tidak butuh kode worker sama sekali —
cukup broker URL yang sama:

```python
celery_app.send_task("worker.tasks.process_transcript.process_transcript", args=[result_id])
```

---

## 3. Topologi Runtime

```
                          Internet / LAN Bank Mega
                                     │
                                     ▼  :443 TLS
              ┌──────────────────────────────────────────────┐
              │   nginx host — call-qc.bankmega.local        │
              │   /etc/nginx/sites-available/default         │
              └───┬──────────┬──────────┬──────────┬─────────┘
                  │          │          │          │
        /         │   /api-b/│   /api-a/│  /auth/* │ /voice-to-text-dm/
                  │          │          │  /tickets│
                  ▼          ▼          ▼          ▼
          ┌────────────┐ ┌────────┐ ┌────────┐ ┌──────────────────┐
          │ dashboard  │ │  api   │ │ App A  │ │ App C   :8008    │
          │ nginx :4006│ │ :4000  │ │ :8000  │ │ App C   :8010    │
          └────────────┘ └───┬────┘ └────────┘ └──────────────────┘
                             │                    (aplikasi lain)
                             │ send_task (Redis)
                             ▼
                        ┌─────────┐        ┌──────────┐
                        │  redis  │◄───────│  worker  │──► flower :4005
                        │  :6378  │        │ (celery) │
                        └─────────┘        └────┬─────┘
                                                │
        ┌───────────────────────────────────────┼────────────────────┐
        ▼                     ▼                 ▼                    ▼
┌───────────────┐  ┌────────────────────┐ ┌───────────┐  ┌────────────────────┐
│ PostgreSQL    │  │ MinIO              │ │ LLM Azure │  │ App A DWH :8002    │
│ 10.155.32.28  │  │ cdn.bankmega.local │ │ Foundry   │  │ reference data     │
│ db `da`       │  │ :443, per-bucket   │ │ gpt-5.4   │  │ cashline/customer  │
│ schema        │  │ credentials        │ │ -mini     │  │                    │
│ `dashboard`   │  └────────────────────┘ └───────────┘  └────────────────────┘
└───────────────┘
```

Ketiga compose berbagi satu network eksternal:

```bash
docker network create qc-net      # sekali per host
```

### Daftar port

| Port | Milik | Keterangan |
|---|---|---|
| 4000 | `api` | FastAPI + OpenAPI di `/docs` |
| 4005 | `flower` | Monitoring Celery — `FLOWER_UNAUTHENTICATED_API=true`, **batasi di firewall** |
| 4006 | `dashboard` | Nginx penyaji bundle Vite |
| 6378 | `redis` | Broker + result backend Celery (bukan 6379) |
| 5432, 4003, 4004 | `postgres`, `minio` lokal | Hanya aktif dengan `--profile local-infra` |

---

## 4. Pembagian Compose

Infra tidak dikumpulkan di satu berkas; tiap repo membawa bagiannya.

| Repo | Service yang didefinisikan |
|---|---|
| api | `api`, `redis`, (`postgres`, `minio` — profile `local-infra`) |
| worker | `worker`, `flower` — satu image, beda `command` |
| dashboard | `dashboard` |

Karena beda berkas compose, worker **tidak punya** `depends_on` ke Postgres/Redis.
Penggantinya `restart: unless-stopped` — worker mencoba lagi sampai infra siap.

`flower` memakai YAML anchor `*worker-image` yang sama dengan `worker`. Blok
`environment` di `flower` **menimpa** (bukan menggabung) milik anchor, jadi
`PYTHONPATH` dan `DWH_API_BASE_URL` wajib ditulis ulang di sana.

---

## 5. Alur Data

### 5.1 Evaluasi transkrip

```
1. Dashboard / webhook   POST /upload_transcript   (transcript.py:69)
                         POST /webhook/process_ticket (webhook.py:128)
2. api                   simpan berkas -> MinIO bucket `transcripts`
                         buat baris `results` (status: pending)
                         celery_app.send_task("worker.tasks.process_transcript...")
3. redis                 antrean
4. worker                process_transcript(result_id)
                         ├─ _download_transcripts()     unduh dari MinIO
                         ├─ filter_calls_by_agent()     compliance/call_ownership.py
                         ├─ data_dwh.py                 reference data App A :8002
                         │                              (cache-first, fallback ke endpoint asli)
                         ├─ evaluate()                  compliance/evaluator.py -> LLM
                         ├─ stamp_static_rules()        compliance/static_similarity.py
                         └─ tulis `results` + `result_data`
5. Dashboard             GET /result/{id}, /list_transcripts, /stats
```

### 5.2 OCR dokumen pendukung

`process_document` memakai `compliance/documents.py`, yang me-resolve modul
prompt secara dinamis:

```python
importlib.import_module("prompt.ocr_ktp")
```

Karena resolusinya dinamis, `prompt/` **wajib** ikut di image worker — kalau
tidak, kegagalannya baru muncul saat runtime OCR, bukan saat build. Itulah
sebabnya `COPY core/prompt /app/prompt` ada di `worker/Dockerfile` walaupun
tidak ada `import prompt` yang terlihat secara statis.

Prompt yang tersedia: `ocr_ktp`, `ocr_kk`, `ocr_npwp`,
`ocr_cover_buku_tabungan`.

### 5.3 Reprocess

`worker/tasks/reprocess_ticket.py` didukung tabel `reprocess_jobs` dan
`reprocess_job_items` (migrasi 0042), dengan kolom `scope` untuk membedakan
reprocess seluruh tiket vs satu tiket (migrasi 0043).

---

## 6. Basis Data

### Kepemilikan skema

`telemarketing-qc-api` adalah **satu-satunya pemilik skema**. Hanya di sana
`alembic upgrade head` dijalankan — dan itu terjadi otomatis di `CMD` container:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
```

Worker tidak pernah menjalankan migrasi. **Kalau sebuah rilis mengubah skema,
job API harus selesai lebih dulu sebelum worker dideploy.**

### Schema terpisah di DWH

`POSTGRES_SCHEMA=dashboard`. Model tidak menyebut schema sama sekali, jadi yang
mengarahkan tabel adalah `search_path` — diatur di dua tempat:

```python
# db/migrations/env.py:56
connection.exec_driver_sql(f'SET search_path TO "{SCHEMA}", public')

# api/dependencies.py — _make_engine()
connect_args["options"] = f"-csearch_path={settings.postgres_schema},public"
```

`public` tetap ikut supaya extension dan tipe bawaan tetap terlihat. Kalau
`POSTGRES_SCHEMA` kosong, perilakunya kembali ke `public` (mode DB lokal lama).

`env.py` juga meng-escape `%` menjadi `%%` sebelum menyerahkan URL ke
ConfigParser — password di `.env` disimpan URL-encoded (`%40` untuk `@`), dan
tanpa escape ini Alembic gagal total.

### 21 tabel

```
users            roles              role_campaigns    user_campaigns
campaigns        results            result_data       documents
tms_cashline     ascend_custp       qc_status_requests
error_code_appeals                  qc_assignments    qc_status_events
qc_manual_checks qc_databases       stats_snapshots   sales_databases
reprocess_jobs   reprocess_job_items app_settings
```

`roles` / `role_campaigns` (migrasi 0031) menjadikan **role sebagai data**, bukan
konstanta kode; `roles.permissions` adalah array JSONB yang ditambah lewat
`||` pada migrasi-migrasi berikutnya.

---

## 7. Integrasi Eksternal

| Sistem | Alamat | Dipakai oleh | Berkas |
|---|---|---|---|
| App A — DWH | `host.docker.internal:8002` | api, worker | `core/services/data_dwh.py` |
| App A — STT/audio | `:8000` via `/api-a/` | dashboard | `UploadAudioView.vue` |
| App C — tickets-daily | `host.docker.internal:8008` | api, worker | `core/services/tickets_daily.py` |
| App C — view-streams/PDF | `host.docker.internal:8010` | api, worker | `core/services/view_streams.py` |
| MinIO CDN | `cdn.bankmega.local:443` | api, worker, core | `core/services/multi_bucket_minio.py` |
| LLM | Azure AI Foundry, `gpt-5.4-mini` | worker (dan api untuk RIPLAY) | `worker/tasks/process_transcript.py` |

`host.docker.internal` dipetakan lewat `extra_hosts: ["host.docker.internal:host-gateway"]`
di compose api dan worker.

`view_streams.py:54` memakai `VIEW_STREAM_API_KEY`, dan jika kosong jatuh ke
`TMS_API_KEY`.

### Dua mode MinIO

`build_minio_client()` memilih mode secara otomatis:

```
ada MINIO_ACCESS_KEY_<BUCKET> + secret-nya yang terisi?
   ya  -> MultiBucketMinioClient   (satu client Minio per bucket)
   tidak -> Minio tunggal pakai MINIO_ACCESS_KEY / MINIO_SECRET_KEY
```

`MultiBucketMinioClient` sengaja meniru API `Minio` persis — setiap method
menerima `bucket_name` sebagai argumen pertama lalu me-*route* ke client yang
benar. Karena itu seluruh kode pemanggil (`put_object`, `get_object`, …) tidak
perlu diubah sama sekali saat berpindah mode.

Bucket yang kredensialnya kosong **dilewati dengan warning**, bukan menggagalkan
startup — supaya migrasi bertahap mungkin. Pemakaian bucket itu nanti gagal
dengan pesan jelas dari `_client_for()`, bukan diam-diam memakai kredensial salah.

Bucket: `transcripts`, `results`, `campaigns`, `documents`, `audio`,
`sales-database`. Bucket `qc-database` sengaja dinonaktifkan — field
`minio_bucket_qc_database` di-comment di `api/dependencies.py:58`.

---

## 8. Frontend

Vue 3 + Vite + Pinia + vue-router. Repo ini **mandiri penuh** — tidak punya
submodule.

```
src/
├── api/client.js        axios instance, baseURL = VITE_API_URL
├── stores/              auth.js, data.js (Pinia)
├── router/
├── views/
│   ├── LoginView.vue
│   ├── dashboard/       Results, Stats, Transcripts, Campaigns,
│   │                    SalesDatabase, QcDatabase, TranscriptDetail
│   ├── upload/          Transcript, Audio, Campaign, SalesDatabase,
│   │                    QcDatabase, GetResult, ReprocessTickets
│   ├── qc/              AssignTicket
│   ├── spq-head/        ManageRole, ManageUser, RoleHierarchy
│   └── delete/          DeleteCampaign
├── components/  composables/  utils/  assets/
```

### `VITE_API_URL` wajib berprefix `/api-b`

Vite mengganti nilai `VITE_*` **saat build**, bukan saat container start — satu
image terikat ke satu environment.

Nilainya **tidak boleh** origin polos. Vhost yang sama punya
`location /auth/login` yang menunjuk **App C :8008** — API login berbeda yang
meminta JSON `{nip, password}`. Kalau `VITE_API_URL` diisi
`https://call-qc.bankmega.local`, request login dashboard menjadi
`POST /auth/login`, nyasar ke App C, dan dijawab **422 Unprocessable Content**.

Efek turunannya: karena `apiClient` sudah membawa `baseURL = '/api-b'`, endpoint
App A harus dipanggil dengan `fetch()` polos — lewat `apiClient` path-nya
menumpuk jadi `/api-b/api-a/…` dan 404.

### Trailing slash menentukan strip prefix

```nginx
location /api-b/ { proxy_pass http://localhost:4000/; }   # ADA slash -> prefix dibuang
    /api-b/auth/login   ->   App B menerima /auth/login

location /api/download { proxy_pass http://localhost:8010; }   # TANPA slash -> path utuh
    /api/download/xxx   ->   :8010 menerima /api/download/xxx
```

Kalau slash di ujung `proxy_pass` untuk `/api-b/` terhapus, App B menerima
`/api-b/auth/login` dan menjawab 404.

### Kebijakan cache di `nginx.conf` container

- `index.html` → `no-store, must-revalidate`.
- `/assets/` (bundle ber-hash) → `max-age=31536000, immutable`, dengan
  `try_files $uri =404` — **bukan** fallback ke `index.html`, supaya chunk yang
  hilang gagal terang-terangan alih-alih dibalas HTML ber-status 200.
- `.mjs` disajikan sebagai `text/javascript` — browser menolak module worker
  (pdf.js) yang dikirim sebagai `application/octet-stream`.

Aturan `no-store` bukan kehati-hatian teoretis: 28 Agustus 2026, tujuh jam
setelah build baru terpasang, empat browser berbeda masih menjalankan bundle
lama dan memanggil `/tickets-daily` alih-alih `/api-b/tickets_daily`.

---

## 9. Konfigurasi

`.env` tidak ter-track git (`.gitignore`), jadi isinya tidak terlihat dari repo.

Yang penting dipahami: **`.env` di repo split menargetkan infra produksi**,
bukan docker lokal seperti monorepo.

| Key | monorepo `system` | repo split |
|---|---|---|
| `POSTGRES_HOST` / `DB` / `USER` | `postgres` / `bankqc` / `bankqc` | `10.155.32.28` / `da` / `datamgmt` |
| `POSTGRES_SCHEMA` | kosong → `public` | `dashboard` |
| `MINIO_ENDPOINT` | `minio:4003` | `cdn.bankmega.local` |
| `MINIO_SECURE` | — | `true` |
| Kredensial MinIO | satu admin key global | 12 key per-bucket |

Kelompok variabel:

```
POSTGRES_*        host, port, db, user, password (URL-encoded), schema
REDIS_URL         redis://redis:6378/0
MINIO_*           endpoint, secure, 6 bucket, 12 key per-bucket, 2 prefix
LLM_*             base_url, api_key, model, temperature, seed,
                  reasoning_effort, timeout, api_version (worker saja)
OCR_*             opsional; string kosong -> None (field_validator worker/config.py)
RIPLAY_*          model, max_pages, render_scale, min_similarity
JWT_*, API_KEY    autentikasi
ADMIN_*           kredensial admin awal
DWH_API_*         App A :8002
TMS_API_*         App C :8008
VIEW_STREAM_*     App C :8010
COLLECTION_CAMPAIGNS   nama campaign penagihan (api/rbac.py:107)
CELERY_CONCURRENCY     default 8
REGISTRY, TAG          diisi Jenkins
```

Tiga kelas Settings, masing-masing subset dari yang sama:

| Kelas | Berkas | Cakupan |
|---|---|---|
| `Settings` | `api/dependencies.py` | paling lengkap |
| `WorkerSettings` | `worker/config.py` | tanpa JWT/admin; plus `llm_api_version`, `ocr_*` |
| `CoreSettings` | `core/core_config.py` | hanya MinIO yang dipakai kode bersama |

Ketiganya membaca `.env` yang sama, sehingga nilainya identik tanpa perlu saling
impor.

---

## 10. Build & Deploy

### Image bersifat self-contained

Kedua Dockerfile menyalin seluruh kode ke dalam image — **tidak** mengandalkan
bind-mount `.:/app` seperti compose monorepo dulu. Build context adalah **root
repo**, bukan subfolder:

```bash
docker build -f api/Dockerfile    -t qc-api    .
docker build -f worker/Dockerfile -t qc-worker .
```

Dependensi core diinstal lebih dulu, baru milik aplikasi — dua layer cache
terpisah, sehingga perubahan kode aplikasi tidak membatalkan cache instalasi core.

### Pipeline Jenkins

```
Checkout  ──►  git submodule update --init --recursive
Test      ──►  api    : PYTHONPATH=.:core pytest tests -q
               worker : import seluruh task (tidak punya test suite sendiri)
Guard     ──►  No Worker Import / No API Import
Build     ──►  docker build -f <app>/Dockerfile .
Push      ──►  registry
Deploy    ──►  docker compose up -d --no-deps <service>   (branch main saja)
```

### Urutan rilis yang wajib

```
1. core    commit + push        (pointer submodule menunjuk commit ini)
2. api     bump pointer, deploy (menjalankan alembic upgrade head)
3. worker  bump pointer, deploy
4. dashboard                    (rebuild kalau VITE_* berubah)
```

Membalik langkah 1 dan 2 membuat `git submodule update` gagal di server, karena
pointer menunjuk commit yang belum ada di remote.

---

## 11. Status & Catatan Cutover (2026-09-02)

Keempat repo sudah di `main` dan sinkron dengan `origin/main`. Yang **live saat
ini masih stack monorepo** (`telemarketing-qc-system-*`), bukan repo split.

### Perubahan yang sudah diterapkan untuk cutover

- `api/.env` + `worker/.env`: ditambah `VIEW_STREAM_*`, `TMS_API_*`,
  `COLLECTION_CAMPAIGNS`. Tanpa ini `view_streams.py:48` dan
  `tickets_daily.py:41` jatuh ke default `https://call-qc.bankmega.local`
  (host luar), bukan App C di `host.docker.internal`.
- `api/docker-compose.yml`: `postgres` dan `minio` diberi
  `profiles: ["local-infra"]` dan dilepas dari `depends_on` — keduanya eksternal.
  `redis` tetap lokal.
- `dashboard/Dockerfile` + compose: tambah build-arg `VITE_API_BASE`,
  `VITE_PDF_API_BASE`, `VITE_PDF_API_KEY`, `VITE_RESULTS_GROUPING`. `.env` tidak
  ikut build context (`.dockerignore`), jadi tanpa build-arg `VITE_PDF_API_KEY`
  jatuh ke `''` dan request PDF kehilangan API key.

### Selisih migrasi

```
alembic heads   -> 0051 (head)
alembic current -> 0025      (schema `dashboard` di 10.155.32.28)
```

26 migrasi tertunda (0026–0051). Pemeriksaan isi `upgrade()`-nya:

- **Tidak ada** `drop_table` maupun `drop_column`. Semua drop yang terlihat
  berada di `downgrade()`.
- Dua `alter_column`, keduanya pelebaran: `qc_status_requests.requested_status`
  `String(4)→String(10)` (0029), dan `users.role` `String(20)→String(50)` (0031).
- Lima `op.execute()`, semuanya backfill atau idempoten: mengisi `kb_text_raw`
  yang masih `NULL` (0027), mengisi kolom `provisi`/`penalti` yang baru
  ditambahkan (0028), `INSERT … ON CONFLICT DO NOTHING` plus penambahan JSONB
  bergerbang `NOT (permissions @> …)` (0044).

Isinya sebagian besar penambahan capability RBAC dan menu.

Karena `alembic upgrade head` jalan otomatis di `CMD`, ke-26 migrasi ini akan
diterapkan ke DWH produksi pada `up` pertama container `api`.

### Urutan `up`

Runbook lengkapnya ada di **bagian 12**, termasuk verifikasi tiap langkah dan
tabel penanganan kegagalan.

Backup tersedia di tiap repo: `.env.bak.20260902`,
`docker-compose.yml.bak.20260902`, `Dockerfile.bak.20260902`.

---

## 12. Menjalankan Aplikasi (Docker Compose)

Runbook lengkap untuk menyalakan sistem dari nol. Perintahnya sudah disesuaikan
dengan hasil cutover 2026-09-02 (bagian 11) — Postgres dan MinIO **eksternal**,
hanya Redis yang lokal.

### 12.1 Yang sebenarnya dinyalakan

Pertanyaan yang paling sering muncul: *"kalau saya `up` keempat aplikasi…"*.
Yang bisa di-`up` sebenarnya **tiga repo, lima container**. `core` bukan salah
satunya.

| Repo | Perintah `up` | Container yang naik |
|---|---|---|
| `telemarketing-qc-api` | ya | `api`, `redis` |
| `telemarketing-qc-worker` | ya | `worker`, `flower` |
| `telemarketing-qc-dashboard` | ya | `dashboard` |
| `telemarketing-qc-core` | **tidak** | — |

`core` tidak punya `docker-compose.yml`, tidak punya `Dockerfile`, dan tidak
pernah menjadi container. Perannya habis saat **build**: isinya di-`COPY` datar
ke `/app` di image api dan worker (lihat bagian 2). Yang perlu dilakukan
terhadap `core` hanyalah memastikan folder `core/` terisi sebelum
`docker build` — dan itu langkah pertama di bawah.

Container yang dihasilkan:

```
local/qc-api:latest        -> service `api`       :4000
redis:7-alpine             -> service `redis`     :6378
local/qc-worker:latest     -> service `worker`    (tanpa port)
local/qc-worker:latest     -> service `flower`    :4005   (image sama, beda command)
local/qc-dashboard:latest  -> service `dashboard` :4006
```

---

### 12.2 Langkah 0 — Prasyarat

```bash
# Konektivitas ke infra eksternal (dijalankan dari host)
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/10.155.32.28/5432' && echo "postgres OK"
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/cdn.bankmega.local/443' && echo "minio CDN OK"
for p in 8000 8002 8008 8010; do
  timeout 3 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$p" && echo "App :$p UP"
done
```

Keempat App harus UP sebelum `up`, karena `DWH_API_BASE_URL`,
`TMS_API_BASE_URL`, dan `VIEW_STREAM_BASE_URL` menunjuk ke sana lewat
`host.docker.internal`.

Pastikan juga `.env` ada di ketiga repo:

```bash
for r in api worker dashboard; do
  f=/data/scorecard_v2/telemarketing-qc-$r/.env
  [ -f "$f" ] && echo "$r: $(grep -cE '^[A-Za-z_]+=' $f) variabel" || echo "$r: .env HILANG"
done
```

Jumlah yang diharapkan setelah cutover: api **58**, worker **59**, dashboard **51**.

---

### 12.3 Langkah 1 — Isi submodule `core`

**Ini langkah yang paling sering terlewat, dan akibatnya paling membingungkan.**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git submodule update --init --recursive

cd ../telemarketing-qc-worker
git submodule update --init --recursive
```

Verifikasi — folder harus berisi, bukan kosong:

```bash
for r in api worker; do
  d=/data/scorecard_v2/telemarketing-qc-$r/core
  n=$(ls "$d" 2>/dev/null | wc -l)
  echo "$r/core: $n entri $([ "$n" -gt 0 ] && echo OK || echo '<-- KOSONG, build akan gagal')"
done
```

Pastikan pointer submodule sama di api dan worker (harus commit yang sama):

```bash
for r in api worker; do
  echo "$r: $(git -C /data/scorecard_v2/telemarketing-qc-$r submodule status)"
done
```

Kalau `core/` kosong, `docker build` berhenti dengan pesan seperti:

```
ERROR: failed to compute cache key: "/core/db": not found
```

---

### 12.4 Langkah 2 — Network bersama

Ketiga compose memakai network eksternal `qc-net`. Dibuat sekali per host:

```bash
docker network ls | grep -q qc-net || docker network create qc-net
```

Tanpa ini, `up` gagal seketika:

```
network qc-net declared as external, but could not be found
```

---

### 12.5 Langkah 3 — Bebaskan port

Kalau stack monorepo masih jalan, port 4000, 4005, 4006, dan 6378 masih dipakai:

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep telemarketing-qc-system
cd /data/scorecard_v2/telemarketing-qc-system && docker compose down
```

Cek tidak ada sisa yang menempel:

```bash
for p in 4000 4005 4006 6378; do
  echo "port $p: $(docker ps --format '{{.Names}} {{.Ports}}' | grep -c ":$p->") pemakai"
done
```

Port 5432, 4003, dan 4004 **tidak** lagi dipakai repo split — Postgres dan MinIO
sekarang eksternal.

---

### 12.6 Langkah 4 — API (dan Redis)

API harus naik lebih dulu karena dialah **satu-satunya pemilik migrasi**.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker compose up -d --build
```

Compose menyalakan `redis` lalu `api` (menunggu Redis `healthy`). Postgres dan
MinIO lokal **tidak** ikut naik — keduanya ada di profile `local-infra`.

Ikuti lognya sampai migrasi selesai:

```bash
docker compose logs -f api
```

Yang harus terlihat, berurutan:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Running upgrade 0025 -> 0026, ...
...
INFO  [alembic.runtime.migration] Running upgrade 0050 -> 0051, ...
[multi-bucket-minio] Bucket 'transcripts' -> access_key='vtt-<bucket>' @ cdn.bankmega.local (secure=True)
INFO:     Uvicorn running on http://0.0.0.0:4000
```

> Kalau yang muncul `[minio] Belum ada kredensial per-bucket — pakai satu client
> global`, berarti `MINIO_ACCESS_KEY_*` tidak terbaca dan aplikasi mencoba
> memakai admin key yang tidak ada di `.env` produksi. Periksa `.env`.

Verifikasi:

```bash
curl -sf http://localhost:4000/health && echo " <- api sehat"
docker compose exec api alembic current          # harus 0051 (head)
curl -s http://localhost:4000/docs -o /dev/null -w "docs: %{http_code}\n"
```

**Jangan lanjut ke worker sebelum `alembic current` menunjukkan `0051 (head)`.**
Worker memakai model yang mengasumsikan skema terbaru.

---

### 12.7 Langkah 5 — Worker dan Flower

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker compose up -d --build
```

Satu image dipakai dua service; bedanya hanya `command`.

Verifikasi worker benar-benar tersambung ke broker dan semua task ter-register:

```bash
docker compose logs --tail=40 worker
docker compose exec worker celery -A worker.celery_app inspect registered
```

Tiga task harus muncul:

```
worker.tasks.process_transcript.process_transcript
worker.tasks.process_document.process_document
worker.tasks.reprocess_ticket.reprocess_ticket
```

Kalau log berisi `ModuleNotFoundError: No module named 'compliance'`, submodule
`core` kosong saat build — ulangi langkah 12.3 lalu `docker compose build --no-cache worker`.

Flower:

```bash
curl -s http://localhost:4005/api/workers -o /dev/null -w "flower: %{http_code}\n"
```

> Flower terbuka tanpa autentikasi (`FLOWER_UNAUTHENTICATED_API=true`). Batasi
> port 4005 di firewall host — jangan diekspos keluar.

---

### 12.8 Langkah 6 — Dashboard

```bash
cd /data/scorecard_v2/telemarketing-qc-dashboard
docker compose up -d --build
```

Build memakan waktu paling lama (`npm ci` + `npm run build`).

Verifikasi bundle benar-benar membawa prefix yang tepat:

```bash
curl -sI http://localhost:4006/ | head -3

# `/api-b` harus ada di dalam bundle. Kalau kosong, VITE_API_URL tidak terbawa
# saat build dan login akan dijawab 422.
docker compose exec dashboard sh -c \
  "grep -rlo '/api-b' /usr/share/nginx/html/assets/ | head -3"
```

> Ingat: `VITE_*` di-*bake* saat build. Mengubah `.env` lalu `docker compose
> restart dashboard` **tidak berpengaruh** — harus `--build`.

---

### 12.9 Langkah 7 — nginx host

Kalau vhost belum terpasang atau berubah:

```bash
cd /data/scorecard_v2/telemarketing-qc-dashboard
diff /etc/nginx/sites-available/default deploy/nginx/call-qc.bankmega.local.conf

sudo cp deploy/nginx/call-qc.bankmega.local.conf /etc/nginx/sites-available/default
sudo nginx -t && sudo systemctl reload nginx
```

---

### 12.10 Verifikasi menyeluruh

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'qc-|telemarketing'
```

Daftar periksa:

| # | Yang dicek | Perintah | Hasil yang benar |
|---|---|---|---|
| 1 | Lima container hidup | `docker ps` | `api`, `redis`, `worker`, `flower`, `dashboard` |
| 2 | API sehat | `curl -sf localhost:4000/health` | 200 |
| 3 | Skema mutakhir | `docker compose exec api alembic current` | `0051 (head)` |
| 4 | Mode MinIO benar | `docker compose logs api \| grep multi-bucket` | ada baris per bucket |
| 5 | Task ter-register | `celery ... inspect registered` | 3 task |
| 6 | Worker menjawab | `celery ... inspect ping` | `pong` |
| 7 | Dashboard tersaji | `curl -sI localhost:4006/` | 200 |
| 8 | Prefix ter-bake | `grep -rlo '/api-b' .../assets/` | ada hasil |
| 9 | Lewat nginx | `curl -k https://call-qc.bankmega.local/api-b/health` | 200 |
| 10 | **Login dari browser** | — | masuk, bukan 422 |

Nomor 10 adalah uji yang paling cepat menangkap salah konfigurasi routing.
Kalau 422, `/auth/login` nyasar ke App C :8008 — periksa `VITE_API_URL` dan
`location /api-b/` di nginx.

---

### 12.11 Urutan lengkap dalam satu blok

Untuk disalin saat sudah paham tiap langkahnya:

```bash
set -e
BASE=/data/scorecard_v2

# 1. submodule core
for r in api worker; do
  git -C $BASE/telemarketing-qc-$r submodule update --init --recursive
  [ -d "$BASE/telemarketing-qc-$r/core/compliance" ] || { echo "core kosong di $r"; exit 1; }
done

# 2. network
docker network ls | grep -q qc-net || docker network create qc-net

# 3. bebaskan port
cd $BASE/telemarketing-qc-system && docker compose down

# 4. api (+redis) — migrasi jalan di sini
cd $BASE/telemarketing-qc-api && docker compose up -d --build
until curl -sf http://localhost:4000/health >/dev/null; do sleep 3; done
docker compose exec -T api alembic current

# 5. worker + flower
cd $BASE/telemarketing-qc-worker && docker compose up -d --build

# 6. dashboard
cd $BASE/telemarketing-qc-dashboard && docker compose up -d --build

echo "selesai"
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

---

### 12.12 Operasi harian

```bash
# Log
docker compose logs -f api                   # di repo masing-masing
docker compose logs --tail=100 worker

# Restart tanpa rebuild (untuk perubahan .env sisi backend)
docker compose up -d --force-recreate api

# Rebuild satu service setelah kode berubah
docker compose up -d --build worker

# Matikan satu stack
docker compose down                          # container saja
docker compose down -v                       # + volume (hati-hati)

# Migrasi manual
docker compose exec api alembic upgrade head
docker compose exec api alembic revision -m "deskripsi"

# Script maintenance (butuh runtime worker: MinIO + pdfplumber)
docker compose exec worker python /app/scripts/backfill_generated_at.py --dry-run
docker compose exec worker python /app/scripts/backfill_reference_cashline_ids.py --dry-run

# Infra lokal untuk uji coba (Postgres + MinIO dalam container)
docker compose --profile local-infra up -d
```

---

### 12.13 Kalau gagal

| Gejala | Sebab | Tindakan |
|---|---|---|
| `network qc-net ... could not be found` | Network belum dibuat | `docker network create qc-net` |
| `failed to compute cache key: "/core/db"` | Submodule kosong | Langkah 12.3, lalu build ulang |
| `ModuleNotFoundError: compliance` di log worker | Image dibangun saat `core/` kosong | `docker compose build --no-cache worker` |
| `port is already allocated` | Stack monorepo masih jalan | Langkah 12.5 |
| API restart terus, log Alembic error | Migrasi gagal di tengah | Cek log; **jangan** paksa restart — periksa `alembic current` dulu |
| `MINIO_ACCESS_KEY variable is not set` | Wajar di mode CDN | Abaikan; hanya relevan untuk profile `local-infra` |
| Log `[minio] Belum ada kredensial per-bucket` | `MINIO_*_KEY_<BUCKET>` tidak terbaca | Periksa `.env` api/worker |
| Login dijawab 422 | `VITE_API_URL` tanpa `/api-b` | Rebuild dashboard dengan build-arg benar |
| Semua request API 404 | Trailing slash `proxy_pass` hilang | Periksa vhost nginx |
| Worker diam, task menumpuk | Worker tidak tersambung broker | `celery ... inspect ping`; cek `REDIS_URL` |
| PDF gagal / tanpa otorisasi | `VITE_PDF_API_KEY` kosong di bundle | Rebuild dashboard (build-arg, bukan `.env`) |

---

### 12.14 Rollback ke stack monorepo

```bash
cd /data/scorecard_v2/telemarketing-qc-api       && docker compose down
cd /data/scorecard_v2/telemarketing-qc-worker    && docker compose down
docker compose down

cd /data/scorecard_v2/telemarketing-qc-system    && docker compose up -d
```

Konfigurasi sebelum cutover tersedia di tiap repo: `.env.bak.20260902`,
`docker-compose.yml.bak.20260902`, `Dockerfile.bak.20260902`.

> **Migrasi database tidak ikut mundur.** Stack monorepo menunjuk Postgres
> lokal (`bankqc`), sedangkan repo split menulis ke DWH schema `dashboard` —
> dua database berbeda, jadi rollback container tidak membatalkan migrasi yang
> sudah diterapkan ke DWH.

---

## 13. Deploy ke Kubernetes (rancangan)

> **Status: belum diterapkan.** Per 2 September 2026 tidak ada manifest
> Kubernetes maupun Helm chart di keempat repo — yang ada hanya
> `docker-compose.yml` dan Jenkinsfile berbasis Docker. Bagian ini adalah
> rancangan beserta manifest siap pakai, bukan catatan sesuatu yang sudah
> berjalan. Perlakukan sebagai titik awal yang masih harus diuji di cluster.

### 13.1 Kenapa arsitektur ini relatif ramah Kubernetes

Setelah cutover ke infra produksi, seluruh state ada **di luar** aplikasi:

| Komponen | Lokasi | Butuh volume? |
|---|---|---|
| PostgreSQL | `10.155.32.28`, schema `dashboard` | tidak |
| Object storage | `cdn.bankmega.local` (MinIO CDN) | tidak |
| Redis | broker Celery, dalam cluster | opsional |
| `/tmp/audio` di worker | ruang kerja sementara | `emptyDir` |

Tiga dari empat container jadi **stateless**, jadi tidak ada PVC yang wajib.
Satu-satunya kandidat PVC adalah Redis, dan itu pun hanya kalau antrean tidak
boleh hilang saat pod pindah node.

### 13.2 Tujuh hal yang berubah dari Compose

Ini bagian yang paling mudah keliru — jangan menerjemahkan compose baris per
baris.

**1. `alembic upgrade head` harus keluar dari `CMD`.**
Di Compose hanya ada satu container `api`, jadi migrasi di `CMD` aman:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
```

Di Kubernetes dengan `replicas: 3`, ketiga pod menjalankan `alembic upgrade head`
bersamaan dan saling berebut tabel `alembic_version`. Migrasi harus dipindahkan
ke **Job** tersendiri yang dijalankan sekali sebelum rollout. Deployment
menimpa `command` supaya hanya menjalankan uvicorn.

**2. `host.docker.internal` tidak ada di Kubernetes.**
App A (`:8000`, `:8002`) dan App C (`:8008`, `:8010`) berjalan di host, di luar
cluster. `extra_hosts` diganti Service tanpa selector + Endpoints eksplisit,
lalu `DWH_API_BASE_URL`/`TMS_API_BASE_URL`/`VIEW_STREAM_BASE_URL` menunjuk nama
Service itu.

**3. `.env` pecah jadi Secret dan ConfigMap.**
Kredensial (Postgres, MinIO per-bucket, LLM, JWT, API key) ke Secret; sisanya
boleh ConfigMap. Cara termudah tetap memakai berkas `.env` yang sudah ada.

**4. `VITE_*` tetap terikat saat build.**
Ini tidak berubah di Kubernetes. Vite mengganti nilainya saat `npm run build`,
jadi **satu image dashboard = satu environment**. ConfigMap tidak bisa
mengubahnya saat runtime. Kalau ingin satu image untuk semua environment,
perlu perubahan kode ke runtime config (`/config.json` yang di-fetch saat boot).

**5. nginx host diganti Ingress.**
Peta prefix `/api-b`, `/api-a`, `/api/download` harus dipertahankan **persis**,
termasuk perilaku strip-prefix-nya — `/api-b` sudah terkunci di dalam bundle.

**6. `qc-net` diganti namespace.**
Ketiga compose berbagi network eksternal `qc-net`; di Kubernetes cukup satu
namespace, dan service saling memanggil lewat DNS internal.

**7. Submodule `core` tidak berubah sama sekali.**
`core` adalah urusan **build**, bukan runtime. CI tetap wajib menjalankan
`git submodule update --init --recursive` sebelum `docker build`. Kubernetes
tidak pernah melihat folder `core/` — yang ia terima hanya image yang isinya
sudah datar di `/app`.

---

### 13.3 Prasyarat

```bash
kubectl version --client
kubectl config current-context          # pastikan cluster yang benar

# Cluster harus bisa menjangkau:
#   10.155.32.28:5432        PostgreSQL DWH
#   cdn.bankmega.local:443   MinIO CDN
#   host App A :8000 :8002   dan App C :8008 :8010
#   Azure AI Foundry (LLM)   HTTPS keluar
```

Image sudah ter-push ke registry (Jenkins `Build` + `Push` sudah menanganinya):

```
registry.gitlab.<domain>/<group>/qc-api:<tag>
registry.gitlab.<domain>/<group>/qc-worker:<tag>
registry.gitlab.<domain>/<group>/qc-dashboard:<tag>
```

---

### 13.4 Langkah 1 — Namespace dan akses registry

```bash
kubectl create namespace telemarketing-qc

kubectl -n telemarketing-qc create secret docker-registry gitlab-registry \
  --docker-server=registry.gitlab.<domain> \
  --docker-username='<user>' \
  --docker-password='<token>'
```

Semua perintah berikutnya memakai `-n telemarketing-qc`. Pertimbangkan
`kubectl config set-context --current --namespace=telemarketing-qc` agar tidak
lupa.

---

### 13.5 Langkah 2 — Secret dan ConfigMap dari `.env`

`.env` yang sudah dibenahi saat cutover bisa dipakai langsung.
`--from-env-file` mengabaikan baris komentar dan baris kosong:

```bash
cd /data/scorecard_v2/telemarketing-qc-api

kubectl -n telemarketing-qc create secret generic qc-env \
  --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

Worker memakai `.env` yang isinya hampir sama; kalau ada selisih
(`LLM_API_VERSION`, `OCR_*` hanya ada di worker), buat Secret kedua:

```bash
cd ../telemarketing-qc-worker
kubectl -n telemarketing-qc create secret generic qc-env-worker \
  --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

Dua nilai **wajib ditimpa** karena menunjuk `host.docker.internal` yang tidak
ada di cluster — ditangani lewat `env` eksplisit di Deployment (lihat 13.9),
yang menang atas `envFrom`.

> **Catatan keamanan.** Secret Kubernetes hanya di-base64, bukan dienkripsi.
> Kalau cluster belum memakai `EncryptionConfiguration` at-rest atau External
> Secrets Operator, tingkat perlindungannya setara berkas `.env` di server —
> jangan anggap lebih aman hanya karena namanya "Secret".

---

### 13.6 Langkah 3 — Redis

Broker dan result backend Celery. Port **6378**, bukan 6379.

```yaml
# redis.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: telemarketing-qc
spec:
  replicas: 1                 # broker Celery — jangan di-scale
  strategy:
    type: Recreate            # hindari dua Redis hidup bersamaan
  selector:
    matchLabels: { app: redis }
  template:
    metadata:
      labels: { app: redis }
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          args: ["redis-server", "--port", "6378"]
          ports:
            - containerPort: 6378
          readinessProbe:
            exec:
              command: ["redis-cli", "-p", "6378", "ping"]
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: { cpu: 50m, memory: 128Mi }
            limits:   { memory: 512Mi }
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          emptyDir: {}        # ganti PVC kalau antrean tidak boleh hilang
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: telemarketing-qc
spec:
  selector: { app: redis }
  ports:
    - port: 6378
      targetPort: 6378
```

Nama Service `redis` membuat `REDIS_URL=redis://redis:6378/0` di `.env` tetap
valid tanpa diubah.

```bash
kubectl apply -f redis.yaml
kubectl -n telemarketing-qc rollout status deploy/redis
```

---

### 13.7 Langkah 4 — Service untuk App A dan App C di luar cluster

```yaml
# external-apps.yaml
apiVersion: v1
kind: Service
metadata:
  name: app-a                 # DWH :8002 dan STT :8000
  namespace: telemarketing-qc
spec:
  ports:
    - name: dwh
      port: 8002
      targetPort: 8002
    - name: stt
      port: 8000
      targetPort: 8000
---
apiVersion: v1
kind: Endpoints
metadata:
  name: app-a                 # nama HARUS sama dengan Service
  namespace: telemarketing-qc
subsets:
  - addresses:
      - ip: 10.155.32.XX      # ISI: IP host tempat App A berjalan
    ports:
      - name: dwh
        port: 8002
      - name: stt
        port: 8000
---
apiVersion: v1
kind: Service
metadata:
  name: app-c                 # tickets-daily :8008, view-streams/PDF :8010
  namespace: telemarketing-qc
spec:
  ports:
    - name: tms
      port: 8008
      targetPort: 8008
    - name: viewstream
      port: 8010
      targetPort: 8010
---
apiVersion: v1
kind: Endpoints
metadata:
  name: app-c
  namespace: telemarketing-qc
subsets:
  - addresses:
      - ip: 10.155.32.XX      # ISI: IP host tempat App C berjalan
    ports:
      - name: tms
        port: 8008
      - name: viewstream
        port: 8010
```

Service tanpa `selector` + Endpoints manual dipilih ketimbang `ExternalName`
karena `ExternalName` hanya menghasilkan CNAME — ia tidak bisa memetakan port,
dan menyulitkan Ingress.

Verifikasi endpoint benar-benar terisi:

```bash
kubectl -n telemarketing-qc get endpoints app-a app-c
```

Kalau kolom `ENDPOINTS` kosong, nama Endpoints tidak cocok dengan nama Service.

---

### 13.8 Langkah 5 — Job migrasi

**Jalankan ini sebelum Deployment api, dan pastikan selesai.**

```yaml
# migrate-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: qc-api-migrate-0051    # ganti nama tiap rilis; Job bersifat immutable
  namespace: telemarketing-qc
spec:
  backoffLimit: 0              # gagal = berhenti, jangan ulangi migrasi separuh jalan
  template:
    spec:
      restartPolicy: Never
      imagePullSecrets:
        - name: gitlab-registry
      containers:
        - name: migrate
          image: registry.gitlab.<domain>/<group>/qc-api:<tag>
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef: { name: qc-env }
          env:
            - name: PYTHONPATH
              value: /app
```

```bash
kubectl apply -f migrate-job.yaml
kubectl -n telemarketing-qc wait --for=condition=complete job/qc-api-migrate-0051 --timeout=600s
kubectl -n telemarketing-qc logs job/qc-api-migrate-0051
```

Kalau Job gagal, **jangan lanjut** ke Deployment — periksa lognya dulu. Untuk
rilis yang dimaksud dokumen ini, Job akan menerapkan 26 migrasi (0026–0051);
rinciannya di bagian 11.

---

### 13.9 Langkah 6 — Deployment API

```yaml
# api.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qc-api
  namespace: telemarketing-qc
spec:
  replicas: 2
  selector:
    matchLabels: { app: qc-api }
  template:
    metadata:
      labels: { app: qc-api }
    spec:
      imagePullSecrets:
        - name: gitlab-registry
      containers:
        - name: api
          image: registry.gitlab.<domain>/<group>/qc-api:<tag>
          # WAJIB menimpa CMD image: tanpa ini setiap replika menjalankan
          # `alembic upgrade head` dan saling berebut tabel alembic_version.
          command: ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "4000"]
          ports:
            - containerPort: 4000
          envFrom:
            - secretRef: { name: qc-env }
          env:
            - name: PYTHONPATH
              value: /app
            # Menimpa nilai host.docker.internal dari .env
            - name: DWH_API_BASE_URL
              value: http://app-a:8002
            - name: TMS_API_BASE_URL
              value: http://app-c:8008
            - name: VIEW_STREAM_BASE_URL
              value: http://app-c:8010
          readinessProbe:
            httpGet: { path: /health, port: 4000 }
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health, port: 4000 }
            initialDelaySeconds: 30
            periodSeconds: 30
          resources:
            requests: { cpu: 200m, memory: 512Mi }
            limits:   { memory: 2Gi }
---
apiVersion: v1
kind: Service
metadata:
  name: qc-api
  namespace: telemarketing-qc
spec:
  selector: { app: qc-api }
  ports:
    - port: 4000
      targetPort: 4000
```

Probe `/health` memakai endpoint yang sama dengan `HEALTHCHECK` di
`api/Dockerfile`, jadi tidak ada endpoint baru yang perlu dibuat.

---

### 13.10 Langkah 7 — Deployment Worker dan Flower

Satu image, dua Deployment — persis seperti pola anchor `*worker-image` di
Compose.

```yaml
# worker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qc-worker
  namespace: telemarketing-qc
spec:
  replicas: 2
  selector:
    matchLabels: { app: qc-worker }
  template:
    metadata:
      labels: { app: qc-worker }
    spec:
      # task_time_limit=1800 di worker/celery_app.py. Grace period harus
      # melebihinya supaya task yang sedang jalan tidak dibunuh saat rollout.
      terminationGracePeriodSeconds: 1860
      imagePullSecrets:
        - name: gitlab-registry
      containers:
        - name: worker
          image: registry.gitlab.<domain>/<group>/qc-worker:<tag>
          args:
            - celery
            - -A
            - worker.celery_app
            - worker
            - --loglevel=info
            - --concurrency=8
          envFrom:
            - secretRef: { name: qc-env-worker }
          env:
            - name: PYTHONPATH
              value: /app
            - name: DWH_API_BASE_URL
              value: http://app-a:8002
            - name: TMS_API_BASE_URL
              value: http://app-c:8008
            - name: VIEW_STREAM_BASE_URL
              value: http://app-c:8010
          readinessProbe:
            exec:
              # `sh -c` wajib: exec tidak melewati shell, jadi $(hostname)
              # tidak akan diekspansi kalau ditulis sebagai array argumen.
              command:
                - sh
                - -c
                - celery -A worker.celery_app inspect ping -d celery@$(hostname)
            initialDelaySeconds: 30
            periodSeconds: 60
            timeoutSeconds: 20
          resources:
            requests: { cpu: 500m, memory: 1Gi }
            limits:   { memory: 4Gi }
          volumeMounts:
            - name: audio
              mountPath: /tmp/audio
      volumes:
        - name: audio
          emptyDir: {}
```

`task_acks_late=True` dan `task_reject_on_worker_lost=True` sudah aktif, jadi
task yang terputus karena pod dievakuasi akan dikembalikan ke antrean — bukan
hilang. Ini yang membuat worker aman di-scale dan di-rollout.

Flower — image sama, `args` berbeda:

```yaml
# flower.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qc-flower
  namespace: telemarketing-qc
spec:
  replicas: 1
  selector:
    matchLabels: { app: qc-flower }
  template:
    metadata:
      labels: { app: qc-flower }
    spec:
      imagePullSecrets:
        - name: gitlab-registry
      containers:
        - name: flower
          image: registry.gitlab.<domain>/<group>/qc-worker:<tag>
          args: ["celery", "-A", "worker.celery_app", "flower", "--port=4005"]
          ports:
            - containerPort: 4005
          envFrom:
            - secretRef: { name: qc-env-worker }
          env:
            - name: PYTHONPATH
              value: /app
            - name: FLOWER_UNAUTHENTICATED_API
              value: "true"
          resources:
            requests: { cpu: 50m, memory: 128Mi }
            limits:   { memory: 512Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: qc-flower
  namespace: telemarketing-qc
spec:
  selector: { app: qc-flower }
  ports:
    - port: 4005
      targetPort: 4005
```

> **Flower terbuka tanpa autentikasi.** `FLOWER_UNAUTHENTICATED_API=true` wajib
> ada karena Flower 2.x menolak `/api/*` dengan 401 tanpanya, dan tidak ada flag
> CLI penggantinya. Di Compose ini dibatasi di firewall host. Di Kubernetes,
> **jangan pasang Ingress untuk Flower** — akses lewat port-forward saja:
>
> ```bash
> kubectl -n telemarketing-qc port-forward svc/qc-flower 4005:4005
> ```
>
> Kalau tetap perlu Ingress, pasang NetworkPolicy dan basic-auth di Ingress.

---

### 13.11 Langkah 8 — Deployment Dashboard

```yaml
# dashboard.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qc-dashboard
  namespace: telemarketing-qc
spec:
  replicas: 2
  selector:
    matchLabels: { app: qc-dashboard }
  template:
    metadata:
      labels: { app: qc-dashboard }
    spec:
      imagePullSecrets:
        - name: gitlab-registry
      containers:
        - name: dashboard
          image: registry.gitlab.<domain>/<group>/qc-dashboard:<tag>
          ports:
            - containerPort: 4006
          readinessProbe:
            httpGet: { path: /index.html, port: 4006 }
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { memory: 256Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: qc-dashboard
  namespace: telemarketing-qc
spec:
  selector: { app: qc-dashboard }
  ports:
    - port: 4006
      targetPort: 4006
```

Dashboard murni penyaji berkas statis, jadi aman di-scale.

> Image ini terikat ke satu environment karena `VITE_*` di-*bake* saat build.
> Untuk environment lain, build ulang dengan build-arg berbeda:
>
> ```bash
> docker build -t qc-dashboard:staging \
>   --build-arg VITE_API_URL=/api-b \
>   --build-arg VITE_API_BASE=/api-a \
>   --build-arg VITE_PDF_API_KEY=<key> \
>   -f Dockerfile .
> ```

---

### 13.12 Langkah 9 — Ingress

Bagian paling rawan. Peta prefix harus **identik** dengan nginx host, karena
`/api-b` sudah terkunci di dalam bundle.

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qc
  namespace: telemarketing-qc
  annotations:
    # $2 = capture group kedua di setiap path -> meniru trailing slash pada
    # `proxy_pass http://localhost:4000/` yang MEMBUANG prefix.
    nginx.ingress.kubernetes.io/rewrite-target: /$2
    nginx.ingress.kubernetes.io/proxy-body-size: "200m"   # unggahan audio/PDF
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
spec:
  ingressClassName: nginx
  tls:
    - hosts: [call-qc.bankmega.local]
      secretName: bankmegalocal-tls
  rules:
    - host: call-qc.bankmega.local
      http:
        paths:
          # App B — prefix DIBUANG
          - path: /api-b(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: qc-api
                port: { number: 4000 }
          # App A — prefix DIBUANG
          - path: /api-a(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: app-a
                port: { number: 8000 }
          # Frontend
          - path: /()(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: qc-dashboard
                port: { number: 4006 }
```

Jalur yang **path-nya utuh** (`/api/download`, `/api/view-streams/`) tidak boleh
memakai `rewrite-target` yang sama, jadi ditaruh di Ingress terpisah tanpa
anotasi rewrite:

```yaml
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qc-passthrough
  namespace: telemarketing-qc
  # TANPA rewrite-target: App C menerima path utuh, meniru
  # `proxy_pass http://localhost:8010` yang TANPA trailing slash.
spec:
  ingressClassName: nginx
  tls:
    - hosts: [call-qc.bankmega.local]
      secretName: bankmegalocal-tls
  rules:
    - host: call-qc.bankmega.local
      http:
        paths:
          - path: /api/download
            pathType: Prefix
            backend:
              service:
                name: app-c
                port: { number: 8010 }
          - path: /api/view-streams
            pathType: Prefix
            backend:
              service:
                name: app-c
                port: { number: 8010 }
```

Sertifikat TLS:

```bash
kubectl -n telemarketing-qc create secret tls bankmegalocal-tls \
  --cert=/etc/ssl/bankmegalocal/bankmegalocal.crt \
  --key=/etc/ssl/bankmegalocal/bankmegalocal.key
```

> **`/auth/login`, `/me`, `/tickets`, `/qc-result-logs` milik aplikasi lain
> (App C :8008), bukan dashboard ini.** Kalau rute-rute itu perlu tetap
> dilayani domain yang sama, tambahkan di Ingress passthrough dengan backend
> `app-c:8008`. Jangan mengarahkannya ke `qc-api` — hasilnya 422, persis
> jebakan `VITE_API_URL` yang dijelaskan di bagian 8.

---

### 13.13 Urutan rollout

Urutannya sama dengan Compose, dan alasannya juga sama.

```bash
NS=telemarketing-qc

# 1. Infra dalam cluster
kubectl apply -f redis.yaml -f external-apps.yaml
kubectl -n $NS rollout status deploy/redis
kubectl -n $NS get endpoints app-a app-c        # jangan kosong

# 2. Migrasi — HARUS selesai sebelum api naik
kubectl apply -f migrate-job.yaml
kubectl -n $NS wait --for=condition=complete job/qc-api-migrate-0051 --timeout=600s

# 3. API
kubectl apply -f api.yaml
kubectl -n $NS rollout status deploy/qc-api

# 4. Worker + Flower — SETELAH migrasi, karena skemanya sudah berubah
kubectl apply -f worker.yaml -f flower.yaml
kubectl -n $NS rollout status deploy/qc-worker

# 5. Dashboard
kubectl apply -f dashboard.yaml
kubectl -n $NS rollout status deploy/qc-dashboard

# 6. Ingress
kubectl apply -f ingress.yaml
```

---

### 13.14 Verifikasi

```bash
NS=telemarketing-qc

kubectl -n $NS get pods -o wide
kubectl -n $NS get endpoints                       # app-a & app-c harus terisi

# API sehat dan terhubung ke DWH
kubectl -n $NS exec deploy/qc-api -- curl -sf http://localhost:4000/health

# Worker terdaftar di broker
kubectl -n $NS exec deploy/qc-worker -- \
  celery -A worker.celery_app inspect registered

# MinIO memilih mode yang benar — cari baris ini di log api:
#   [multi-bucket-minio] Bucket 'transcripts' -> access_key='vtt-<bucket>' @ cdn.bankmega.local
# Kalau yang muncul "[minio] Belum ada kredensial per-bucket", Secret
# MINIO_ACCESS_KEY_* tidak terbaca.
kubectl -n $NS logs deploy/qc-api | grep -i minio | head

# Revisi Alembic yang aktif
kubectl -n $NS exec deploy/qc-api -- alembic current

# Dari luar
curl -kI https://call-qc.bankmega.local/
curl -k  https://call-qc.bankmega.local/api-b/health
```

Uji ujung-ke-ujung yang paling cepat menangkap salah konfigurasi: **login dari
browser**. Kalau dijawab 422, berarti `/auth/login` nyasar ke App C — periksa
Ingress dan `VITE_API_URL` di image dashboard.

---

### 13.15 Rollback

```bash
NS=telemarketing-qc

kubectl -n $NS rollout undo deploy/qc-api
kubectl -n $NS rollout undo deploy/qc-worker
kubectl -n $NS rollout undo deploy/qc-dashboard
```

> **Migrasi database tidak ikut ter-rollback.** `rollout undo` hanya
> mengembalikan image, bukan skema. Kalau rilis yang gagal mengandung migrasi,
> versi lama aplikasi bisa saja tidak cocok dengan skema baru. Untuk kasus ini
> ke-26 migrasi bersifat additive (tidak ada `drop_table`/`drop_column` di
> `upgrade()`), jadi kode lama umumnya masih jalan — tapi itu **kebetulan pada
> rilis ini**, bukan jaminan umum. Untuk rilis yang mengubah kolom secara
> destruktif, siapkan `alembic downgrade` terpisah dan uji lebih dulu.

Kembali sepenuhnya ke Docker Compose:

```bash
kubectl delete namespace telemarketing-qc
cd /data/scorecard_v2/telemarketing-qc-api && docker compose up -d
```

---

### 13.16 Pekerjaan lanjutan yang belum tercakup

| Hal | Catatan |
|---|---|
| Autoscaling worker | HPA berbasis CPU kurang tepat untuk beban LLM. Ukur panjang antrean Redis lewat KEDA (`ScaledObject` tipe `redis`) |
| PodDisruptionBudget | `minAvailable: 1` untuk `qc-api` dan `qc-dashboard` |
| NetworkPolicy | Batasi akses ke `qc-flower` dan `redis` hanya dari dalam namespace |
| Enkripsi Secret | `EncryptionConfiguration` at-rest, atau External Secrets Operator |
| Helm / Kustomize | Manifest di atas masih statis; `<tag>` dan `<domain>` perlu di-template |
| CI | Jenkinsfile masih `docker compose up -d`; stage `Deploy` perlu diganti `kubectl set image` atau `helm upgrade` |
| Log & metrik | Belum ada; `/metrics` juga belum diekspos aplikasi |
| Runtime config dashboard | Selama `VITE_*` di-bake saat build, satu image tetap = satu environment |

---

## 14. Jebakan yang Sudah Terbukti

| Gejala | Sebab |
|---|---|
| `docker build` berhenti di `COPY core/...` | Clone tanpa `--recurse-submodules`; `core/` kosong |
| `ModuleNotFoundError: compliance` di luar Docker | Lupa `PYTHONPATH=.:core` |
| Login dashboard dijawab **422** | `VITE_API_URL` tanpa prefix `/api-b` → nyasar ke App C :8008 |
| App B menjawab **404** untuk semua request | Slash di ujung `proxy_pass http://localhost:4000/` terhapus |
| Bundle lama terus dipakai setelah deploy | `index.html` di-cache browser — dicegah `no-store` |
| Module worker pdf.js ditolak browser | `.mjs` disajikan sebagai `application/octet-stream` |
| MinIO error "tidak ada kredensial untuk bucket X" | Bucket belum punya `MINIO_ACCESS_KEY_<X>` |
| Alembic gagal total saat start | Password URL-encoded tanpa escape `%` → `%%` |
| Ekstraksi RIPLAY 502 | `riplay_*` tidak dideklarasikan di Settings → `AttributeError` di dalam `try` |
| `git submodule update` gagal di server | Pointer di-push sebelum commit core di-push |

---

## 15. Rujukan Cepat

| Perlu tahu | Buka |
|---|---|
| Peta routing nginx host | `dashboard/deploy/nginx/README.md` |
| Salinan vhost produksi | `dashboard/deploy/nginx/call-qc.bankmega.local.conf` |
| Layout image api | `api/api/Dockerfile` |
| Layout image worker | `worker/worker/Dockerfile` |
| Definisi Settings | `api/api/dependencies.py`, `worker/worker/config.py`, `core/core_config.py` |
| Pemilihan mode MinIO | `core/services/multi_bucket_minio.py` |
| Skema tabel | `core/db/models.py` |
| Migrasi | `api/db/migrations/versions/` |
