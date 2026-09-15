# E2E Telemarketing QC — empat repo, satu alur

Menguji `telemarketing-qc-api`, `telemarketing-qc-worker`, `telemarketing-qc-core`
(lewat keduanya) dan `telemarketing-qc-dashboard` sebagai **satu sistem**, di lingkungan
yang sepenuhnya terisolasi.

```
./jalankan.sh          # nol sampai Allure report
./jalankan.sh test     # hanya test + report (stack sudah jalan)
./jalankan.sh bersih   # hentikan stack, buang volume
```

Report: `artefak/allure-report/index.html` — sedang dilayani di **http://localhost:14200**

## Hasil

**28 test, 28 lulus, 0 gagal.**

| Feature | Lulus |
|---|---|
| Infrastruktur & migrasi | 5/5 |
| Pipeline penilaian | 4/4 |
| Scorecard v4 | 4/4 |
| Field respons baru | 3/3 |
| Bentuk prompt & caching | 3/3 |
| Auto Assign | 3/3 |
| Dashboard (bundle produksi) | 6/6 |

## Yang membuat ini e2e, bukan integration test

* **Image yang diuji dibangun dari Dockerfile repo masing-masing**, bukan image khusus
  test — termasuk salinan datar `core/` ke `/app`, persis bentuk yang naik ke produksi.
* **Transkrip yang dipakai PDF nyata** (4 berkas, tiket `060257HO0l`), diparsing
  `pdfplumber` sungguhan.
* **Worker Celery sungguhan** mengambil task lewat Redis sungguhan, menulis ke MinIO dan
  Postgres sungguhan.
* **Migrasi dijalankan dari NOL** di skema `dashboard` — sama seperti produksi.

## Yang distub, dan kenapa

Hanya **panggilan model**. `LLM_BASE_URL` menunjuk `e2e/stub_llm`, sebuah server
OpenAI/Azure-compatible.

Alasannya bukan kemudahan: **vonis model tidak deterministik dan tidak bisa di-assert**.
Dengan stub, seluruh jalur di sekelilingnya justru bisa diperiksa ketat — termasuk
`cached_tokens` dan `reasoning_tokens` yang dipalsukan supaya jalur pencatatan token
(Batch 8) ikut teruji.

**Kode keempat repo tidak diubah sama sekali** untuk keperluan test. Stub dipasang lewat
environment, bukan lewat tambalan di kode yang diuji.

## Apa yang sebenarnya dibuktikan

Beberapa test dirancang untuk gagal kalau port dev→prod meleset:

| Test | Yang ditangkapnya |
|---|---|
| `test_alembic_di_kepala_0053` | rantai migrasi bercabang (dua migrasi mengaku `0052`) |
| `test_max_score_135_5` | bobot v3 (150) masih dipakai alih-alih v4 (135,5) |
| `test_skor_diturunkan_bukan_dibaca` | server membaca skor dari keluaran LLM, bukan menurunkannya sendiri |
| `test_snapshot_reference_data` | port W1 membuang `reference_data` dari `result_json` — seluruh jalur snapshot mati tanpa satu error pun |
| `test_urutan_blok` | penataan prompt Batch 8 tidak sampai ke permintaan HTTP |
| `test_reprocess_active_bertahan` | skema dev diambil apa adanya sehingga field milik prod lenyap |
| `test_kelas_tahap_di_css` | CSS `stage-*` tertinggal; tabel progres tampil tanpa warna dan ikon |
| `test_bobot_v4` (dashboard) | angka v3 masih ter-bake di bundle yang dikirim ke browser |
| `test_llm_distub` | `LLM_BASE_URL` salah menunjuk endpoint sungguhan |

Yang terakhir itu penjaga keselamatan, bukan penjaga mutu.

## Dua temuan dari menjalankannya

**1. Migrasi tidak membuat skema `dashboard`.** `env.py` hanya menyetel `search_path` dan
`version_table_schema`; skemanya harus sudah ada. Container API mati saat startup dengan
`InvalidSchemaName` sampai `pg-init/01-skema.sql` ditambahkan. Di produksi skema itu
memang sudah ada sebagai skema DWH, jadi ini tidak terlihat di sana — tetapi instalasi
baru mana pun akan tersandung.

**2. User bawaan tidak bisa membuat campaign.** Migrasi `0001` menyemai user dengan role
**`spq_head`**, dan `spq_head` tidak punya `admin.campaign.write` maupun izin Manage User.
Jadi di instalasi baru tidak ada satu pun akun yang bisa membuat campaign lewat API —
akun `admin` harus dibuat sengaja, langsung di database. E2E menyisipkannya sendiri
(fixture `user_admin`) alih-alih melonggarkan RBAC yang sedang diuji.

## Susunan

```
e2e/
  docker-compose.e2e.yml   stack terisolasi (pg, redis, minio, stub, api, worker)
  .env.e2e                 seluruh konfigurasi; tidak ada yang menunjuk produksi
  pg-init/01-skema.sql     CREATE SCHEMA dashboard (lihat temuan 1)
  stub_llm/                server OpenAI-compatible + jejak permintaan
  allure-cli/              image ber-JRE; host tidak punya Java
  tests/                   7 berkas pytest + fixture
  artefak/allure-report/   report hasil render (tidak di-commit)
  jalankan.sh
```

## Batas yang jujur

* **Vonis model tidak diuji** — memang tidak bisa; lihat bagian stub.
* **Dashboard diuji lewat bundle hasil build**, bukan lewat browser. Yang dibuktikan:
  string dan kelas CSS yang benar sampai ke artefak. Interaksi layar (klik, render tabel)
  butuh Playwright dan belum ada.
* **Satu tiket, satu campaign.** Cukup untuk membuktikan alurnya; belum menguji beban,
  balapan antar-worker, maupun tiket dua-agent.
* **Data uji bukan salinan produksi.** `results` di produksi kosong, jadi tidak ada yang
  bisa disalin (lihat `telemarketing-qc-api/docs_api_15092026.md` §29).
