# Panduan Deploy — Telemarketing QC System

Panduan lengkap men-deploy sistem dari **GitHub hingga jalan di server**, mencakup **dua jalur**:

- **Jalur A — Docker** (disarankan; paling cepat & konsisten).
- **Jalur B — Tanpa Docker / bare-metal** (instalasi native di server).

Ditutup dengan bagian **Production** (reverse proxy, HTTPS, systemd, firewall) dan **Troubleshooting**.

> Semua perintah, port, dan variabel di dokumen ini diverifikasi langsung dari
> `docker-compose.yml`, `api/Dockerfile`, `worker/Dockerfile`, `dashboard/Dockerfile`,
> `dashboard/nginx.conf`, `dashboard/vite.config.js`, `alembic.ini`, `db/migrations/env.py`,
> `api/dependencies.py`, `worker/config.py`, `worker/celery_app.py`, dan `.env.example`.

---

## 1. Ringkasan Arsitektur

Sistem terdiri dari **7 service**:

| Service | Teknologi | Fungsi |
|---|---|---|
| `postgres` | PostgreSQL 16 | Database utama (users, results, appeals, TMS/reference data) |
| `redis` | Redis 7 | Broker + result backend untuk Celery |
| `minio` | MinIO (S3-compatible) | Object storage: transkrip PDF, hasil JSON, campaign, dokumen, audio |
| `api` | FastAPI + Uvicorn (Python 3.11) | REST API; menjalankan migrasi Alembic saat start |
| `worker` | Celery (Python 3.11) | Proses transkrip & dokumen (LLM/OCR) secara async |
| `flower` | Flower | Dashboard monitoring Celery |
| `dashboard` | Vue 3 + Vite → Nginx (Node 20 build) | Frontend SPA |

Alur deploy:

```
GitHub  ──clone──►  konfigurasi .env  ──►  Postgres + Redis + MinIO
                                             │
                                             ▼
                          api (alembic upgrade head → uvicorn)
                                             │
                             ┌───────────────┼───────────────┐
                             ▼               ▼               ▼
                          worker          flower          dashboard
                         (Celery)      (monitoring)     (Vue → Nginx)
```

Dependensi eksternal: **LLM endpoint** (OpenAI-compatible) via `LLM_BASE_URL`, dan opsional **OCR** (Mistral Document AI) via `OCR_*`.

---

## 2. Tabel Port

| Service | Port host | Port container | Catatan |
|---|---|---|---|
| `api` | **4010** | 4000 | ⚠️ Dari host gunakan **4010**, bukan 4000 (compose memetakan `4010:4000`) |
| `dashboard` | 4006 | 4006 | Nginx SPA |
| `flower` | 4005 | 4005 | Monitoring Celery |
| `minio` (S3 API) | 4003 | 4003 | Endpoint object storage |
| `minio` (console) | 4004 | 4004 | Web console MinIO |
| `postgres` | 5432 | 5432 | **Hanya `127.0.0.1`** (tidak diekspos ke jaringan) |
| `redis` | 6379 | 6379 | **Hanya `127.0.0.1`** |

> **Penting:** di dalam jaringan Docker, `api` tetap mendengar di **4000** dan service lain
> memanggilnya lewat nama `api:4000`. Yang dipetakan ke host adalah **4010**. Jadi
> `http://localhost:4000` hanya bekerja dari dalam container atau via reverse proxy; dari
> host pakai `http://localhost:4010`.

---

## 3. Prasyarat

**Jalur A (Docker):**
- Docker Engine ≥ 24 dan Docker Compose v2.
- Akses jaringan ke LLM endpoint (`LLM_BASE_URL`).

**Jalur B (bare-metal):**
- Python **3.11**
- Node.js **20** (untuk build dashboard)
- PostgreSQL **16**
- Redis **7**
- MinIO server (binary resmi MinIO)
- Reverse proxy (Nginx/Caddy) bila memakai base path/HTTPS.

---

## 4. Ambil Kode dari GitHub

