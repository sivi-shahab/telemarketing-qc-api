# Dokumentasi Handover — Telemarketing QC System

Indeks paket dokumentasi untuk serah-terima sistem. Mulai dari atas.

> **Status: diverifikasi 28 Agustus 2026** terhadap kode & container yang berjalan
> (introspeksi route + permission, isi tabel DB, konfigurasi campaign aktif, md5 artefak
> DB vs berkas di `docs/`).
>
> **Pembaruan 28 Agustus 2026** — artefak campaign disinkronkan ke **prompt v74 + KB v34
> + scorecard v3**. Enam kenaikan versi prompt dalam satu hari (v69 → v74), semuanya
> berasal dari `csv_bank/28 Agustus 2026/update.md`. Perubahan terpenting:
>
> **Error code & badword**
> - **Dua error code baru** — **B27** (Offering bukan kepada Nasabah terundang, kategori
>   "Offering bukan kepada CH", Risk Base **M**) dan **B28** (Inappropriate Language,
>   Risk Base **M**). Keduanya ditambahkan ke `compliance/error_codes.py` DAN ke
>   `ALLOWED_ERROR_CODES` — tanpa yang kedua, kode ada di katalog tapi tidak pernah tampil.
> - **B28 diturunkan dari `badword_check`**, bukan dari LLM. Satu temuan badword = satu
>   baris B28 (bagian `--- 4)` di `build_error_code_table`). Karena diturunkan di sisi
>   KODE, tiket lama yang evaluasinya sudah punya `badword_check` langsung menampilkannya
>   tanpa Reprocess.
> - **Sepuluh frasa sarkas** dari kolom "Sampling details case" B28 disisipkan ke kategori
>   badword yang sudah ada.
>
> **Aturan pencocokan (v70, v72)**
> - **Nomor rekening wajib SAMA PERSIS** sesudah dinormalisasi (buang non-angka, buang nol
>   di depan). Ambang 80% tidak berlaku — pada nomor 10 digit ambang itu memaafkan sampai
>   dua digit salah. `4629790567` vs `4639790567` (90%) kini MISMATCH.
> - **Email dinilai TERPISAH** antara `local` dan `domain`, masing-masing harus >= 80.
>   Menghitung atas alamat utuh membuat domain yang identik menyeret local yang buruk
>   melewati ambang (`DEWIFITRI112@` vs `fitri112@` = 82% → lolos, padahal local hanya 67%).
> - **Nama TMS yang terpotong diselaraskan** — kolom TMS dibatasi lebar field, sehingga
>   `"DOROTA MEIANTIKO K"` untuk `"Dorota Meantiko Kurnadi"` jatuh ke 67%. Meniru
>   `_align_abbreviations` milik `nama_ibu_kandung`, dengan penyesuaian: token TERAKHIR TMS
>   boleh awalan berapa pun panjangnya. Ambang **tetap 90**, tanpa normalisasi fonetik.
>   Kalibrasi 97 baris: 6 pulih, 0 regresi, 0 bocor.
>
> **Penilaian**
> - **SC_CL_24 bertingkat** — `verified_count` 0 → item_score 0 (kehilangan 15), **1 → 7.5**,
>   >= 2 → 15. Tingkat tengah menghargai satu parameter yang benar-benar terverifikasi.
>   Nilai 7.5 memang masuk skor akhir walau kategorinya tetap FAIL, karena
>   `ai_score_phase_2` menjumlahkan `item_score`, bukan `category_score`.
> - **ZERO-SCORE RULE ditegakkan di KODE** (`compliance/scoring.py::no_product_interest`).
>   Sebelumnya aturan itu hanya hidup di prompt, sehingga hitung ulang deterministik
>   melewatkannya dan memberi PASS kepada tiket tanpa minat produk yang oleh LLM sudah
>   benar dinyatakan FAIL.
> - **Logika skor tidak lagi terduplikasi** — `api/routers/stats.py` dulu menyimpan salinan
>   `_max_score`/`_scorecard_score` sendiri dan tertinggal saat modul aslinya berubah;
>   kini didelegasikan ke `compliance/scoring.py`.
> - **Status PENDING dipropagasikan ke scorecard** — baris card holder di zona abu-abu
>   membuat SC_CL_23_1/23_2 ikut PENDING, dengan `item_score` DIPERTAHANKAN. Penangguhan
>   bukan vonis: skor tidak dipotong, tidak ada veto non-tolerable, tidak ada score bomb.
>
> **Evidence (v73)**
> - `5b` **Pemeriksaan silang reason ↔ kutipan** — kata kunci konkret pada reason harus
>   ada di dalam kutipannya.
> - `5c` **Greeting & Probing terikat pembukaan panggilan** — nama agent yang disebut ulang
>   di menit ke-6 bukan bukti perkenalan; "Bapak memiliki fasilitas dari Bank Mega"
>   (fasilitas nasabah) bukan "saya dari Bank Mega" (asal agent).
> - `5d` **Ucapan terpotong bukan dasar menyimpulkan ketiadaan** — transkrip VTT memotong
>   kalimat; wajib membaca ucapan berikutnya sebelum menyatakan BELUM_SESUAI.
> - **Pembacaan ulang oleh agent adalah verifikasi yang sah** — agent yang membacakan nilai
>   dari sistem lalu nasabah membenarkan TETAP verifikasi; `extracted_value` diisi dari
>   bacaan agent. Tidak berlaku untuk verifikasi statik (di sana melanggar B15).
>
> **Kebijakan yang dikunci (v71, v74)**
> - **Kontradiksi dokumen dicabut** (v71) — prompt sempat memuat dua instruksi berlawanan
>   tentang `nama_pemilik_rekening`: blok 21 Agu "TIDAK ada dokumen pendukung" vs blok
>   24 Agu "WAJIB cover buku tabungan". Yang benar blok 24 Agu; kodenya memang sudah
>   menjalankan itu.
> - **Fallback Final Konfirmasi PERMANEN** (v74) — item "Penjelasan Mega Cashline" yang
>   hanya terpenuhi di dalam Final Konfirmasi TETAP SESUAI. Pencabutan pernah diusulkan
>   dan ditolak (akan membalik 344 item di 98 tiket).
>
> Rincian tiap kenaikan versi: `CHANGELOG_prompt_v69_to_v70.md`, `_v70_to_v72.md`,
> `_v72_to_v73.md`, `_v73_to_v74.md`.

