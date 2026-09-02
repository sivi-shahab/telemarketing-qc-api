# Runbook Operasional — Telemarketing QC System

Panduan operasional harian (day-2 ops): monitoring, restart, scaling, backup/restore,
memproses ulang tiket, dan penanganan insiden. Ditujukan untuk tim yang menjaga sistem
setelah deploy. Untuk instalasi awal lihat [`DEPLOYMENT.md`](./DEPLOYMENT.md).

> Sebagian besar contoh memakai **Docker**. Untuk bare-metal, ganti `docker compose ...`
> dengan operasi service/systemd yang setara (lihat DEPLOYMENT.md §9.3).

---

## 1. Peta Cepat

| Komponen | Akses | Cek sehat |
|---|---|---|
| API | `http://<host>:4010` | `curl http://<host>:4010/health` → `{"status":"ok"}` |
| Dashboard | `http://<host>:4006` | buka di browser |
| Swagger API | `http://<host>:4010/docs` | daftar endpoint |
| Flower (monitor Celery) | `http://<host>:4005` | task worker aktif/gagal |
| MinIO console | `http://<host>:4004` | isi bucket |
| PostgreSQL | `127.0.0.1:5432` | `pg_isready` |
| Redis | `127.0.0.1:6379` | `redis-cli ping` → `PONG` |

Data persisten (bind-mount): `./data/postgres`, `./data/minio`, `./data/redis`.

---

## 2. Monitoring & Log

```bash
docker compose ps                     # status semua service (running/healthy)
docker compose logs -f api            # log API (request, error)
docker compose logs -f worker         # log worker (proses transkrip/LLM) — paling sering dicek
docker compose logs -f --tail=200 api worker   # gabungan, 200 baris terakhir
```

- **Flower** (`:4005`) menampilkan antrian Celery: task sukses/gagal, worker aktif,
  durasi. Cek di sini kalau transkrip "tidak jalan".
- **Healthcheck** built-in: `api` (`/health`), `postgres` (`pg_isready`), `redis`
  (`redis-cli ping`), `minio` (`/minio/health/live`). Lihat kolom `STATUS` di
  `docker compose ps` (mis. `healthy`).

---

## 3. Restart / Stop / Start

```bash
# Restart backend setelah perubahan kode Python (di-bind-mount .:/app)
docker compose restart api worker

# Restart satu service
docker compose restart worker

# Stop semua (data di ./data TETAP ada)
docker compose down

# Start lagi
docker compose up -d

# ⚠️ Stop + HAPUS data (WIPE DB/MinIO/Redis) — hanya untuk reset total
docker compose down -v
```

> **Perubahan frontend** tidak cukup restart — dashboard di-*bake* ke image, wajib
> `docker compose up -d --build dashboard` lalu hard refresh (Ctrl+Shift+R).

---

## 4. Scaling Worker

Throughput proses transkrip diatur worker Celery. Dua cara:

```bash
# A. Naikkan concurrency per container (.env): CELERY_CONCURRENCY=16
docker compose up -d worker

# B. Tambah jumlah container worker
docker compose up -d --scale worker=3
```

> Bottleneck sebenarnya biasanya **rate limit LLM**, bukan CPU. Naikkan concurrency
> bertahap sambil memantau error rate di log worker & Flower.

---

## 5. Migrasi Database

Migrasi Alembic **jalan otomatis** saat container `api` start (`alembic upgrade head`
di CMD). Untuk menjalankan manual:

```bash
docker compose exec api alembic upgrade head    # terapkan migrasi terbaru
docker compose exec api alembic current         # revisi aktif
docker compose exec api alembic history          # riwayat migrasi
```

Detail skema & cara menambah migrasi baru: lihat [`DATA_MODEL.md`](./DATA_MODEL.md).

---

## 6. Backup & Restore

### 6.1 PostgreSQL