```bash
git clone <url-repo> telemarketing-qc-system
cd telemarketing-qc-system
cp .env.example .env
# lalu edit .env (lihat bagian 5)
```

---

## 5. Konfigurasi `.env`

Semua service (kecuali dashboard) membaca `.env` di root repo. **Wajib mengganti** semua
nilai yang mengandung `changeme*` sebelum production.

### PostgreSQL
| Var | Default (`.env.example`) | Keterangan |
|---|---|---|
| `POSTGRES_HOST` | `postgres` | Nama service Docker. **Bare-metal → `localhost`** |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_DB` | `bankqc` | Nama database |
| `POSTGRES_USER` | `bankqc` | User database |
| `POSTGRES_PASSWORD` | `changeme` | **Ganti** |

### Redis
| Var | Default | Keterangan |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Broker Celery. **Bare-metal → `redis://localhost:6379/0`** |

### MinIO
| Var | Default | Keterangan |
|---|---|---|
| `MINIO_ENDPOINT` | `minio:4003` | **Bare-metal → `localhost:4003`** |
| `MINIO_ACCESS_KEY` | `minioadmin` | Dipetakan ke `MINIO_ROOT_USER` |
| `MINIO_SECRET_KEY` | `changeme123` | Dipetakan ke `MINIO_ROOT_PASSWORD`. **Ganti** |
| `MINIO_BUCKET_TRANSCRIPTS` | `transcripts` | |
| `MINIO_BUCKET_RESULTS` | `results` | |
| `MINIO_BUCKET_CAMPAIGNS` | `campaigns` | |
| `MINIO_BUCKET_DOCUMENTS` | `documents` | |
| `MINIO_BUCKET_AUDIO` | `audio` | |
| `MINIO_BUCKET_SALES_DATABASE` | `sales-database` | |
| `MINIO_BUCKET_QC_DATABASE` | `qc-database` | |
| `MINIO_TRANSCRIPTS_SOURCE_PREFIX` | `""` (saran: `inbox/`) | Prefix ingestion webhook. **Kosong = scan seluruh bucket** |
| `MINIO_DOCUMENTS_SOURCE_PREFIX` | `""` (saran: `inbox/`) | Idem |

> Semua bucket dibuat otomatis saat api start (`ensure_buckets()`), jadi tidak wajib diset
> manual — default-nya ada di `api/dependencies.py`.
>
> ⚠️ Default kedua `*_SOURCE_PREFIX` di kode adalah **string kosong**, bukan `inbox/`. Bila
> variabelnya tidak ditulis di `.env`, webhook men-scan **seluruh** bucket.

### LLM (wajib diisi)
| Var | Default | Keterangan |
|---|---|---|
| `LLM_BASE_URL` | *(kosong)* | Endpoint OpenAI-compatible, mis. `https://api.openai.com/v1` |
| `LLM_API_KEY` | *(kosong)* | API key |
| `LLM_MODEL` | *(kosong)* | Nama model, mis. `gpt-5-mini` |
| `LLM_TEMPERATURE` / `LLM_SEED` / `LLM_REASONING_EFFORT` / `LLM_TIMEOUT` | `1.0` / `42` / `medium` / `1800` | Parameter worker |

### OCR (opsional — Mistral Document AI)
| Var | Keterangan |
|---|---|
| `OCR_BASE_URL` / `OCR_MODEL` / `OCR_API_KEY` | Kosongkan bila tidak dipakai (string kosong → diabaikan) |
| `OCR_TEMPERATURE` / `OCR_SEED` / `OCR_REASONING_EFFORT` | Opsional; kosong = parameter tidak dikirim, default provider berlaku |

### RIPLAY (ekstraksi fact sheet produk saat upload campaign)
| Var | Default | Keterangan |
|---|---|---|
| `RIPLAY_MODEL` | *(kosong)* | Model vision; kosong = ikut `LLM_MODEL` |
| `RIPLAY_MAX_PAGES` | `20` | Batas halaman PDF yang dirender |
| `RIPLAY_RENDER_SCALE` | `2.0` | Skala render halaman → gambar |
| `RIPLAY_MIN_SIMILARITY` | `50.0` | Ambang kemiripan nama produk RIPLAY vs nama campaign |

