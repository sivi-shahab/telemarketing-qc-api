# Runbook cutover — core jadi paket pip

Prosedur menaikkan image api dan worker hasil de-vendoring ke host. Berlaku
**sekali**, saat perpindahan dari `core/` yang disalin ke paket
`telemarketing-qc-core`. Sesudah itu deploy kembali mengikuti
`deployment_guidelines.md` masing-masing repo.

Spec dan rencana: `telemarketing-qc-core/docs/superpowers/`.

> **Tidak ada perubahan perilaku dalam rilis ini.** Seluruh pekerjaan bersifat
> build-time: kode yang berjalan sama persis, hanya jalannya masuk ke image yang
> berbeda. Suite api sebelum dan sesudah de-vendoring identik (96 lulus, 38
> lewat). Kalau setelah cutover ada perilaku yang berubah, itu regresi —
> rollback, jangan "perbaiki maju".

---

## 0. Prasyarat

### Tag core sudah ada di remote

Ini gerbangnya. Tanpa tag, `docker build` berhenti di stage builder.

```bash
git ls-remote --tags https://github.com/sivi-shahab/telemarketing-qc-core.git
```

Harus memuat `refs/tags/v1.0.0`. Kalau kosong, cabang core dan tag-nya belum
di-push — hentikan di sini, tidak ada langkah berikutnya yang bisa jalan.

### Versi core sama di kedua repo

```bash
grep -h 'telemarketing-qc-core @' \
  /data/scorecard_v2/telemarketing-qc-api/api/requirements.txt \
  /data/scorecard_v2/telemarketing-qc-worker/worker/requirements.txt
```

Kedua baris harus berakhiran tag yang sama. Beda versi antara api dan worker
tidak menimbulkan error — hanya perbedaan perilaku diam-diam di dua proses yang
seharusnya sepakat.

### Ruang disk

Build stage builder mengunduh dan mem-build wheel; `pdfplumber` + `pypdfium2`
tidak kecil. Cutover 8 September 2026 gagal di tengah jalan dengan
`no space left on device` karena root sudah 100% penuh.

```bash
df -h /            # sisakan minimal ~10 GB sebelum mulai
docker system df   # kalau mepet: docker builder prune -f (cache saja, aman)
```

### Titik rollback

**Wajib, dan mudah terlewat:** compose memberi image nama tetap
`local/qc-api:latest` dan `local/qc-worker:latest`. Rebuild menimpanya, dan
image lama kehilangan nama — tidak ada yang bisa dikembalikan. Beri nama dulu
sebelum build:

```bash
docker tag local/qc-api:latest    local/qc-api:pre-devendor
docker tag local/qc-worker:latest local/qc-worker:pre-devendor
docker images | grep pre-devendor      # pastikan keduanya ada
```

---

## 1. Build (tanpa menyentuh yang sedang berjalan)

`docker compose build` hanya membangun image; container lama tetap melayani
sampai `up` dijalankan di langkah 2.

```bash
cd /data/scorecard_v2/telemarketing-qc-api       && docker compose build api
cd /data/scorecard_v2/telemarketing-qc-worker    && docker compose build
```

Yang wajar terlihat di log: stage `builder` memasang `git`, lalu
`pip wheel` meng-clone core dari `git+https` dan meng-checkout tag-nya. Stage
runtime memasang semuanya dengan `--no-index` — tidak ada yang ditarik dari
jaringan di sana.

Periksa hasilnya sebelum menyalakan apa pun:

```bash
for img in local/qc-api:latest local/qc-worker:latest; do
  echo "=== $img"
  docker run --rm --entrypoint sh $img -c '
    command -v git >/dev/null && echo "GAGAL: git terbawa ke image akhir" || echo "OK: git tidak ada"
    ls /wheels >/dev/null 2>&1 && echo "GAGAL: /wheels tertinggal" || echo "OK: /wheels tidak ada"
    python -c "import qc_core; print(\"qc_core\", qc_core.__version__)"'
done
```

Ketiga baris harus `OK`, dan versi `qc_core` sama dengan tag di
`requirements.txt`.

Khusus worker, buktikan kontrak dengan api sebelum deploy — nama task yang
berubah tidak melempar error, task-nya hanya menggantung di antrian:

```bash
docker run --rm --entrypoint sh local/qc-worker:latest -c '
python -c "
from qc_core.compliance.documents import load_prompt_module
[load_prompt_module(d) for d in (\"ktp\",\"kk\",\"npwp\",\"cover_buku_tabungan\")]
from worker.celery_app import celery_app
import worker.tasks.process_document, worker.tasks.process_transcript, worker.tasks.reprocess_ticket
n = set(celery_app.tasks)
for t in (\"worker.tasks.process_document.process_document\",
          \"worker.tasks.process_transcript.process_transcript\",
          \"worker.tasks.reprocess_ticket.reprocess_ticket\"):
    assert t in n, t
print(\"OK: keempat prompt ter-resolve + ketiga task terdaftar\")
"'
```

---