> **Pembaruan 24 Agustus 2026** — artefak campaign disinkronkan ke **prompt v68 + KB v34**
> (scorecard v3 tidak berubah), Alembic HEAD **`0044`**. Delapan perubahan, semuanya
> berasal dari enam tiket anomali di `csv_bank/24 Agustus 2026/update.md`:
>
> - **Segmen Final Konfirmasi kini punya SYARAT** (v66) — sebuah blok baru disebut recap
>   bila memuat pembuka pengulangan **dan** minimal dua nilai komersial. Legal statement
>   dan informasi pasca-persetujuan **bukan** recap, sehingga panggilan terakhir yang hanya
>   berisi keduanya tidak lagi memindahkan segmen recap ke sana. Pada tiket `220122UZKb`
>   (3 panggilan) kekeliruan ini menjatuhkan **7 item** Final Konfirmasi yang sebenarnya
>   terpenuhi: [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §Evidence.
> - **Kutipan pengisi dilarang** (v66) — satu kutipan yang sama tidak boleh dipakai sebagai
>   evidence ≥ 3 item ber-requirement berbeda; bila tidak ada segmen yang relevan, evidence
>   diisi `null`. Sebelumnya prompt justru MENYURUH mengisi "kutipan paling relevan".
> - **Penyelarasan singkatan Ascend untuk nama ibu kandung** (v68 + kode) — nama yang di
>   Ascend terpotong/disingkat (`TRI WAHJOENINGSIH T`, `TH RUSMINAH`) tidak lagi menghukum
>   nasabah yang menyebutnya lengkap: token transkrip **dipendekkan mengikuti bentuk Ascend**
>   sebelum similarity dihitung (`010550Vosa` 54% → **84%**). Acuan Ascend tidak pernah
>   disentuh, dan penyelarasan **hanya boleh menaikkan** nilai. Sesudahnya tabel band
>   berlaku apa adanya — **tanpa** pembebasan dokumen tersendiri.
> - **Health Declaration dilonggarkan** (KB v29) — "Apakah pernyataan/jawaban tersebut benar?"
>   kini sah sebagai permintaan kesediaan; frasa "bersedia" tidak lagi diwajibkan (3 tiket).
> - **Koroborasi TMS untuk nomor rekening** (v66) — nomor rekening TMS yang ditemukan di
>   transkrip (termasuk yang didikte sepotong-sepotong) membuat `SC_CL_14` SESUAI apa pun
>   kata-kata agent. Hanya boleh MENAIKKAN status, tidak pernah menurunkan.
> - **`nama_pemilik_rekening` minta cover buku tabungan** (v66) — ambang **90**; di bawah itu
>   tetap `MISMATCH` (skor tetap dipotong, B02 tetap terbit) **dan** dokumen diminta.
> - **Sakelar kebijakan SLA H+2 di menu Results** — indikator untuk semua peran, tombol
>   on/off khusus `admin`. Dulu konstanta di kode: [`API_REFERENCE.md`](./API_REFERENCE.md)
>   §Doc SLA Policy, [`RUNBOOK.md`](./RUNBOOK.md) §8.
> - **Tanggal cetak tagihan: angka 16 WAJIB** (KB v34) — "tanggal 25 saja" kini
>   BELUM_SESUAI; 16 adalah tanggal cetak untuk total tagihan terhutang, 25 hanya
>   pelengkap. Sekaligus frasa **"hari kalender"/"terdekat" tidak lagi diwajibkan**:
>   "tercetak pada tanggal enam belas atau dua lima **ke depan**" sudah sah
>   (tiket `200405z4B9`, semula BELUM_SESUAI).
> - **Suku bunga TnC Product dikoreksi ke 0,99%–3,99% per bulan (effective rate)** —
>   nilai RIPLAY "Mulai dari 1,75% (Flat per bulan)" adalah **ilustrasi memakai suku
>   bunga terendah** (catatan kaki RIPLAY sendiri menyatakannya), bukan envelope produk.
>   Dikoreksi di `campaigns.riplay_extraction`, sehingga TnC **dan** overlay KB
>   (`KB_CL_7`/`KB_CL_27`) ikut benar. ⚠️ **Meng-upload ulang RIPLAY PDF akan menimpa
>   koreksi ini.**
> - **Ringkasan Kategori: item `TIDAK_DINILAI` tidak lagi dihitung** — kategori MUS yang
>   seluruh itemnya dilewati dulu tampil **PASS bernilai penuh** dan membuat total 150
>   bertentangan dengan `maximum_score` 108,75. Kini 0/0 berlabel **TIDAK DINILAI**.
>
> **Pembaruan 21 Agustus 2026** — prompt v65 + KB v28, Alembic HEAD `0043`. Lima perubahan:
>
> - **Revamp verifikasi statik** (v56→v59): aturan konsistensi antar-penyebutan (≥ 90%)
>   **dihapus** — setiap penyebutan langsung diadu ke Ascend, yang tertinggi dipakai.
>   Aturan tanggal panggilan yang sempat menggantikannya (saringan mati di v56/v57, lalu
>   prioritas berjenjang di v58) **ikut dicabut pada v59 atas konfirmasi Bank Mega** —
>   tanggal panggilan bukan syarat pengambilan bukti. Ambang `nama_ibu_kandung` menjadi
>   **80 / 50** (dulu 90 / 80) dan `nama_pemilik_rekening` menjadi **90** (dulu 80). Tiap
>   penyebutan membawa `source_file` (nama PDF) untuk penelusuran:
>   [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1/§5.2.
> - **Bug penalti kritikal**: normalisasi memulihkan item scorecard `SC_CL_23_x` tetapi tidak
>   pernah melepas irisan `ai_score_critical_compliance_check`, sehingga tiket bisa berbunyi
>   MATCH + SESUAI namun tetap Not Qualified. Diperbaiki lewat `_restore_critical_items`
>   yang kini dipakai bersama applier banding.
> - **Tombol Reprocess per tiket** di kolom **Action** menu Results (kolom "Delete Record"
>   lama, kini memuat Reprocess + Delete bertumpuk): [`API_REFERENCE.md`](./API_REFERENCE.md)
>   §Reprocess Ticket, [`RUNBOOK.md`](./RUNBOOK.md) §7.
> - **Label "Indikasi Fraud" dihapus** dari kolom AI Status dan export XLSX (aturannya
>   sendiri sudah ikut dicabut bersama aturan konsistensi).
> - **Label field & sapaan** (v63) — "Nama ibu kandung, Wong Aiua" tidak lagi dinilai
>   berikut labelnya; 2 tiket keluar dari MISMATCH, 1 menjadi Qualified.
> - **Kolom Match dapat status `PENDING`** (v65) — zona abu-abu yang dokumennya masih
>   ditunggu dalam tenggat H+2; lewat tenggat tanpa unggah ia menjadi MISMATCH dan skornya
>   baru dipotong. Sekaligus memperbaiki `_missing_docs_map` yang menentukan kewajiban
>   dokumen dari angka LLM mentah, bukan angka ternormalisasi yang tampil di layar
>   (**38 tiket; 7 berubah Qualified → Not Qualified**).
> - **Tahun lahir 2000-an wajib 4 digit** (v62) — aturan yang selama ini hanya ada di prompt
>   dan **tidak pernah berjalan** (normalisasi Python menimpanya jadi MATCH 100%) kini
>   ditegakkan di kode.
> - **Mengeja = jawaban sah** (v60) — ejaan huruf-per-huruf tidak lagi dihukum oleh tanda
>   hubungnya (`020338gGlU`: 50% → 73%). Kelonggaran spasi yang sempat menyertainya (v61)
>   **dicabut pada v64**: acuan Ascend tidak boleh dimanipulasi.
> - **KB v21 → v28** — `scoring_rule` KB_CL_23_1/23_2 masih memuat aturan konsistensi ≥ 90%
>   yang sudah dicabut prompt, padahal prompt menyuruh "PATUHI scoring_rule di KB".
>   Kontradiksi itu dihapus, ambang band ditulis eksplisit, lalu aturan tanggalnya ikut
>   dicabut menyusul prompt v59. Riwayat per revisi ada di seri CHANGELOG pada
>   `campaign_cashline/` (mulai `CHANGELOG_kb_v21_to_v22.md`).
>
> Dampak terukur setelah rerun 98 tiket cashline: Qualified **10 → 26**.
>
> **Pembaruan 13 Agustus 2026** — artefak campaign disinkronkan ke **prompt v54** (KB v21 &
> scorecard v3 tidak berubah); ketiganya sudah diverifikasi **identik byte-per-byte** dengan
> `campaigns` id 18 di DB. Yang ikut didokumentasikan:
>
> - **Badword** (prompt v53, diperketat v54) — veto AI Status baru. Sejak 21 Agustus 2026 ia
>   **satu-satunya** veto yang masih menulis catatan di kolom AI Status:
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

## Arsitektur (mulai dari sini)
- [`ARSITEKTUR.md`](./ARSITEKTUR.md) — **dokumen arsitektur lintas-repo**: empat repositori dan kenapa `core` ada di dua tempat, topologi runtime + daftar port, pembagian compose, alur data (transkrip/OCR/reprocess), kepemilikan skema DB, integrasi eksternal (App A, App C, object storage S3, LLM), frontend + jebakan prefix `/api-b`, build/deploy Jenkins, urutan rilis wajib, dan langkah compose lengkap dari nol. Berlaku untuk **keempat** repo, bukan hanya `api`.

## Setup & Operasi
- [`DEPLOYMENT.md`](./DEPLOYMENT.md) — deploy dari GitHub ke server (Docker & non-Docker) + production hardening.
- [`RUNBOOK.md`](./RUNBOOK.md) — operasi harian: monitoring, restart, scaling, backup/restore, sakelar SLA H+2, refresh snapshot Statistics, insiden.

## Logika QC (pengetahuan inti)
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — konfigurasi campaign (prompt/KB/scorecard/RIPLAY), model scoring, dan precedence status PASS/FAIL/PENDING.
- [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) — katalog 46 error code, risk base, efek banding.

## Referensi Teknis
- [`PIPELINE_PDF_TO_RESULTS.md`](./PIPELINE_PDF_TO_RESULTS.md) — perjalanan satu tiket: PDF masuk → worker → evaluasi LLM → baris di halaman Results.
- [`INTEGRATION.md`](./INTEGRATION.md) — ingestion (webhook), worker Celery, integrasi LLM, OCR, dan RIPLAY.
- [`API_REFERENCE.md`](./API_REFERENCE.md) — 68 operasi REST, autentikasi (JWT + X-API-Key), permission per endpoint.
- [`DATA_MODEL.md`](./DATA_MODEL.md) — skema DB (21 tabel), relasi, alur migrasi Alembic (HEAD `0049`).

## Organisasi & Akses
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — model capability, 10 role bawaan, matriks permission, `data_scope`, pembatasan campaign.
- [`CREDENTIALS.md`](./CREDENTIALS.md) — cara membuat akun (username/password) Sales & QC dari CSV masing-masing (tanpa kredensial asli).

## Artefak Campaign Aktif
- `prompt_cashline_mus_v74.txt`, `cashline_kb_v34.txt`, `cashline_scorecard_v3.txt` — file sumber campaign Cashline (id 18) yang sedang berjalan, **identik byte-per-byte** dengan `campaigns` id 18 di DB (KB = `kb_text_raw`, tanpa overlay RIPLAY). Riwayat versi + CHANGELOG ada di `../campaign_cashline/`.

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

> Arsitektur sistem ada di [`ARSITEKTUR.md`](./ARSITEKTUR.md) (lihat bagian teratas),
> bukan di `../README.md` — README repo hanya memuat quick-start singkat.