### Celery / Auth / Admin / Dashboard
| Var | Default | Keterangan |
|---|---|---|
| `CELERY_CONCURRENCY` | `8` | Jumlah worker paralel (**production saat ini 24**) |
| `API_KEY` | `changeme-...` | Header `X-API-Key` (legacy). **Ganti** |
| `JWT_SECRET_KEY` | `changeme-jwt-secret-key` | **Wajib ganti** (rahasia token) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `60` / `7` | |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | `admin` / `changeme-...` / `admin@bank.local` | Admin pertama, di-seed migrasi `0001` saat tabel `users` kosong |
| `VITE_API_URL` | `http://localhost:4000` | URL API dari sisi **browser**, di-*bake* saat build dashboard (lihat catatan ⚠️ di bawah) |

> ⚠️ **`VITE_API_URL` di-*bake* saat build**, bukan runtime. Mengubah nilainya berarti
> **rebuild dashboard** (bukan sekadar restart). Nilai umum:
> - `http://localhost:4000` — akses lokal langsung.
> - `http://<ip-server>:4010` — akses jaringan langsung (sesuaikan port host api = 4010).
> - `/telemarketing_qc_system/api` — **relatif**, mengandalkan reverse proxy di depan (lihat bagian 9).

---

## 6. Jalur A — Deploy dengan Docker

### 6.1 Jalankan seluruh stack

```bash
docker compose up -d --build
```

Yang terjadi otomatis:
- Container `api` menjalankan `alembic upgrade head` **lalu** `uvicorn` (migrasi jalan tiap kali api start).
- MinIO bucket dibuat otomatis via `ensure_buckets()` saat api boot.
- Migrasi `0001` men-seed admin pertama (`ADMIN_USERNAME/PASSWORD`) **hanya bila** tabel `users` kosong.

### 6.2 Verifikasi

```bash
docker compose ps                          # semua service "running"/"healthy"
curl http://localhost:4010/health          # {"status":"ok"} — perhatikan port 4010
```

| Yang dibuka | URL lokal |
|---|---|
| Dashboard | http://localhost:4006 |
| Swagger API | http://localhost:4010/docs |
| MinIO console | http://localhost:4004 |
| Flower | http://localhost:4005 |

### 6.3 Deploy ke server / jaringan

1. Set `VITE_API_URL` sesuai cara browser mengakses API — mis. `http://<ip-server>:4010`
   (akses langsung) atau `/telemarketing_qc_system/api` (di belakang reverse proxy).
2. **Rebuild dashboard** (karena URL di-bake):
   ```bash
   docker compose up -d --build dashboard
   ```
3. Buka port firewall yang perlu diakses browser (mis. `4010` dan `4006`), atau cukup
   `80/443` bila memakai reverse proxy (bagian 9).

### 6.4 Update setelah perubahan kode

Backend di-*bind-mount* (`.:/app`), frontend **tidak** (di-bake ke image):

```bash
# Perubahan Python (api/worker) — cukup restart:
docker compose restart api worker

# Perubahan frontend — WAJIB rebuild dashboard:
docker compose up -d --build dashboard
# lalu hard refresh di browser (Ctrl+Shift+R)
```

### 6.5 Scaling worker

```bash
# via concurrency (di .env): CELERY_CONCURRENCY=16
# atau tambah instance worker:
docker compose up -d --scale worker=3
```

---

## 7. Jalur B — Deploy Tanpa Docker (bare-metal)

Menjalankan tiap komponen langsung di server. Contoh di bawah memakai konvensi Ubuntu/Debian.

### 7.1 Install service dasar