## 2. Deploy — api dulu, baru worker

Urutannya tidak boleh dibalik: api satu-satunya yang menjalankan
`alembic upgrade head`.

### 2a. Cek migrasi tertunda

Rilis ini **tidak membawa migrasi baru**, jadi yang benar adalah jarak nol. Kalau
ternyata ada revisi tertunda, itu datang dari pekerjaan lain — baca dulu sebelum
melanjutkan, karena `alembic upgrade head` jalan otomatis saat container start
dan tidak menanyakan konfirmasi. DB DWH dipakai bersama tim lain.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker compose run --rm --entrypoint sh api -c 'alembic current && alembic heads'
```

`alembic current` di image baru sekaligus membuktikan `db/migrations/env.py`
bisa mengimpor `qc_core.db.models` — kalau ini jalan, migrasi saat start juga
akan jalan.

### 2b. Naikkan api

```bash
docker compose up -d api
docker compose logs -f api        # tunggu migrasi + "Uvicorn running"
```

Verifikasi:

```bash
curl -f http://localhost:4000/health                      # {"status":"ok"}
docker compose exec -T api python -c "import qc_core; print(qc_core.__version__)"
```

Log startup yang sehat **tidak** memuat `[minio] Lewati ensure bucket`. Kalau
muncul, bucket tidak terjangkau — hampir selalu soal sertifikat, dan di rilis ini
yang pertama dicurigai adalah `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` atau
`bankmegalocal.crt` yang tidak ikut ke image baru:

```bash
docker compose exec -T api sh -c 'env | grep -E "SSL_CERT_FILE|REQUESTS_CA_BUNDLE"; \
  ls -l /usr/local/share/ca-certificates/bankmegalocal.crt'
```

### 2c. Naikkan worker dan flower

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker compose up -d
docker compose logs -f worker     # tunggu banner celery + daftar [tasks]
```

Banner Celery mencetak daftar task yang terdaftar. Ketiganya harus ada:
`process_document`, `process_transcript`, `reprocess_ticket`.

---

## 3. Verifikasi menyeluruh

Yang membuktikan cutover benar bukan container yang hidup, melainkan satu tiket
yang benar-benar diproses dari ujung ke ujung — di situlah api, worker, core,
S3, dan LLM bertemu sekaligus.

1. Login di dashboard, buka satu tiket, jalankan **reprocess**.
2. Ikuti perpindahannya di Flower (`http://localhost:4005`): task harus
   **diambil** worker, bukan menggantung `PENDING`. Task menggantung = nama task
   tidak cocok antara api dan worker.
3. Pastikan hasilnya muncul di halaman Results dengan skor terisi.
4. Untuk tiket berdokumen, pastikan OCR-nya jalan — di situlah
   `load_prompt_module()` benar-benar dipanggil, jalur yang dulu bergantung pada
   trik `sys.path` dan `COPY core/prompt`.

Pemeriksaan cepat sisi data:

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker compose exec -T api python -c "
from api.dependencies import get_minio, get_settings
from qc_core.services.s3_buckets import _BUCKET_CREDENTIAL_FIELDS
s, c = get_settings(), get_minio()
for bf, akf, _ in _BUCKET_CREDENTIAL_FIELDS:
    b = getattr(s, bf, '')
    if b: print(f'{b:20s} exists={c.bucket_exists(b)}')
"
```

Keenam bucket harus `exists=True`.

---

## 4. Rollback

Tidak ada migrasi dan tidak ada perubahan skema, jadi rollback cukup
mengembalikan image — data tidak perlu disentuh.

```bash
docker tag local/qc-api:pre-devendor    local/qc-api:latest
docker tag local/qc-worker:pre-devendor local/qc-worker:latest

cd /data/scorecard_v2/telemarketing-qc-api    && docker compose up -d --no-build api
cd /data/scorecard_v2/telemarketing-qc-worker && docker compose up -d --no-build
```

`--no-build` penting: tanpa itu Compose membangun ulang dari kode yang sudah
di-de-vendor dan menimpa lagi image lama yang baru saja dikembalikan.

Kalau rollback terpaksa dilakukan, catat gejalanya sebelum image barunya
dihapus — image `:devendor`-nya masih bisa diperiksa dengan `docker run` tanpa
mengganggu container yang sudah kembali normal.

---

## 5. Sesudah cutover

- Hapus tag `pre-devendor` setelah beberapa hari tenang, bukan di hari yang
  sama — itu satu-satunya jalan pulang.
- `docs/ARSITEKTUR.md` bab 5 dan 12 masih menjelaskan model submodule `core/`
  yang sudah tidak berlaku (sudah tidak akurat bahkan sebelum rilis ini, sejak
  vendoring). Perlu ditulis ulang terpisah.
- Rantai bump otomatis (rilis core → PR bump di api dan worker) baru hidup
  setelah secret `CROSS_REPO_TOKEN` dipasang di repo core. Sampai saat itu,
  naikkan versi core dengan menyunting satu baris di `requirements.txt`.