```bash
# Backup (dump SQL)
set -a; . ./.env; set +a
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%F).sql

# Restore (ke DB kosong)
cat backup_YYYY-MM-DD.sql | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

### 6.2 MinIO (object storage: transkrip PDF, hasil JSON, campaign, dokumen)

Cara paling sederhana — salin direktori backing store saat stack berhenti:

```bash
docker compose stop minio
tar czf minio_backup_$(date +%F).tar.gz ./data/minio
docker compose start minio
```

Alternatif (tanpa downtime) dengan MinIO client `mc`:

```bash
mc alias set qc http://<host>:4003 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc mirror qc/transcripts ./backup/transcripts
mc mirror qc/results     ./backup/results
mc mirror qc/campaigns   ./backup/campaigns
mc mirror qc/documents   ./backup/documents
```

### 6.3 Yang WAJIB di-backup

- **PostgreSQL** — semua state aplikasi (users, results metadata, appeals, campaign text, TMS/reference).
- **MinIO** — file transkrip, hasil JSON, campaign, dokumen (tidak ada di DB).
- **`.env`** — konfigurasi & secret (simpan di kanal aman, bukan di git).

> Redis (`./data/redis`) tidak perlu di-backup — hanya broker/cache antrian.

---

## 7. Memproses Ulang Tiket (reprocess)

Ada **tiga** cara, semuanya butuh akun `admin`. Karena prompt/scorecard/KB diambil
**fresh dari DB** tiap task, ketiganya otomatis memakai konfigurasi campaign terbaru —
inilah cara menerapkan revisi prompt ke tiket yang sudah ada.

| Cara | Untuk | Permission |
|---|---|---|
| Tombol **Reprocess** (kolom Action, menu Results) | satu ticket id | `admin.ticket.reprocess` |
| Menu **Upload Data → Reprocess All Ticket** | semua tiket satu/beberapa campaign | `admin.ticket.reprocess` |
| Hapus + upload ulang transkrip | kasus khusus (mis. berkas PDF-nya sendiri salah) | `admin.ticket.delete` + `transcript.upload` |

Dua cara pertama memakai mesin yang sama dan **aman terhadap kegagalan**: entry lama
sebuah ticket id hanya dihapus SETELAH entry barunya berstatus `done`; kalau gagal,
entry baru dibuang dan entry lama dipertahankan apa adanya. Yang dihapus persis id yang
dibekukan saat tombol ditekan, jadi upload yang masuk di tengah job tidak ikut terhapus.

Yang **hilang** pada entry lama setelah reproses berhasil: banding Error Code,
usulan/approval Manual Status, dan dokumen pendukung. Berkas transkrip & JSON hasil di
MinIO tidak dihapus.

```bash
# satu tiket
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "http://<host>:4000/reprocess_ticket?ticket_id=221111rBUk" | jq