```bash
# PostgreSQL 16 & Redis 7 (via paket distro atau repo resmi)
sudo apt install -y postgresql-16 redis-server

# Buat database + user sesuai .env
sudo -u postgres psql -c "CREATE USER bankqc WITH PASSWORD '<password>';"
sudo -u postgres psql -c "CREATE DATABASE bankqc OWNER bankqc;"

# MinIO (binary resmi) — jalankan sebagai service (lihat contoh systemd di bagian 9)
# Contoh manual:
export MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD='<secret>'
minio server /var/lib/minio --address ":4003" --console-address ":4004"
```

### 7.2 Siapkan Python environment

Satu virtualenv menampung kebutuhan api **dan** worker:

```bash
cd telemarketing-qc-system
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt -r worker/requirements.txt
```

### 7.3 Konfigurasi environment shell

Karena proses dijalankan native, sesuaikan `.env` (hostname Docker → `localhost`):

```
POSTGRES_HOST=localhost
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:4003
LLM_BASE_URL=https://api.openai.com/v1   # atau endpoint LLM Anda
```

> ⚠️ **Celery dan Alembic TIDAK membaca `.env`** (hanya Uvicorn/pydantic-settings yang
> membacanya). Jadi export dulu ke shell sebelum menjalankan proses apa pun:
> ```bash
> set -a; . ./.env; set +a
> export PYTHONPATH=$(pwd)     # root repo harus importable (Docker menyetel PYTHONPATH=/app)
> ```
> Selalu jalankan semua perintah **dari root repo**.

### 7.4 Migrasi database

```bash
alembic upgrade head
```
(Config: `alembic.ini` → `script_location = db/migrations`; `db/migrations/env.py` menyusun
URL dari `POSTGRES_*` di environment.)

### 7.5 Jalankan proses

Urutan boot yang benar: **Postgres/Redis/MinIO → migrasi → api → worker → flower**
(MinIO harus hidup **sebelum** api karena `ensure_buckets()` dipanggil saat startup).

```bash
# API (terminal 1)
uvicorn api.main:app --host 0.0.0.0 --port 4000

# Worker (terminal 2)
celery -A worker.celery_app worker --loglevel=info --concurrency=8

# Flower — opsional (terminal 3)
celery -A worker.celery_app flower --port=4005
```

> Untuk production, jangan jalankan manual di terminal — pakai **systemd** (bagian 9.3).

### 7.6 Build & sajikan dashboard tanpa Docker

```bash
cd dashboard
npm ci
VITE_API_URL=<url-api-dari-browser> npm run build   # output ke dashboard/dist/
```

Sajikan `dist/` dengan web server statis. **Syarat wajib**:
- **SPA fallback** ke `index.html` (client-side routing).
- File `.mjs` disajikan sebagai `text/javascript` (dibutuhkan worker pdf.js).
- Situs harus di-mount di base path **`/telemarketing_qc_system/`** (karena semua URL aset
  absolut dengan prefix itu). Alternatif: ubah `base` di `dashboard/vite.config.js` lalu build ulang.

Contoh `nginx.conf` statis (adaptasi dari `dashboard/nginx.conf`):

```nginx
server {
    listen 4006;
    root /var/www/telemarketing-qc/dist;

    location ~ \.mjs$ {
        default_type text/javascript;
        try_files $uri =404;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
}
```

---

## 8. Seed Data Awal (kedua jalur)

