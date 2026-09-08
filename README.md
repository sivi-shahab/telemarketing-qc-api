# telemarketing-qc-api

Backend FastAPI sistem QC Telemarketing: REST API, autentikasi JWT/API key,
migrasi Alembic, dan enqueue task ke Celery. Port `4000`.

Repo ini adalah **satu-satunya pemilik skema database** — hanya di sini
`alembic upgrade head` dijalankan.

## Repo terkait

| Repo | Isi |
|---|---|
| `telemarketing-qc-core` | Kode bersama (`qc_core.db`, `qc_core.compliance`, `qc_core.services`, `qc_core.prompt`, `qc_core.sales_lookup`) — dependensi pip, dipin di `api/requirements.txt` |
| `telemarketing-qc-worker` | Celery worker + Flower |
| `telemarketing-qc-dashboard` | Frontend Vue 3 |

## Dokumentasi arsitektur

Dokumen arsitektur sistem berlaku untuk **keempat repo** dan tinggal di repo
`telemarketing-qc-api`:

| Berkas | Isi |
|---|---|
| `telemarketing-qc-api/docs/ARSITEKTUR.md` | Topologi runtime, pembagian compose, alur data, kepemilikan skema DB, integrasi eksternal (App A/App C/object storage S3/LLM), build & deploy, urutan rilis wajib, langkah menjalankan dari nol |
| `telemarketing-qc-api/docs/README.md` | Indeks seluruh paket dokumentasi (deployment, runbook, data model, API reference, role, scoring) |

Baca `ARSITEKTUR.md` lebih dulu sebelum mengubah apa pun yang menyentuh repo lain.

## Setup

```bash
git clone <URL-repo-ini> && cd telemarketing-qc-api
cp .env.example .env                        # lalu isi nilainya
docker network create qc-net                # sekali per host
docker compose up -d --build
```

API di `http://localhost:4000`, dokumentasi OpenAPI di `/docs`.

## Menjalankan tanpa Docker

Core bukan lagi folder di repo ini melainkan paket `qc_core` yang ter-install dari
`api/requirements.txt` (butuh `git` di mesin, karena dipasang dari `git+https`):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r api/requirements.txt pytest
PYTHONPATH=. pytest tests -q
PYTHONPATH=. uvicorn api.main:app --reload --port 4000
```

Versi core yang dipakai terbaca di satu tempat saja, baris `telemarketing-qc-core @
git+...@vX.Y.Z` di `api/requirements.txt`. Baris itu di-bump otomatis oleh
`.github/workflows/bump-core.yml` setiap kali repo core merilis tag baru.

## Batas dengan worker

API **tidak pernah** meng-import kode worker. Task dikirim by name lewat
`api/celery_client.py`:

```python
from api.celery_client import celery_app
celery_app.send_task("worker.tasks.process_transcript.process_transcript", args=[result_id])
```

Yang dibutuhkan hanya broker URL (`REDIS_URL`), bukan kode task-nya.
`.github/workflows/ci.yml` punya job `no-worker-import` yang menggagalkan CI kalau
ada `from worker ...` yang lolos masuk.

Dua script maintenance yang memang butuh runtime worker
(`backfill_generated_at.py`, `backfill_reference_cashline_ids.py`) tinggal di repo
worker, bukan di sini.

## Struktur

```
api/            FastAPI: main, routers, schemas, auth, dependencies, celery_client
db/migrations/  Alembic (env.py + 25 versi) — model-nya di paket qc_core.db
alembic.ini
scripts/        load_reference_csv.py, seed_cashline_users.py
tests/          pytest
```

## Migrasi

Jalan otomatis saat container start (`CMD`: `alembic upgrade head && uvicorn ...`).
Manual:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision -m "deskripsi"
```

Migrasi `0005` menyeed tabel reference dari `csv_bank/` **kalau direktorinya ada**.
Direktori itu berisi data nasabah asli dan sengaja tidak ikut ke repo ini, jadi di
Jenkins / database kosong langkah seed-nya terlewat dengan bersih — pembuatan
tabelnya tetap jalan.

## Deploy

Lihat `Jenkinsfile`. Isi `REGISTRY` dan daftarkan credential `gitlab-registry`
lebih dulu. Urutan rilis yang mengandung perubahan skema: **API dulu** (migrasi),
baru worker.
