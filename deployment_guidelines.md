# Deployment — telemarketing-qc-api

Panduan menyalakan service **API**. Dua repo lain punya berkasnya sendiri:
`telemarketing-qc-worker/deployment_guidelines.md` dan
`telemarketing-qc-dashboard/deployment_guidelines.md`.

> **API dinyalakan PERTAMA.** Ia satu-satunya pemilik migrasi Alembic — worker
> dan dashboard tidak menjalankannya. Menyalakan worker lebih dulu di DB yang
> skemanya belum termigrasi akan gagal dengan error kolom/tabel tidak ada.

---

## 1. Prasyarat

### Network `qc-net`

Ketiga repo berbagi satu network eksternal. Buat **sekali** di host:

```bash
docker network create qc-net
```

Tanpa ini `docker compose up` langsung gagal: ketiga compose file mendeklarasikan
`external: true`, jadi Compose tidak akan membuatkannya.

### Submodule `core`

Kode bersama (`db/`, `compliance/`, `services/`, `prompt/`, `sales_lookup.py`)
ada di submodule `core/`, bukan di repo ini.

```bash
git submodule update --init --recursive
git submodule status          # pastikan tidak ada awalan '-' atau '+'
```

Awalan `-` berarti belum ter-checkout, `+` berarti commit-nya beda dari yang
dicatat repo induk. **Build akan sukses tapi container mati saat start** dengan
`ModuleNotFoundError: No module named 'services.s3_buckets'` — kesalahan yang
menyesatkan karena build-nya sendiri tidak mengeluh.

Setelah menarik perubahan core:

```bash
git -C core fetch origin <branch> && git -C core merge --ff-only FETCH_HEAD
git add core && git commit -m "bump core"
```

### Berkas `.env`

Tidak ikut Git. Kunci yang wajib ada:

| Kelompok | Kunci |
|---|---|
| Postgres | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SCHEMA` |
| Redis/Celery | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| S3/CDN | `MINIO_ENDPOINT`, `MINIO_SECURE`, `MINIO_BUCKET_*`, `MINIO_ACCESS_KEY_*`, `MINIO_SECRET_KEY_*` |
| DWH & TMS | `DWH_API_BASE_URL`, `TMS_API_*`, `VIEW_STREAM_*` |
| LLM | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Auth | `API_KEY`, `JWT_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` |
| Audio | `AUDIO_RECORDING_DIR` (opsional, default `/data/recording`) |

Dua hal yang gampang salah:

- **`POSTGRES_PASSWORD` URL-encoded.** Password mengandung `%` karena disusun
  sebagai bagian URL koneksi (mis. `%40` untuk `@`). Jangan "memperbaiki"nya
  jadi karakter asli — `database_url` merangkainya sebagai URL dan
  `db/migrations/env.py` meng-escape `%` jadi `%%` untuk ConfigParser.
- **Nama bucket bukan nama generik.** Bucket di CDN bernama `voice-to-text-dm`,
  `vtt-results`, `vtt-campaigns`, `vtt-documents`, `vtt-audio`, `vtt-sales-db` —
  bukan `transcripts`/`results`/dst. Salah nama memberi `AccessDenied`,
  bukan `NoSuchBucket`, jadi mudah dikira masalah kredensial.

### Sertifikat CDN

`certs/bankmegalocal.crt` ikut di repo dan dipasang Dockerfile ke trust store
image. Server `cdn.bankmega.local` hanya mengirim sertifikat leaf-nya tanpa CA
penerbit, jadi leaf itu sendiri yang dipercaya — sama seperti trust store host.
Verifikasi TLS **tetap menyala**; yang memungkinkannya adalah
`VERIFY_X509_PARTIAL_CHAIN` di `core/services/s3_buckets.py`.

Jangan mengganti pendekatan ini dengan `verify=False`.

### Folder antrian STT

`/data/recording` di host di-bind mount ke container. Folder itu diawasi
`/data/script_antrian/producer_watch.py` (di luar repo ini). Kalau host belum
punya foldernya:

```bash
sudo mkdir -p /data/recording
```

---

## 2. Menyalakan

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker compose up -d --build api
```

Yang terjadi saat start: `alembic upgrade head`, lalu `uvicorn` di port 4000.

Service yang ikut naik: `api` (4000) dan `redis` (6378). `postgres` dan `minio`
ada di compose tapi **ber-profile `local-infra`** — sengaja tidak ikut, karena
produksi memakai DWH dan CDN. Untuk uji coba lokal:

```bash
docker compose --profile local-infra up -d
```

### Periksa migrasi tertunda SEBELUM start (produksi)

DB DWH dipakai bersama tim lain. Sebelum menyalakan ke sana, cek dulu jaraknya:

```bash
docker compose run --rm --entrypoint sh api -c \
  'python -c "
from sqlalchemy import text
from api.dependencies import get_settings,_make_engine
with _make_engine(get_settings()).connect() as c:
    print(c.execute(text(\"select version_num from <schema>.alembic_version\")).scalar())
"'
docker compose run --rm --entrypoint sh api -c 'alembic heads'
```

Kalau jaraknya jauh, baca dulu revisi di antaranya — `alembic upgrade head` jalan
otomatis dan tidak menanyakan konfirmasi.

---

## 3. Verifikasi

```bash
curl -f http://localhost:4000/health          # {"status":"ok"}
docker compose logs -f api                    # migrasi + startup
```

Startup yang sehat **tidak** mencetak baris `[minio] Lewati ensure bucket`.
Kalau muncul, artinya bucket tidak terjangkau — cek nama bucket dan kredensial.

Uji menyeluruh:

```bash
# login
TOK=$(curl -s -X POST http://localhost:4000/auth/login \
  --data-urlencode "username=<user>" --data-urlencode "password=<pass>" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOK" http://localhost:4000/auth/me
curl -s -H "Authorization: Bearer $TOK" http://localhost:4000/list_results
```

Cek koneksi S3 keenam bucket:

```bash
docker compose exec -T api python -c "
from api.dependencies import get_minio, get_settings
from services.s3_buckets import _BUCKET_CREDENTIAL_FIELDS
s, c = get_settings(), get_minio()
for bf, akf, _ in _BUCKET_CREDENTIAL_FIELDS:
    b = getattr(s, bf, '')
    if b: print(f'{b:20s} exists={c.bucket_exists(b)}')
"
```

---

## 4. Menjalankan test

`pytest` sengaja tidak ada di image produksi. Jalankan di container sekali-pakai
supaya API yang sedang berjalan tidak terganggu:

```bash
docker run --rm -v "$PWD/tests:/app/tests:ro" --env-file .env \
  --entrypoint sh local/qc-api:latest -c \
  'pip install -q pytest && python -m pytest tests/ -q'
```

Beberapa test memang gagal di luar container lengkap (fixture PDF tidak
ter-mount, test yang butuh DB). Bandingkan dengan hasil sebelum perubahan Anda,
jangan berasumsi suite-nya hijau bersih.

---

## 5. Urutan penuh tiga repo

```bash
docker network create qc-net                     # sekali saja

cd telemarketing-qc-api       && docker compose up -d --build api
cd ../telemarketing-qc-worker && docker compose up -d --build
cd ../telemarketing-qc-dashboard && docker compose up -d --build
```

Alasan urutannya: API menjalankan migrasi dan menyediakan `redis` yang dipakai
worker sebagai broker.

---

## 6. Nginx depan (di host, di luar repo)

Pintu masuk sebenarnya adalah `https://call-qc.bankmega.local`, bukan port
container. Peta di `/etc/nginx/sites-available/default`:

| Path | Tujuan |
|---|---|
| `/` | dashboard `:4006` |
| `/api-b/` | API repo ini `:4000` (prefix di-strip) |
| `/api-a/` | App A / STT `:8000` |
| `/api/download`, `/api/view-streams/` | `:8010` |

Mengakses `http://localhost:4006` langsung **tidak bisa dipakai login** — bundle
memanggil `/api-b/...` yang hanya dipetakan nginx depan, sehingga dibalas
`405 Not Allowed` oleh nginx dashboard sendiri.

---

## 7. Masalah yang pernah terjadi

| Gejala | Sebab & penanganan |
|---|---|
| `ModuleNotFoundError: services.s3_buckets` | Submodule `core` tertinggal. `git -C core fetch && merge --ff-only`, lalu rebuild. |
| `[minio] Lewati ensure bucket ...: AccessDenied` | Nama bucket di `.env` salah. Lihat daftar nama asli di bagian Prasyarat. |
| `non-XML response from server; 403 Forbiden!` | Region tidak di-set sehingga SDK memanggil `GET /<bucket>?location=`, yang ditolak nginx CDN. Sudah ditangani `_region()`; kalau muncul lagi, cek `MINIO_REGION`. |
| `CERTIFICATE_VERIFY_FAILED` | Sertifikat CDN tidak terpasang atau `SSL_CERT_FILE` tidak menunjuk bundle hasil `update-ca-certificates`. |
| `password authentication failed` | Password URL-encoded dipakai mentah. Harus lewat `settings.database_url`, bukan diteruskan langsung ke psycopg2. |
| `failed to prepare extraction snapshot` saat build | Galat buildkit yang sesekali muncul. Ulangi `docker compose build api`. |
| Compose gagal: network `qc-net` not found | Belum dibuat. `docker network create qc-net`. |