- **Admin pertama** — otomatis dibuat oleh migrasi `0001` saat tabel `users` masih kosong,
  memakai `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`ADMIN_EMAIL`.
- **Campaign — TIDAK auto-seed.** Wajib upload manual **sebelum** upload transkrip:
  lewat dashboard menu **Upload Data → Upload Campaign** (permission `admin.campaign.write` —
  **hanya akun `admin`** sejak 14 Agustus 2026; login sebagai SPQ Head tidak akan menemukan
  menunya),
  isi nama campaign + unggah 3 file `.txt` (`prompt`, `knowledge_base`, `scorecard`) plus
  RIPLAY PDF opsional. Versi aktif per 12 Agustus 2026 ada di `docs/` dan
  `campaign_cashline/`: `prompt_cashline_mus_v54.txt`, `cashline_kb_v21.txt`,
  `cashline_scorecard_v3.txt`.
- **Script utilitas** di `scripts/` (jalankan di dalam container `api`/`worker` untuk Docker,
  atau di dalam venv untuk bare-metal — semuanya butuh `.env` ter-export & `PYTHONPATH` root):
  - `scripts/load_reference_csv.py` — memuat data reference/TMS dari CSV.
  - `scripts/seed_cashline_users.py` — seed user campaign Cashline.
  - `scripts/backfill_generated_at.py` — backfill `generated_at` (butuh MinIO + pdfplumber).

  Contoh (Docker): `docker compose exec api python scripts/load_reference_csv.py`
  Contoh (bare-metal): `python scripts/load_reference_csv.py`

---

## 9. Production Hardening

### 9.1 Reverse proxy (Nginx) di depan

Nginx bawaan container dashboard **hanya menyajikan file statis** — ia **tidak** mem-proxy
ke API. Konfigurasi production live memakai `VITE_API_URL=/telemarketing_qc_system/api`
(relatif), sehingga **wajib** ada reverse proxy luar yang me-route base path SPA dan sub-path
`/api` ke service masing-masing (pola live: `https://dashboard.tombin.id/telemarketing_qc_system/`).

Contoh server block:

```nginx
server {
    listen 443 ssl;
    server_name dashboard.example.id;

    ssl_certificate     /etc/letsencrypt/live/dashboard.example.id/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dashboard.example.id/privkey.pem;

    # API → service api (host 4010 untuk Docker; 4000 bila bare-metal)
    location /telemarketing_qc_system/api/ {
        proxy_pass http://127.0.0.1:4010/;   # bare-metal: http://127.0.0.1:4000/
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Dashboard SPA → service dashboard (Nginx :4006)
    location /telemarketing_qc_system/ {
        proxy_pass http://127.0.0.1:4006/;
        proxy_set_header Host $host;
    }
}
```

> Trailing slash pada `proxy_pass` menentukan apakah prefix di-strip. Sesuaikan dengan
> route API Anda (endpoint di FastAPI tidak berprefix `/telemarketing_qc_system/api`, jadi
> prefix harus di-strip seperti contoh di atas).

Bila memakai proxy ini, build dashboard dengan `VITE_API_URL=/telemarketing_qc_system/api`.

### 9.2 HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dashboard.example.id
# certbot memasang sertifikat & auto-renew (systemd timer)
```

### 9.3 systemd units (bare-metal)

Buat unit agar api/worker/flower otomatis start & restart. Sesuaikan path venv & repo.

`/etc/systemd/system/qc-api.service`:
```ini
[Unit]
Description=Telemarketing QC - API
After=network.target postgresql.service redis-server.service

[Service]
User=qc
WorkingDirectory=/opt/telemarketing-qc-system
EnvironmentFile=/opt/telemarketing-qc-system/.env
Environment=PYTHONPATH=/opt/telemarketing-qc-system
ExecStartPre=/opt/telemarketing-qc-system/.venv/bin/alembic upgrade head
ExecStart=/opt/telemarketing-qc-system/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 4000
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/qc-worker.service`:
```ini
[Unit]
Description=Telemarketing QC - Celery Worker
After=network.target redis-server.service

[Service]
User=qc
WorkingDirectory=/opt/telemarketing-qc-system
EnvironmentFile=/opt/telemarketing-qc-system/.env
Environment=PYTHONPATH=/opt/telemarketing-qc-system
ExecStart=/opt/telemarketing-qc-system/.venv/bin/celery -A worker.celery_app worker --loglevel=info --concurrency=8
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/qc-flower.service` (opsional): sama seperti worker, ganti `ExecStart`
menjadi `... celery -A worker.celery_app flower --port=4005`.

> Catatan: `EnvironmentFile` hanya memuat baris `KEY=VALUE` sederhana — cukup untuk `.env`
> ini (tanpa quoting kompleks). Migrasi dijalankan lewat `ExecStartPre` pada `qc-api`.

Aktifkan:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qc-api qc-worker qc-flower
```