# pantau (job_id dari respons di atas, atau dari POST /reprocess_tickets)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://<host>:4000/reprocess_job/<job_id>" | jq '.status, .counts'
```

**Ongkosnya nyata**: satu panggilan LLM per unique ticket id. Rerun 98 tiket cashline
pada 21 Agustus 2026 memakan ~30 menit dengan `CELERY_CONCURRENCY=16` (~5 menit per
tiket, 16 slot paralel). Naikkan concurrency lewat `.env` lalu **`docker compose up -d
worker`** — `docker restart` TIDAK cukup, karena nilainya masuk ke *command* container
saat compose merender `--concurrency=${CELERY_CONCURRENCY:-8}`.

> Perubahan yang murni soal **pembacaan** (ambang band, pemilihan penyebutan verifikasi
> statik, teks reason) tidak menuntut reproses: semuanya dihitung ulang tiap kali
> halaman dibuka. Yang menuntut reproses adalah perubahan yang mengubah **keluaran
> LLM** — revisi prompt/KB/scorecard.

---

## 8. Operasi Campaign

Campaign (prompt/knowledge_base/scorecard, + RIPLAY opsional) **wajib** ada sebelum upload
transkrip. Update campaign = upload ulang via dashboard **Upload Data → Upload Campaign**
(butuh `admin.campaign.write` — **hanya akun `admin`** sejak 14 Agustus 2026). Tidak perlu
restart service — prompt dibaca fresh
dari DB tiap task. Detail: [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md).

Cek kesiapan seluruh campaign (konfigurasi QC, roster, akun, data TMS, tiket):

```bash
curl -s -H "X-API-Key: $API_KEY" http://<host>:4010/campaign_readiness | jq
```

---

## 9. Sakelar Aturan Tenggat H+2 (SLA dokumen)

Tiket yang kekurangan dokumen wajib berstatus **PENDING** selama masih dalam 48 jam sejak
`tms_cashline.submit_time`, dan **FAIL** setelahnya.

**Sejak 24 Agustus 2026 sakelarnya ada di LAYAR, bukan di kode.** Menu **Results** memuat
indikator kebijakan untuk semua peran, dan tombol on/off untuk role `admin`. Tidak perlu
edit file, tidak perlu restart, tidak perlu refresh manual:

| | |
|---|---|
| **Lokasi** | menu **Results**, bilah di bawah baris filter |
| **Tombol** | hanya muncul untuk role `admin` (capability `admin.doc_sla.write`) |
| **Indikator** | biru = H+2 AKTIF · oranye = NONAKTIF; tampil untuk **semua** peran |
| **Penyimpanan** | `app_settings.doc_sla_enabled` (`"true"`/`"false"`) |
| **Endpoint** | `GET /doc_sla_policy` (cukup login) · `PUT /doc_sla_policy` (admin) |

Lewat API bila perlu:

```bash
TOKEN=$(curl -s -X POST http://<host>:4010/auth/login \
          -d 'username=<admin>&password=<pass>' | jq -r .access_token)   # form-encoded!
curl -s -X PUT http://<host>:4010/doc_sla_policy \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"enabled": false}'
```

Kapan dimatikan: saat perlu **menguji tampilan PENDING** pada data yang submit_time-nya sudah
lama lewat (semua tiket jatuh ke FAIL sehingga PENDING tak pernah muncul di layar).

> **`POST /stats/refresh` TIDAK lagi diperlukan** untuk sakelar ini: kebijakannya ikut di
> dalam `_stats_signature` (versi `v11`), jadi snapshot Statistics otomatis basi dan
> dihitung ulang. Perubahan logika LAINNYA tetap butuh refresh manual — lihat §11.
>
> Konstanta lama `compliance/stats_aggregate.py: DOC_SLA_ENABLED` kini hanya **nilai
> cadangan** bila nilai DB belum sempat terbaca. **Jangan** mengeditnya untuk mengubah
> kebijakan — yang berlaku adalah isi `app_settings`.
>
> Semua pembaca tetap lewat `_doc_sla_expired()`. Worker tidak perlu di-restart
> (tidak mengimpor `stats_aggregate`).
>
> **Dampaknya besar pada data lama:** mengaktifkan kembali membuat semua tiket PENDING yang
> tenggatnya sudah lewat langsung terbaca Not Qualified, dan error rate organisasi naik.
> Contoh nyata 12 Agustus 2026: breakdown AI Status berubah dari
> `approve 12 / return 43 / pending 44` menjadi `approve 12 / return 87 / pending 0`.

---

## 10. Playbook Insiden

| Gejala | Diagnosis | Tindakan |
|---|---|---|
| Transkrip tidak diproses (status `pending`/`processing` lama) | Worker mati / Redis putus | `docker compose ps`; `docker compose logs -f worker`; cek Flower; `docker compose restart worker` |
| Semua evaluasi error | LLM endpoint down / API key habis / rate limit | Cek log worker (error dari `LLM_BASE_URL`); verifikasi `LLM_API_KEY`, kuota, konektivitas |
| Dashboard tampil versi lama | Aset di-cache/di-bake | `docker compose up -d --build dashboard` + hard refresh |
| Frontend gagal call API / CORS | `VITE_API_URL` salah saat build | Set nilai benar, rebuild dashboard |
| `localhost:4000` tidak bisa dari host | Port host api = **4010** | Pakai `http://<host>:4010` |
| api gagal start (bucket/MinIO error) | MinIO belum siap saat api boot | Pastikan MinIO healthy dulu, lalu `docker compose restart api` |
| DB penuh / lambat | Data menumpuk | Cek ukuran `./data/postgres` & `./data/minio`; arsip/hapus tiket lama; backup dulu |
| Admin lama masih ada setelah ganti `ADMIN_*` | Seed hanya saat tabel `users` kosong | Reset admin = wipe DB (`down -v`) — hati-hati, hapus semua data |
| Angka Statistics tidak berubah setelah ubah logika scoring | Snapshot di-cache per *signature data*, bukan versi kode | `POST /stats/refresh` (lihat §11) |
| Role melihat campaign yang bukan haknya | Tag campaign role/user belum di-set, atau cache permission | Cek `GET /roles` & `GET /roles/user_campaigns`; campaign efektif = irisan role ∩ user ∩ roster |
| Tidak ada yang bisa buka Manage User/Role | Sejak 10 Agustus 2026 hanya `admin` yang punya `admin.user.write`/`admin.role.write` | Pastikan ada akun `admin` aktif; bila hilang, perbaiki lewat DB langsung |
| Semua tiket kekurangan dokumen jadi Not Qualified | `DOC_SLA_ENABLED = True` & submit_time sudah lewat 48 jam | Perilaku benar (§9); matikan sakelar hanya untuk pengujian |

