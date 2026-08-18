# Dokumentasi Handover — Telemarketing QC System

Indeks paket dokumentasi untuk serah-terima sistem. Mulai dari atas.

> **Status: diverifikasi 12 Agustus 2026** terhadap kode & container yang berjalan
> (introspeksi route + permission, isi tabel DB, revisi Alembic, konfigurasi campaign aktif).

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
- [`DATA_MODEL.md`](./DATA_MODEL.md) — skema DB (18 tabel), relasi, alur migrasi Alembic (HEAD `0040`).

## Organisasi & Akses
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — model capability, 10 role bawaan, matriks permission, `data_scope`, pembatasan campaign.
- [`CREDENTIALS.md`](./CREDENTIALS.md) — cara membuat akun (username/password) Sales & QC dari CSV masing-masing (tanpa kredensial asli).

## Artefak Campaign Aktif
- `prompt_cashline_mus_v52.txt`, `cashline_kb_v21.txt`, `cashline_scorecard_v3.txt` — file sumber campaign Cashline (id 18) yang sedang berjalan. Riwayat versi + CHANGELOG ada di `../campaign_cashline/`.

---

## Tiga hal yang paling sering salah dipahami

1. **Admin ≠ SPQ Head.** Admin mengurus sistem (user, role, campaign, database); SPQ Head
   memutus perkara QC. Hanya `admin` yang bisa mengelola user & role — jaga selalu ada satu
   akun Admin aktif. Detail: [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §3.
2. **Akses ditentukan permission, bukan nama role.** Guard lama `get_spq_head_user` dkk. sudah
   tidak dipakai sebagai gate endpoint. Detail: [`API_REFERENCE.md`](./API_REFERENCE.md) §2.
3. **Cache Statistics tidak peduli perubahan kode.** Signature snapshot berbasis data, jadi
   setelah mengubah logika scoring wajib `POST /stats/refresh`. Detail:
   [`RUNBOOK.md`](./RUNBOOK.md) §11.

---

## Yang perlu diserahkan terpisah (non-dokumen)
- **Config reverse proxy eksternal** (routing `/telemarketing_qc_system/` + `/api`) — tidak ada di repo, ambil dari server.
- **`.env` production** (secret asli) — via kanal aman.
- **Kredensial infrastruktur**: SSH server, DNS/domain, sertifikat TLS, LLM API key + billing, OCR endpoint/key, akun GitHub.
- **Backup data**: `./data/{postgres,minio}`.
- **Checklist rotasi secret**: `JWT_SECRET_KEY`, `API_KEY`, password DB/MinIO/admin.

> README utama proyek (Docker quick-start, arsitektur) ada di [`../README.md`](../README.md).
