# Dokumentasi Handover — Telemarketing QC System

Indeks paket dokumentasi untuk serah-terima sistem. Mulai dari atas.

> **Status: diverifikasi 12 Agustus 2026** terhadap kode & container yang berjalan
> (introspeksi route + permission, isi tabel DB, revisi Alembic, konfigurasi campaign aktif).
>
> **Pembaruan 13 Agustus 2026** — artefak campaign disinkronkan ke **prompt v54** (KB v21 &
> scorecard v3 tidak berubah); ketiganya sudah diverifikasi **identik byte-per-byte** dengan
> `campaigns` id 18 di DB. Yang ikut didokumentasikan:
>
> - **Badword** (prompt v53, diperketat v54) — veto AI Status baru, sejajar Indikasi Fraud:
>   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7.
> - **Tag panggilan `[Pn]`** (v54) — memperbaiki `evidence.ticket_id` yang salah panggilan
>   pada transkrip panjang: [`INTEGRATION.md`](./INTEGRATION.md) §4.
> - **Verifikasi statik**: hitung ulang similarity kini disertai penulisan ulang `reason`,
>   dan propagasi verifikasi → scorecard → critical compliance diperbaiki agar berjalan pada
>   tiket tanpa banding (**menggeser skor 3 tiket, 2 di antaranya PASS → Not Qualified**):
>   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1/§6,
>   [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) §4/§5.
>
> **Pembaruan 14 Agustus 2026** — **AI Status dihitung, tidak pernah disimpan**, dan export
> XLSX per tiket kini mengikuti vonis kanonik yang sama dengan daftar Results:
>
> - Sheet `ringkasan_penilaian_ai` dulu menyimpulkan sendiri baris "Hasil" dari dict evaluasi,
>   sehingga buta terhadap aturan dokumen H+2 dan Manual Status yang sudah disetujui —
>   **21 dari 98 tiket ter-export "LULUS" padahal Not Qualified**. Setiap sebab gugur kini
>   punya baris alasannya sendiri (termasuk veto non-tolerable, yang sebelumnya tidak pernah
>   dijelaskan): [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7.2.
> - Field `ai_status` **di dalam** `result_json → evaluation` adalah tebakan LLM yang tidak
>   pernah ditulis ulang dan **meleset 30%** (29 dari 98 tiket, semuanya terlalu longgar).
>   Jangan dipakai untuk laporan/integrasi: [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7.1.
>
> **Pembaruan 14 Agustus 2026 (putaran kedua)** — migrasi **`0041_admin_only_data_menus`**,
> lima perubahan yang menggeser hak akses dan angka laporan:
>
> - **Seluruh pengurusan data pindah ke Admin.** Campaigns, Database Sales & QC, semua menu
>   Upload Data, dan Delete Campaign dicabut dari setiap role lain — 19 permission dikunci
>   `ADMIN_ONLY_PERMISSIONS`, tidak lagi bisa diberikan lewat Manage Role.
>   **QC Support jadi lumpuh** (kehilangan hak upload padahal cakupannya "tiket sendiri") —
>   ini disengaja: [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §4.1.
> - **Error Rate: satu rumus untuk semua panel** — `Total Risk (H+M+L) ÷ Submissions`, dengan
>   pengecualian tiket yang hanya kena `L` pada item `tolerable: YES`. Sebelumnya Overview &
>   Hierarki memakai rasio reject sementara Performa Campaign memakai risk base, sehingga
>   angka untuk pertanyaan yang sama tidak pernah cocok:
>   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §8.1.
> - **Dua error code dokumen baru** — **B09** (tenggat H+2 lewat tanpa dokumen, `Error - Human`,
>   Risk `M`) dan **C03** (dokumen salah jenis, `Error - Customer`, Risk `O`). Keadaan pertama
>   dulu tidak menerbitkan kode apa pun sehingga terhitung `O`:
>   [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) §5.1.
> - **Tabel Error Code memakai kosakata sheet QC** — kolom `Error Type` & `Error Category`
>   ditambahkan, `Details Error` disamakan dengan sheet: [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) §4.1.
> - **Sales Agent tidak bisa lagi membuka dokumen pendukung**, dan SPQ Head menukar Export
>   Agregat dengan **`GET /export_tickets_xlsx`** (semua tiket satu periode):
>   [`API_REFERENCE.md`](./API_REFERENCE.md) §5.3.
>
> Sesudah deploy: `POST /stats/refresh`.

## Setup & Operasi
- [`DEPLOYMENT.md`](./DEPLOYMENT.md) — deploy dari GitHub ke server (Docker & non-Docker) + production hardening.
- [`RUNBOOK.md`](./RUNBOOK.md) — operasi harian: monitoring, restart, scaling, backup/restore, sakelar SLA H+2, refresh snapshot Statistics, insiden.

## Logika QC (pengetahuan inti)
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — konfigurasi campaign (prompt/KB/scorecard/RIPLAY), model scoring, dan precedence status PASS/FAIL/PENDING.
- [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) — katalog 46 error code, risk base, efek banding.

## Referensi Teknis
- [`INTEGRATION.md`](./INTEGRATION.md) — ingestion (webhook), worker Celery, integrasi LLM, OCR, dan RIPLAY.
- [`PIPELINE_PDF_TO_RESULTS.md`](./PIPELINE_PDF_TO_RESULTS.md) — perjalanan satu tiket: PDF masuk → worker → evaluasi LLM → baris di halaman Results.
- [`API_REFERENCE.md`](./API_REFERENCE.md) — 68 operasi REST, autentikasi (JWT + X-API-Key), permission per endpoint.
- [`DATA_MODEL.md`](./DATA_MODEL.md) — skema DB (18 tabel), relasi, alur migrasi Alembic (HEAD `0041`).

## Organisasi & Akses
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — model capability, 10 role bawaan, matriks permission, `data_scope`, pembatasan campaign.
- [`CREDENTIALS.md`](./CREDENTIALS.md) — cara membuat akun (username/password) Sales & QC dari CSV masing-masing (tanpa kredensial asli).

## Artefak Campaign Aktif
- `prompt_cashline_mus_v54.txt`, `cashline_kb_v21.txt`, `cashline_scorecard_v3.txt` — file sumber campaign Cashline (id 18) yang sedang berjalan. Riwayat versi + CHANGELOG ada di `../campaign_cashline/`.

---

## Lima hal yang paling sering salah dipahami

1. **Admin ≠ SPQ Head.** Admin mengurus sistem (user, role, campaign, database, seluruh
   Upload Data); SPQ Head memutus perkara QC. Sejak 14 Agustus 2026 pemisahan ini **hampir
   total** — SPQ Head tidak lagi menyentuh campaign, database, upload, maupun hapus tiket.
   Hanya `admin` yang bisa mengelola user & role, jadi jaga selalu ada satu akun Admin aktif.
   Detail: [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §3 & §4.1.
2. **Akses ditentukan permission, bukan nama role.** Guard lama `get_spq_head_user` dkk. sudah
   tidak dipakai sebagai gate endpoint. Detail: [`API_REFERENCE.md`](./API_REFERENCE.md) §2.
3. **Cache Statistics tidak peduli perubahan kode.** Signature snapshot berbasis data, jadi
   setelah mengubah logika scoring wajib `POST /stats/refresh`. Detail:
   [`RUNBOOK.md`](./RUNBOOK.md) §11.
4. **AI Status tidak ada kolomnya di DB.** `results.status` adalah status *pipeline*
   (`pending`/`processing`/`done`/`failed`), bukan vonis QC. AI Status dihitung ulang tiap
   request dari `result_data` + `error_code_appeals` + `qc_status_requests` + `documents` —
   dan bergantung waktu berjalan (PENDING → FAIL saat tenggat H+2 lewat). Field `ai_status`
   di dalam `result_json` hanya tebakan LLM yang tidak pernah ter-update. Detail:
   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §7.1.
5. **Error Rate ≠ persentase Not Qualified.** Sejak 14 Agustus 2026 rumusnya
   `Total Risk (H+M+L) ÷ Submissions` di **semua** panel Statistics — satu risk base tertinggi
   per tiket, dan tiket yang hanya kena `L` pada item `tolerable: YES` tidak dihitung. Kolom
   `Errors` (jumlah Not Qualified) tetap tampil tapi bukan pembilangnya. Detail:
   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §8.1.

---

## Yang perlu diserahkan terpisah (non-dokumen)
- **Config reverse proxy eksternal** (routing `/telemarketing_qc_system/` + `/api`) — tidak ada di repo, ambil dari server.
- **`.env` production** (secret asli) — via kanal aman.
- **Kredensial infrastruktur**: SSH server, DNS/domain, sertifikat TLS, LLM API key + billing, OCR endpoint/key, akun GitHub.
- **Backup data**: `./data/{postgres,minio}`.
- **Checklist rotasi secret**: `JWT_SECRET_KEY`, `API_KEY`, password DB/MinIO/admin.

> README utama proyek (Docker quick-start, arsitektur) ada di [`../README.md`](../README.md).