---

## 11. Cache Snapshot Statistics

Payload dashboard Statistics disimpan di tabel `stats_snapshots` dan dipakai ulang selama
**signature data** cocok (`crud._stats_signature`). Signature itu dihitung dari **data**, bukan
dari versi kode — jadi:

> Mengubah **logika** perhitungan (sakelar SLA, ambang band, mirror scoring, hitung ulang
> similarity statik, propagasi verifikasi → scorecard) **tidak** meng-invalidate cache.
> Dashboard akan menyajikan angka lama sampai ada data baru masuk.

Refresh **wajib** setelah perubahan yang menggeser skor atau AI Status tiket lama — snapshot
menyimpan keduanya, jadi tiket yang berpindah Qualified → Not Qualified tidak akan terlihat
di Statistics sampai dihitung ulang.

Paksa hitung ulang:

```bash
# Lewat endpoint (butuh login / X-API-Key)
curl -s -X POST -H "X-API-Key: $API_KEY" http://<host>:4010/stats/refresh

# Atau langsung di container
docker exec telemarketing-qc-system-api-1 python -c "
from api.dependencies import get_db
from db import crud
crud.get_or_build_stats_snapshot(next(get_db()), force=True)
print('snapshot recomputed')
"
```

Satu baris disimpan per hari WIB (baris hari ini ditimpa bila berubah; hari baru = baris baru).

---

## 12. Checklist Rutin

- **Harian:** cek `docker compose ps` (semua healthy), pantau error di log worker & Flower.
- **Mingguan:** backup PostgreSQL + MinIO; cek kapasitas disk `./data`.
- **Saat update kode:** backend → `restart api worker`; frontend → `up -d --build dashboard`.
- **Saat revisi QC logic:** upload ulang campaign; proses ulang tiket sampel untuk validasi;
  bila yang berubah kode Python (bukan prompt), jalankan juga `POST /stats/refresh`.
- **Berkala:** rotasi secret bila perlu (`JWT_SECRET_KEY`, `API_KEY`, password DB/MinIO/admin).

---

## Referensi terkait
- [`DEPLOYMENT.md`](./DEPLOYMENT.md) — instalasi & production hardening
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — campaign & model scoring
- [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) — katalog error code
- [`INTEGRATION.md`](./INTEGRATION.md) — ingestion & integrasi
- [`API_REFERENCE.md`](./API_REFERENCE.md) — endpoint & auth
- [`DATA_MODEL.md`](./DATA_MODEL.md) — skema DB & migrasi
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — role & akses menu