### 9.4 Firewall (ufw)

```bash
# Mode reverse proxy (disarankan): hanya web + SSH
sudo ufw allow 80,443/tcp
sudo ufw allow 22/tcp

# Mode akses langsung (tanpa proxy): buka port yang diakses browser
# sudo ufw allow 4010/tcp   # api
# sudo ufw allow 4006/tcp   # dashboard
```

**Jangan** mengekspos PostgreSQL (5432), Redis (6379), atau MinIO (4003/4004) ke internet.
Di Docker, Postgres/Redis sudah di-bind ke `127.0.0.1`.

### 9.5 Secrets wajib untuk production

Ganti semua nilai `changeme*`, minimal: `JWT_SECRET_KEY`, `API_KEY`, `POSTGRES_PASSWORD`,
`MINIO_SECRET_KEY`, `ADMIN_PASSWORD`. Gunakan string acak yang kuat.

---

## 10. Operasional & Troubleshooting

### Perintah operasional (Docker)

```bash
docker compose logs -f api          # log api
docker compose logs -f worker       # log worker (proses transkrip)
docker compose restart api worker   # restart backend
docker compose down                 # stop (data di ./data tetap ada)
docker compose down -v              # stop + HAPUS volume/data ⚠️
docker compose exec api alembic upgrade head   # migrasi manual
```

### Backup

Data persisten ada di bind-mount `./data/{postgres,minio,redis}`. Backup dengan
menghentikan stack lalu menyalin folder tersebut, atau `pg_dump` untuk Postgres dan
`mc mirror` untuk MinIO.

### Tabel Troubleshooting

| Gejala | Penyebab & Solusi |
|---|---|
| Dashboard menampilkan versi lama | Aset di-bake ke image → **rebuild** `docker compose up -d --build dashboard` lalu **hard refresh** (Ctrl+Shift+R) |
| Frontend gagal call API / CORS error | `VITE_API_URL` salah saat build → set nilai benar lalu rebuild dashboard |
| `http://localhost:4000` tidak bisa diakses dari host | Port host api = **4010** (`4010:4000`). Pakai `http://localhost:4010` |
| Admin lama masih ada setelah ganti `ADMIN_*` | Seed hanya jalan saat tabel `users` kosong. Reset = wipe DB (`docker compose down -v` atau hapus `./data/postgres`) |
| Celery/Alembic tidak lihat konfigurasi (bare-metal) | Belum `set -a; . ./.env; set +a`. Export dulu, jalankan dari root repo, set `PYTHONPATH` |
| api gagal start: bucket/MinIO error | MinIO belum hidup saat api boot. Start MinIO dulu (`ensure_buckets()` butuh MinIO) |
| ImportError modul `api`/`worker`/`db` | Tidak dijalankan dari root repo atau `PYTHONPATH` belum di-set ke root |
| Transkrip tidak diproses | Worker tidak jalan / Redis tak terhubung. Cek `docker compose logs -f worker` & `REDIS_URL` |

---

## Ringkasan cepat

**Docker (paling cepat):**
```bash
git clone <url-repo> && cd telemarketing-qc-system
cp .env.example .env   # edit secrets + LLM_* + VITE_API_URL
docker compose up -d --build
curl http://localhost:4010/health
```

**Bare-metal (inti):**
```bash
# Postgres/Redis/MinIO sudah jalan; .env sudah diset (host → localhost)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt -r worker/requirements.txt
set -a; . ./.env; set +a; export PYTHONPATH=$(pwd)
alembic upgrade head
uvicorn api.main:app --host 0.0.0.0 --port 4000 &
celery -A worker.celery_app worker --loglevel=info --concurrency=8 &
(cd dashboard && npm ci && VITE_API_URL=<url> npm run build)   # sajikan dist/ via nginx
```
