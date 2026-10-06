# Plan: Campaign NTB (New to Bank) — KB, Scorecard, Prompt + penyesuaian backend

Disusun 5 Oktober 2026. **Perencana: Opus. Pelaksana: Sonnet.**

Pelaksana: kerjakan **per fase, berurutan**. Tiap fase punya *Kriteria selesai*.
Jangan lanjut ke fase berikutnya sebelum kriteria fase sebelumnya terpenuhi. Bagian
bertanda **⛔ STOP** berarti: berhenti dan tanyakan ke user, jangan menebak.

---

## 0. Ringkasan

NTB adalah penjualan **kartu kredit baru** ke calon nasabah yang belum punya kartu Bank Mega.
Campaign Cashline (`docs/cashline_kb_v38.txt`, `docs/cashline_scorecard_v31.txt`,
`docs/prompt_cashline_mus_v82.txt`) dipakai sebagai **acuan format dan gaya aturan**, bukan
sebagai isi.

Ada tiga perbedaan mendasar dari Cashline:

| | Cashline | NTB |
|---|---|---|
| Nasabah | Card holder lama → **diverifikasi** (tanggal lahir, ibu kandung, dinamis 2-dari-9) memakai data **Ascend** | Calon nasabah baru → **tidak ada data Ascend**, tidak ada verifikasi statik/dinamis. Agent justru **mengumpulkan data aplikasi** (≈40 field) |
| Data acuan | TMS (`tms_cashline`) + Ascend (`ascend_custp`), dibandingkan dengan ucapan nasabah | **Tidak ada perbandingan Ascend.** Penilaian murni dari transkrip |
| Varian | Cashline (100) + MUS (50), MUS wajib sejak 8 Sep 2026 | 4 varian aditif: Basic (100) / +Supplement (125) / +MUS (150) / +MUS+Supplement (175). MUS & Supplement **opsional** |

### Sumber (sudah dibaca perencana)
- `docs/NTB/Script NTB Okt 26.xlsx` — sheet `Probing`: alur script (Greeting → Probing promo →
  Program Cashback NTB → Promo Hartono → Info cashback kartu tambahan → Pengisian data (tabel
  49 field di gambar) → Penawaran MUS → PDP MUS → Health Declaration → Agree Supplement (+ tabel
  field supplement di gambar) → Sharing Data → PDP Supplement → 4 varian Final Confirmation →
  Link Microsite → Closing → Handling Objection).
- `docs/NTB/Score Card NTB_Supplement_MUS 05102026.xlsx` — **scorecard yang berlaku** (5 Okt
  2026, menggantikan versi lama `M19 - Axel-M07-Dhea-M20` yang sudah dihapus dari folder). 4 sheet varian +
  sheet `Tampilan TMS2` (screenshot form TMS2 "MAIN CAMPAIGN: New To Bank Eksternal").
- Dump teks kedua file (dipakai pelaksana): jalankan ulang skrip di Lampiran A, jangan
  mengandalkan ingatan.

### Temuan penting: backend saat ini **memblokir** NTB
Campaign hanyalah 1 baris `campaigns` (prompt/KB/scorecard sebagai teks, diunggah lewat
Admin → Upload Campaign). LLM tidak peduli nama campaign. Yang hardcoded ke Cashline adalah
semua kode **sesudah** LLM:

1. **Gerbang data acuan** — `worker/tasks/process_transcript.py:422-464`: tiket tanpa baris
   `tms_cashline` **atau** `ascend_custp` → langsung `PENDING`, LLM tidak dipanggil. Semua tiket
   NTB akan berhenti di sini.
2. **Status saat baca** — `core/compliance/stats_aggregate.py` `data_gap_map` (~698-775) dan
   `_result_ai_status` (~873), duplikatnya di `api/routers/stats.py:850-871`: `DATA_GAP_ASCEND`
   memaksa PENDING.
3. **Skor maksimal** — `core/compliance/scoring.py:178-215` `max_score`: 100 bila
   `cashline_interest`, +50 bila `mus_interest`. Bila NTB memakai kunci `mus_interest`, skornya
   jadi 50, salah.
4. **Item kritis** — `core/compliance/error_codes.py:3482` `CRITICAL_ITEM_CODES = SC_CL_*`.
5. **Error code per kategori** — `error_codes.py:345-354` `CATEGORY_ERROR_CODES` memakai nama
   kategori Cashline; `ITEM_CODE_RE` (`:380-407`) hanya mengenali `SC_CL_`.
6. **Dua tahap / paralel** — `core/compliance/two_pass.py:52-79` (`MANDATORY_PASS2_CODES`),
   `parallel_pass.py` (blok `cashline_*`).
7. **RIPLAY** — `core/compliance/riplay.py` memetakan ke `KB_CL_*`. NTB: **jangan unggah RIPLAY**.
8. **Dashboard** — `dashboard/src/components/EvaluationView.vue` (panel minat Cashline/MUS
   `:663-682`, `MUS_CATEGORIES :1024`, `CATEGORY_ERROR_CODES :1160`, `maxScoreBreakdown
   :1262-1351` 100/50 tetap).

Jadi "membuat KB dan prompt" saja **tidak cukup** agar NTB bisa dinilai. Fase 3–4 di bawah
menangani backend dan dashboard, dengan prinsip **nol perubahan perilaku untuk Cashline**.

---

## 1. Keputusan desain

Bagian D1–D9 adalah keputusan perencana. Yang bertanda *(konfirmasi)* memakai default yang
masuk akal, tapi **⛔ tanyakan ke user sebelum Fase 1 selesai**. Daftar pertanyaannya ada di
§7 supaya bisa ditanyakan sekaligus.

**D1. Satu campaign `ntb`, satu scorecard berisi semua item (175 poin), varian ditentukan
dari isi percakapan.** Polanya sama dengan MUS di Cashline: item Supplement/MUS bernilai
`TIDAK_DINILAI` bila nasabah tidak setuju produk itu. Alasannya, varian baru diketahui setelah
panggilan, sedangkan campaign dipilih saat unggah. Baris campaign `ntb` sudah ada (placeholder
kosong).

**D2. Kode item: `SC_NTB_<n>` / `KB_NTB_<n>`.** Jangan memakai ulang `SC_CL_*`, karena kode
Cashline dirujuk keras di banyak tempat dan akan memicu logika verifikasi Cashline secara keliru.

**D3. Tanpa Ascend dan tanpa verifikasi.** Tidak ada Task C (card holder), tidak ada
`SC_CL_23_*`/`SC_CL_24`, tidak ada static similarity. Prompt NTB **tidak** memuat seksi
CARD HOLDER / STATIC VERIFICATION / DYNAMIC VERIFICATION / PENYELARASAN SINGKATAN ASCEND /
ADDRESS SOURCE MODE / VERIFICATION EVIDENCE ROUTING.

**D4. TMS juga tidak dijadikan syarat** *(konfirmasi)*. Kolom aplikasi NTB memang sudah ada di
`tms_cashline` (migrasi `0053`), tetapi isi TMS adalah input agent sendiri, dan nilai
`CashLine NTB` di kolom campaign TMS adalah sub-segmen **Cashline**, bukan campaign ini. Fase
awal NTB **tidak memakai data acuan apa pun**. Perbandingan "ucapan nasabah vs isian TMS2"
dicatat sebagai pekerjaan lanjutan (§8).

**D5. Struktur skor — aditif murni (scorecard 05102026).**

| Varian | Total | Lulus (90%) |
|---|---|---|
| Basic | 100 | 90 |
| Basic + Supplement | 125 | 112,5 |
| Basic + MUS | 150 | 135 |
| Basic + MUS + Supplement | 175 | 157,5 |

**Basic 100 + Supplement 25 + MUS 50**, dan bobot item Basic **sama di keempat varian**.
Scorecard 05102026 memperbaiki versi M19:
- Di *NTB + MUS*, iuran tahunan dan link microsite turun 3 → 2.
- "Informasi sertifikat via WhatsApp" naik 2,25 → 4,25 (di MUS dan MUS+Supplement).
- Total gabungan 173 → 175.

Karena itu **tidak perlu** field bobot per varian.

Catatan xlsx yang masih tersisa:
- Item OJK "Pasal 35 ayat 1.b POJK 22/2023" diberi catatan *"tidak ada di campaign NTB"* di
  sheet Supplement, tetapi tetap berbobot 2 (dan ada di script Final Confirmation Supplement).
  **Default: tetap dinilai** (ada di script).
- "Persetujuan data nasabah" diberi catatan *"tidak ada di NTB"* di sheet MUS, tetapi tetap
  berbobot 1. **Default: tetap dinilai.**
- "Lama bekerja/usaha" = Major/bobot 0 di NTB Only, Minor/0 di varian MUS. Bobotnya 0 di semua
  varian, jadi tidak dinilai.
- Sheet *NTB Only* menamai subtotal final konfirmasinya "Final Konfirmasi Basic + MUS Score",
  padahal tanpa MUS. Ini salah label; abaikan.

Cara memodelkan: tiap item punya satu `weight`. Item add-on diberi `applies_to`
(`"SUPL"` / `"MUS"`). Python menghitung `max_score` dari **tabel varian di kode**
(100 + 25·SUPL + 50·MUS), bukan dari `maximum_score` buatan LLM. Kode juga memverifikasi bahwa
jumlah bobot item yang berlaku sama dengan tabel itu (log warning bila beda).

**D6. Item bobot 0 / opsional tidak masuk scorecard.** NPWP, Tlp rumah, Telepon Kantor Ext,
Kartu kredit bank lain (+nomor), Auto Pay type/rekening, Memo, Lama bekerja/usaha, Provinsi,
Kab/Kota dan Kode Pos (rumah & kantor; terisi otomatis dari kecamatan) **tidak** dibuat item
scorecard. KB tetap mencatatnya di `conversation_phases`/catatan supaya LLM tidak menghukum
agent yang tidak menanyakannya.

**D7. Minat & varian — kunci output BARU khusus NTB**, jangan memakai ulang
`cashline_interest`/`mus_interest`, karena `scoring.max_score` akan salah hitung:
- `ntb_interest` — nasabah setuju pengajuan kartu utama (`INTERESTED` / `NOT_INTERESTED` /
  `UNCLEAR`).
- `ntb_supplement_interest` — setuju kartu tambahan (+ jumlah & nama, maksimal 4).
- `ntb_mus_interest` — setuju Mega Ultima Shield.
- `ntb_mus_eligibility` — hasil Health Declaration. Jawaban "TIDAK" → MUS dihentikan
  (sesuai script). Item MUS sesudah titik henti `TIDAK_DINILAI`, sedangkan item sebelumnya
  (penawaran, PDP, kesediaan HD) tetap dinilai.
- `ntb_variant` — **dihitung Python** dari tiga minat di atas: `BASIC` / `BASIC_SUPL` /
  `BASIC_MUS` / `BASIC_MUS_SUPL`. LLM boleh mengusulkan, tapi kode yang memutuskan.

**D8. MUS dan Supplement TIDAK wajib di NTB** *(konfirmasi)*. Aturan Bank Mega 8 Sep 2026
("rekaman valid wajib Cashline DAN MUS") hanya berlaku untuk Cashline. Di NTB, bila
nasabah menolak MUS/Supplement, kategori itu `TIDAK_DINILAI` dan skor maksimalnya turun ke
varian yang sesuai.

Bila `ntb_interest ≠ INTERESTED` (nasabah tidak setuju kartu utama), perilakunya **sama dengan
`no_product_interest` Cashline**: skor 0 / bukan rekaman penjualan. *(konfirmasi)*

**D9. Item kritis (potongan 25%) NTB** *(konfirmasi)*. Padanan `CRITICAL_ITEM_CODES` Cashline
(kesediaan waktu, verifikasi, legal statement):
- Kesediaan waktu / PDP greeting (bobot 5)
- Legal Statement Basic (Iya/Setuju)
- Legal Statement SPL — hanya bila varian memuat Supplement
- Legal Statement MUS — hanya bila varian memuat MUS
- PDP Supplement dan PDP MUS (bobot 5 dan 3, ditandai "(PDP)" di xlsx)

Item kritis bersyarat yang `TIDAK_DINILAI` **tidak** boleh memicu FAIL.

---

## 2. Fase 1 — Artefak campaign (KB, Scorecard, Prompt) — *inti permintaan*

Semua berkas di `docs/NTB/`:
- `ntb_scorecard_v1.txt`
- `ntb_kb_v1.txt`
- `prompt_ntb_v1.txt`
- `CHANGELOG_ntb.md`

Format teksnya sama dengan Cashline (array JSON berindentasi tab). Validasi dengan
`json.loads` setelah membuang trailing comma.

### 1a. Scorecard `ntb_scorecard_v1.txt`
Skema per item sama dengan Cashline:
`{category, item_code, requirement, kb_reference, weight, tolerable}`, ditambah
**`applies_to`** (opsional: `"SUPL"` / `"MUS"`; tanpa
field = semua varian). Kategori dan item **persis** mengikuti xlsx:

| # | Kategori (nama final) | Varian | Isi (dari xlsx) | Subtotal |
|---|---|---|---|---|
| 1 | `Greeting` | semua | salam 1 (YES), nama agent 2 (YES), nama Bank Mega 2 (YES), kesediaan waktu (PDP) 5 (NO) | 10 |
| 2 | `Probing` | semua | Info Promo/Discount 3 (NO), Range Limit 1 (YES), MPC Point 1 (YES) | 5 |
| 3 | `Pengisian Data Basic` | semua | 34 field berbobot >0 (lihat daftar di bawah) | 64 |
| 4 | `Pengisian Data Supplement` | SUPL | Nama Supl 2, Jenis kelamin 2, Hubungan 1, Info alamat kirim = kartu utama 1, PDP Supplement 5 — semua NO | 11 |
| 5 | `Penjelasan Mega Ultima Shield` | MUS | Premi 0,68% 3, Benefit 4,5, Simulasi premi 3, PDP MUS 3, Kesediaan HD 3, Penyampaian HD 5, Konfirmasi HD 3 — semua NO | 24,5 |
| 6 | `Final Konfirmasi Basic` | semua | Hari/Tanggal 2, Nama CH 2, Iuran tahunan 2, Persetujuan ditentukan analyst 1, Info aktivasi kartu 1, Alamat pengiriman kartu 2, Info dikirim link microsite 2 | 12 |
| 7 | `Final Konfirmasi Supplement` | SUPL | Konfirmasi Nama SPL 2, Hubungan SPL 2, Limit sharing 2, Billing jadi satu 1, Info OJK POJK 22/2023 2 | 9 |
| 8 | `Final Konfirmasi Mega Ultima Shield` | MUS | Info MUS produk PFI Mega Life/OJK 4, Sertifikat via WA ≤10 hari kerja 4,25, Premi tidak dapat dikembalikan 4,25, RIPLAY & sertifikat 4, Info klaim (ahli waris + 90 hari) 4 | 20,5 |
| 9 | `Legal Statement Basic` | semua | Legal Statement Basic (Iya/Setuju) 5 | 5 |
| 10 | `Legal Statement Supplement` | SUPL | Legal Statement SPL 5 | 5 |
| 11 | `Legal Statement Mega Ultima Shield` | MUS | Legal Statement MUS 5 | 5 |
| 12 | `Closing` | semua | Konfirmasi pemberian dokumen tambahan 2, Info pembicaraan direkam 2 | 4 |

Cek jumlah: Basic = 10+5+64+12+5+4 = **100** ✓. +SUPL = 11+9+5 = **25** → 125 ✓.
+MUS = 24,5+20,5+5 = **50** → 150 ✓. Gabungan = 100+25+50 = **175** ✓.
Pelaksana **wajib** menulis skrip kecil (§5) yang menghitung keempat total dari berkas
scorecard dan membandingkannya dengan tabel ini.

Catatan: xlsx menggabungkan Final Konfirmasi + Legal Statement dalam satu blok. Pemecahan ke
kategori Legal Statement terpisah mengikuti pola Cashline (dan memudahkan item kritis &
error code B18). Bobotnya tidak berubah.

**34 field Pengisian Data Basic (bobot):**
- Jenis Kartu 1, Nama Lengkap sesuai KTP 3, No KTP/Kitas 3, Kewarganegaraan 1,
  Jenis Kelamin 3, Status perkawinan 1, Tempat Lahir 3, Tanggal Lahir 3
- Alamat Rumah 1 2, Alamat Rumah 2 1, RT 2, RW 1, Kelurahan 2, Kecamatan 2
- Handphone 2, Email 1, Nama Keluarga Dekat 2, HP Keluarga Dekat 2, Nama Gadis Ibu Kandung 3
- Jabatan 2, Bidang Usaha 2, Pekerjaan 2, Nama Perusahaan 2
- Alamat Kantor 1 2, Alamat Kantor 2 1, Kantor Kelurahan 2, Kantor Kecamatan 2,
  Telepon Kantor 2
- Penghasilan Kotor/bulan 2, Alamat Pengiriman Kartu 2, Alamat Tagihan 2
- Source code 1, Persetujuan data nasabah 1, E-statement 1

Jumlahnya = 64. Hitung ulang dengan skrip. Semua NO, kecuali yang di xlsx bertanda tolerable.

**⛔ STOP sebelum menulis requirement untuk 3 item ini (§7 Q4):** "Source code" (catatan xlsx:
*by system*), "Jenis Kartu yang dikehendaki", dan "E-statement". Ketiganya mungkin dipilih agent
di sistem tanpa diucapkan. Default bila user tidak menjawab: nilai berdasarkan apakah agent
**menanyakan/menyebutkan** hal itu di panggilan. Source code: `TIDAK_DINILAI` dari transkrip
(tidak dapat dinilai dari audio).

### 1b. Knowledge Base `ntb_kb_v1.txt`
Ikuti struktur Cashline v38:
1. Objek `conversation_phases` di awal. Satu entri per kategori di 1a, dengan `description`
   yang menjelaskan kapan kategori dinilai dan aturan `TIDAK_DINILAI` per varian (salin pola
   deskripsi MUS Cashline, tapi **tanpa** aturan wajib 8 Sep).
2. Satu objek per `KB_NTB_n`: `kb_code`, `category`, `requirement`, `evidence_selection_rule`
   (`phase_scope` / `prefer` / `fallback` / `note`), `example_phrases` (diambil **verbatim** dari
   script xlsx, dipecah per kalimat), `scoring_rule` bila perlu, dan `details` untuk angka
   produk.

Konten yang wajib dibawa dari script, dengan angkanya persis:
- **Greeting:** salam sesuai jam (Pagi 08-10, Siang 10-14, Sore 14-18) — **⛔ §7 Q5**: dinilai
  ketat atau tidak (Cashline tidak). Nama lengkap nasabah, "Pusat Informasi Promo Bank Mega".
  Salin aturan multi-panggilan Greeting dari `KB_CL_1..4` (termasuk aturan `name_online` di
  `KB_CL_2`; AGENT REFERENCE DATA tetap dikirim worker untuk semua campaign).
- **Probing:**
  - Promo Transmart 10% / cicilan 0% 6 bln; dining 15–20% (Yoshinoya, Pepper Lunch, dll.);
    Agoda 8%, tiket.com, XXI.
  - MPC tiap kelipatan Rp10.000; cicilan hingga 48 bulan.
  - **Program Cashback NTB** (100% maks Rp15rb/trx, 3×, total Rp45rb, Ride-hailing & Digital
    Subscription, transaksi pertama ≤30 hari, periode 3 bulan, dikreditkan ≤30 hari sejak akhir
    bulan transaksi, tidak dapat digabung).
  - **Hartono** cicilan 0% 3/6/12 bln, min Rp1jt, s.d. 31 Des 2026, biaya konversi Rp50.000.
  - "Range Limit" — **⛔ §7 Q6**: script tidak memuat kalimat range limit sama sekali.
- **Pengisian Data:** satu KB per field, berisi definisi + contoh pertanyaan agent + aturan
  "SESUAI bila agent menanyakan ATAU nasabah menyebutkan nilainya dan agent mengonfirmasi".
  Catatan khusus:
  - Alamat Rumah/Kantor 2 boleh "titik" bila cukup di alamat 1.
  - Handphone wajib ditanyakan kembali nomor aktif.
  - Field bobot 0 dicantumkan sebagai *informational* (tidak dinilai).
- **Supplement:** maksimal 4 nama; field supplement di gambar script (Full name KTP, NIK, Tgl
  lahir, Jenis kelamin, HP, Hubungan, Email, Ibu kandung supl, Pembatasan limit opsional).
  Alamat kirim sama dengan kartu utama. PDP Supplement wajib dijawab "YA/SETUJU".
  - **Cashback kartu tambahan Rp75.000** (min akumulasi Rp1jt/30 hari, per kartu, maks 4) hanya
    ditawarkan bila nasabah tidak setuju supplement di awal. Masukkan sebagai *informational*
    (tidak ada item scorecard). Catat bahwa periode penawaran di script "1 Mar – 31 Agu 2026"
    sudah lewat (§7 Q7).
- **MUS:** PT PFI Mega Life Insurance; premi 0,68%/bulan dari total tagihan terhutang; contoh
  Rp1jt → Rp6.800. Manfaat: meninggal kecelakaan 500% / sakit 200%, cacat tetap total 100%,
  cacat sebagian 10% min Rp50rb selama 12 bln, penyakit kritis 100% (5 penyakit).
  - PDP MUS (data diteruskan ke PFI Mega Life); Health Declaration 3 poin (poin ke-3 khusus
    wanita hamil >7 bln). Jawaban TIDAK → MUS berhenti, kartu tetap diproses.
  - Final MUS: bukan produk Bank Mega, sertifikat via WA ≤10 hari kerja, hardcopy di PFI, premi
    tidak dapat dikembalikan, RIPLAY via email / www.pfimegalife.co.id, klaim maks 90 hari
    kalender.
  - Bila MUS Cashline (v38 `KB_CL_17..22, 33..38, 43`) punya `scoring_rule` yang sudah terbukti
    di lapangan untuk konsep yang **sama**, adaptasi teksnya, tapi ganti semua rujukan
    "Cashline" dan hapus aturan wajib/exemption 8 Sep.
- **Final Konfirmasi:** 4 varian teks script. Iuran tahunan gratis tahun pertama, Rp500rb–1jt.
  Jenis & limit ditentukan analisa internal. Aktivasi via Welcome Pack. Mega Call 08041500010.
  - **Syarat "blok recap":** adaptasi dari deskripsi `Final Konfirmasi Mega Cashline` v38 —
    pembuka "saya konfirmasikan pada hari ini" + minimal dua unsur recap. Pertahankan
    peringatan multi-panggilan (pilih panggilan terakhir yang **punya** recap).
- **Legal statement:** jawaban eksplisit "YA"/"SETUJU" dari nasabah.
- **Closing:** konfirmasi dokumen tambahan (WA resmi + telepon), "pembicaraan ini direkam".
  M-SMILE dan website **opsional** (tidak dinilai).
- **Handling objection** (proses ulang, MUS, premi, pembatalan, klaim, SLA polis 10 hari):
  masukkan sebagai referensi *informational* agar LLM tidak menganggapnya penyimpangan.

### 1c. Prompt `prompt_ntb_v1.txt`
Mulai dari salinan `docs/prompt_cashline_mus_v82.txt`. **Pertahankan** seksi generik yang sudah
teruji di lapangan, **hapus** seksi khusus Cashline/Ascend, dan **tulis ulang** seksi yang
bergantung produk.

| Seksi v82 (baris) | Tindakan |
|---|---|
| INPUT SCHEMA, SPEAKER LABEL, MULTI-CALL, tag `[Pn]` (1-100) | **Pertahankan**; ganti contoh `KB_CL_4` → `KB_NTB_<kesediaan waktu>` |
| OBJECTIVE, EVALUATION RULES, CONTEXTUAL COMPLIANCE (101-197) | Pertahankan; ganti pengecualian MUS (`5. EXCEPTION`) dengan aturan varian NTB |
| VERIFICATION → SCORECARD PROPAGATION (199-269) | **Hapus** |
| CASHLINE VERIFICATION → SCORECARD PROPAGATION (271-326) | **Hapus** |
| ERROR CODE CLASSIFICATION / EVIDENCE RULE (327-516) | Pertahankan kerangka; ganti nama kategori → B10/B12/B18 sesuai mapping NTB (Fase 3), hapus B02/B03/B05/B15/B16/B17 (tidak ada data acuan/verifikasi) |
| CRITICAL COMPLIANCE CHECK (517-571) | Tulis ulang dengan item kritis D9 |
| BADWORD DETECTION (572-707) | Pertahankan |
| GLOBAL EVIDENCE ORDERING, EVIDENCE EXTRACTION RULES (708-991) | Pertahankan; ganti contoh Cashline (no. 7 Penjelasan vs Final Konfirmasi) dengan padanan NTB (Probing/Penjelasan MUS vs Final Konfirmasi) |
| SCORECARD REASON RULE, POINT OF IMPROVEMENT (992-1133) | Pertahankan |
| CUSTOMER INTEREST RULE, MUS EXEMPTION, MUS SCORECARD CONDITIONAL, CAMPAIGN INTEREST EXTRACTION/VERIFICATION (1134-1458) | **Tulis ulang** menjadi `ntb_interest`, `ntb_supplement_interest`, `ntb_mus_interest`, `ntb_mus_eligibility` + **NTB VARIANT CONDITIONAL RULE** (item `applies_to` → `TIDAK_DINILAI` bila produknya tidak disetujui; HD = TIDAK → item MUS sesudahnya `TIDAK_DINILAI`) |
| SCORING RULE (1459-1531) | Tulis ulang: tabel varian 100/125/150/175 (aditif), `applies_to`, passing 90% |
| DYNAMIC VERIFICATION, B15 DISCLOSURE, VERIFICATION ROUTING, ADDRESS SOURCE MODE (1532-1752) | **Hapus** |
| STRUCTURED DATA EXTRACTION (1764-1849) | Pertahankan `agent_name_said` dan field umum; **ganti** isi dengan blok baru `ntb_application_extraction` (nilai yang disebut di panggilan untuk 34 field basic + field supplement; `null` bila tidak disebut). Hanya untuk tampilan QC, **tanpa** verifikasi/perbandingan |
| DATA EXTRACTION & REFERENCE VERIFICATION (1850-3081) | **Hapus**, kecuali sub-seksi VALUE-ONLY EXTRACTION dan NUMBER & DATE NORMALIZATION (1856-1933) yang dipindah ke blok ekstraksi NTB |
| DYNAMIC PARAM MAP, VERIFICATION ITEM SCORING (3082-3192) | **Hapus** |
| AI SCORE VERIFICATION / PHASE 3 / AI STATUS (3193-3258) | Pertahankan rumus; hapus komponen verifikasi |
| OUTPUT FORMAT (3259-3456) | Tulis ulang: hapus `cashline_*`, `card_holder_*`, `mus_exemption`; tambah kunci D7 + `ntb_application_extraction`; `scorecard_result` sama persis skemanya |
| OUTPUT ORDER ENFORCEMENT, PERFORMANCE SAFETY (3457-3547) | Pertahankan; sesuaikan daftar kunci |

Aturan untuk pelaksana:
- **Jangan menulis ulang** seksi yang dipertahankan. Setiap aturan di sana lahir dari tiket
  nyata (lihat tanggal & ID tiket di teks); cukup ganti rujukan kode/kategori.
- **Grep akhir wajib kosong** di prompt & KB NTB:
  `grep -nE "SC_CL_|KB_CL_|Cashline|cashline|Ascend|ascend|card_holder|tms_|SC_CL_24|verifikasi dinamis"`.
  Pengecualian yang disengaja ditulis di CHANGELOG.
- Target ukuran prompt jauh di bawah v82 (196 KB). Seksi verifikasi/ekstraksi Cashline ≈ 60%
  dari isinya.

**Kriteria selesai Fase 1:**
- Ketiga berkas valid JSON/teks.
- Skrip cek total menghasilkan 100/125/150/175, dan tiap item cocok dengan sheet xlsx 05102026 yang relevan.
- Setiap `kb_reference` di scorecard ada di KB, dan sebaliknya.
- Grep di atas bersih.
- `CHANGELOG_ntb.md` mencatat: sumber, keputusan D1–D9, jawaban §7, inkonsistensi xlsx.

---

## 3. Fase 2 — Penanda campaign & gerbang data acuan

Tujuannya, NTB bisa melewati worker **tanpa mengubah perilaku Cashline**.

1. Buat `core/compliance/campaign_profile.py` — registry profil per campaign (dicocokkan
   **case-insensitive** pada nama campaign):
   ```
   CampaignProfile(
     key, item_prefix ("SC_CL_" | "SC_NTB_"),
     requires_tms: bool, requires_ascend: bool,
     critical_item_codes: tuple, category_error_codes: dict,
     mandatory_pass2_codes: tuple, max_score_fn, no_interest_fn,
   )
   ```
   - Profil `cashline`: isi persis dari konstanta yang ada sekarang (pindahkan/rujuk, jangan
     salin nilai berbeda).
   - Profil `ntb`: `requires_tms=False`, `requires_ascend=False`.
   - Campaign tak dikenal → profil cashline (perilaku hari ini).
2. `worker/tasks/process_transcript.py:416-464`: `required_keys` dan daftar `kurang` hanya
   memeriksa TMS/Ascend bila profil memintanya. Untuk NTB, `build_reference_data` tetap boleh
   dipanggil (AGENT REFERENCE DATA `name_online` dibutuhkan), tapi blok CASHLINE / CARD HOLDER /
   TNC jangan dikirim. Cara termudah: tambah parameter ke `reference_data.build_reference_data`.
   Verifikasi di kode dulu, termasuk bahwa RIPLAY (`riplay.py`) tidak menyentuh NTB.
3. `stats_aggregate.data_gap_map` + `_result_ai_status` dan `api/routers/stats.py:850-871`: jangan
   menandai `DATA_GAP_TMS`/`DATA_GAP_ASCEND` untuk tiket yang profilnya tidak memerlukan.
   Periksa juga `_missing_docs_map` (pemicu NPWP ≥50jt dari limit Ascend) dan
   `GET /campaign_readiness` (cek TMS di `campaign.py:322-412`).
4. `recording_validation.py:68` `_PRODUK` (penanda Legal Statement untuk memilih rekaman utama
   multi-PDF): tambahkan pola NTB ("kartu kredit", "kartu tambahan", "ultima shield").
   Periksa dulu apakah memang perlu.

**Kriteria selesai:**
- Unit test: profil `ntb` → tidak PENDING karena data acuan.
- Profil `cashline` → gerbang identik dengan sebelumnya. Test harus menunjukkan tiket cashline
  tanpa Ascend **tetap** PENDING.

---

## 4. Fase 3 — Skor, item kritis, error code (sesudah LLM)

1. `scoring.max_score`: delegasikan ke `profile.max_score_fn`.
   - Cashline = fungsi lama, tanpa perubahan.
   - NTB = tabel varian D5 dari `ntb_variant`, yang dihitung di fungsi baru
     `ntb_variant(evaluation)` dari kunci D7. Stempel `ntb_variant` ke evaluasi (seperti
     `mus_exemption.stamp`).
2. `scoring.no_product_interest`: NTB → `ntb_interest` bukan `INTERESTED`.
3. `is_mus_item` / `BASE_MUS_CATEGORIES` / `mus_wajib_tidak_dipenuhi`: pastikan tidak pernah
   aktif untuk NTB. Kategori MUS NTB bernama sama dengan Cashline
   ("Penjelasan Mega Ultima Shield", "Final Konfirmasi Mega Ultima Shield", "Legal Statement
   Mega Ultima Shield"), jadi **cek setiap pemakai** `is_mus_item`.
4. **Penjaga varian deterministik** (baru, khusus NTB): setelah LLM, item dengan
   `applies_to` yang tidak cocok varian → paksa `TIDAK_DINILAI`. Item yang cocok tapi
   `TIDAK_DINILAI` tanpa alasan HD → log warning (jangan diubah). Bobot tiap item
   disetel ulang dari scorecard, karena LLM tidak dapat diandalkan menyalin bobot yang benar.
5. `CRITICAL_ITEM_CODES` → `profile.critical_item_codes`. Pemakai: `scoring.py:337,374`,
   `two_pass.py:387`, `error_codes._sync_critical_compliance` (`:3485-3584`, yang
   **menyuntikkan** entri kritis yang hilang; jangan suntikkan item kritis bersyarat bila
   variannya tidak berlaku).
6. `CATEGORY_ERROR_CODES` → `profile.category_error_codes`. **⛔ mapping NTB perlu
   dikonfirmasi (§7 Q8).** Usulan:
   - `Greeting` → B12
   - `Probing`, `Pengisian Data *`, `Penjelasan MUS`, `Final Konfirmasi *`, `Closing` → B10
   - `Legal Statement *` → B18

   Tambahkan A08/B24/B25/B27 ke `ALLOWED_ERROR_CODES` hanya bila user setuju.
7. `ITEM_CODE_RE` (`error_codes.py:380-407`): perluas agar mengenali `SC_NTB_`.
8. `two_pass.MANDATORY_PASS2_CODES` / `FALLBACK_AWARE_CATEGORIES` dan `parallel_pass` (merge
   blok `cashline_*`): tentukan padanan NTB (item Final Konfirmasi/Legal Statement NTB) dan cara
   menggabungkan blok `ntb_*` antar rekaman. Ikuti pola yang sama.
9. `call_ownership.stamp_agent_name_reason` (B29, `SC_CL_2`): arahkan ke item "nama agent" NTB
   lewat profil.
10. `documents.py` (dokumen dari `cashline_data_verification`, `SC_CL_13`, `SC_CL_23_*`): pastikan
    no-op untuk NTB.

**Kriteria selesai:**
- Test `max_score` NTB untuk 4 varian (100/125/150/175) dan passing grade (90/112,5/135/157,5).
- Test potongan kritis bersyarat.
- **Uji regresi Cashline**: hitung ulang skor tersimpan semua 54 tiket cashline (tanpa LLM:
  `two_pass.resync_scores` / error code dari evaluasi tersimpan) sebelum dan sesudah
  perubahan. Hasilnya harus **identik byte-per-byte**.

---

## 5. Fase 4 — Dashboard

`dashboard/src/components/EvaluationView.vue` dan modal terkait. Kirim profil dari API
(mis. `campaign_profile` di `/result/{id}`) supaya frontend tidak menebak dari nama.
- Panel minat (`:663-682`): untuk NTB tampilkan Kartu Utama / Supplement / MUS (+ HD) dan
  **varian**.
- `maxScoreBreakdown` (`:1262-1351`): NTB → "Basic 100 + Supplement 25 + MUS 50".
- `MUS_CATEGORIES`, `CATEGORY_ERROR_CODES`, `VERIF_ITEM_CODES`: ambil dari profil. Tabel
  verifikasi Cashline/Card Holder **disembunyikan** untuk NTB.
- Tab `cashline_verification` di `ResultsView.vue:1597`: sembunyikan untuk NTB. Ganti dengan
  tabel read-only `ntb_application_extraction` (field → nilai yang disebut di panggilan).
- Modal `AddErrorCodeModal`, `ErrorCodeReviewModal`, `CardHolderManualCheckModal`,
  `DocumentsSection`: pastikan tidak error untuk tiket tanpa blok cashline/card holder.

**Kriteria selesai:** `npx vite build` bersih. Halaman evaluasi tiket NTB dummy (Fase 5)
tampil tanpa error konsol. Tiket cashline tidak berubah tampilannya (cek 2–3 tiket).

---

## 6. Fase 5 — Unggah & validasi

1. Unggah lewat Admin → Upload Campaign (`POST /upload_detail_campaign`) ke campaign `ntb`.
   **Tanpa RIPLAY.** Simpan salinan versi di `docs/NTB/` (sudah di Fase 1).
2. Restart `api worker` (perubahan `core/compliance/*`), lalu `POST /stats/refresh`.
3. **Data uji:** DB saat ini **tidak punya satu pun rekaman NTB**. ⛔ Minta user menyediakan
   ≥5 rekaman/transkrip NTB nyata yang mencakup keempat varian, termasuk minimal satu kasus HD
   = TIDAK dan satu kasus nasabah menolak.
   - Jangan membuat transkrip palsu untuk menilai mutu prompt.
   - Transkrip sintetis **boleh** dipakai hanya untuk smoke test pipeline (Fase 2–4), dan harus
     ditandai jelas sebagai sintetis.
4. Untuk tiap rekaman nyata: proses, lalu bandingkan dengan penilaian QC manusia bila ada
   (sheet scorecard xlsx diberi nama agent "Axel-M07-Dhea-M20", jadi kemungkinan ada hasil QC
   manual). Catat selisih per item di `docs/NTB/validation_v1.md`.
5. Iterasi prompt/KB → `v2`, `v3`, …, masing-masing dengan entri CHANGELOG. Tiap perubahan
   aturan disertai ID tiket penyebabnya, seperti kebiasaan di prompt Cashline.

---

## 7. Pertanyaan untuk user / Bank Mega (tanyakan sekaligus, sebelum Fase 1 final)

1. ~~Total gabungan 173 atau 175?~~ **Terjawab 5 Okt 2026:** scorecard 05102026 → aditif
   100 + 25 + 50 = 175.
2. **MUS / Supplement opsional** di NTB (D8)? Dan nasabah yang menolak kartu utama → skor 0?
3. **Item kritis** NTB (D9) sudah sesuai?
4. **Source code, Jenis kartu, E-statement**: dinilai dari ucapan agent, atau di luar
   jangkauan audio (`TIDAK_DINILAI`)?
5. **Salam sesuai jam** (Pagi/Siang/Sore) dinilai ketat?
6. **Range Limit** (Probing, bobot 1): kalimat apa yang diharapkan? Tidak ada di script.
7. **Periode program** di script (cashback supplement "1 Mar – 31 Agu 2026", tiket.com
   "s.d 31 Agustus 2025") sudah lewat. Apakah KB tetap memakai angka ini atau ada versi script
   yang lebih baru?
8. **Mapping error code** kategori NTB (Fase 3.6) dan apakah A08/B24/B25 perlu diaktifkan.
9. **TMS** (D4): apakah nanti ada ekspor TMS2 untuk NTB yang ingin dibandingkan (pekerjaan
   lanjutan), atau NTB murni dari transkrip?
10. **Data uji**: dari mana rekaman NTB dan hasil QC manualnya bisa didapat?

---

## 8. Di luar cakupan (pekerjaan lanjutan)

- Verifikasi isian TMS2 vs ucapan nasabah (bila Q9 = ya): padanan Task B Cashline memakai
  kolom NTB di `tms_cashline` (migrasi `0053`).
- Campaign kartu lain yang berbagi pola (Supplement standalone, Reinstate, Activation) bisa
  memakai `campaign_profile` yang sama.
- Statistik/PPT Error Rate: `ntb` sudah ada di `_CAMPAIGN_LABELS` dan grup CARD
  (`api/routers/stats.py:1372-1435`). Cek ulang setelah ada data.

---

## Lampiran A — Dump teks xlsx

```bash
cd docs/NTB && python3 - <<'EOF'
import openpyxl
for f in ["Script NTB Okt 26.xlsx","Score Card NTB_Supplement_MUS 05102026.xlsx"]:
    wb = openpyxl.load_workbook(f, data_only=True)
    print("=====", f)
    for ws in wb.worksheets:
        print("\n##### SHEET:", ws.title)
        for row in ws.iter_rows():
            cells = [(c.coordinate, c.value) for c in row if c.value is not None]
            if cells: print(" | ".join(f"{k}: {str(v).strip()}" for k, v in cells))
EOF
```

Tabel field Pengisian Data & Supplement ada sebagai **gambar** di sheet `Probing`, dan form TMS2
ada sebagai gambar di sheet `Tampilan TMS2`. Ekstrak dengan `ws._images` (`im._data()`), lalu
baca gambarnya.

## Lampiran B — Pembagian kerja Opus / Sonnet

- **Sonnet (pelaksana):** Fase 1–5 sesuai urutan, termasuk skrip cek, test, dan uji regresi.
- **Opus (review):** review akhir Fase 1 (KB/prompt, terutama aturan varian & recap), review
  diff Fase 3 sebelum merge, dan analisis selisih di `validation_v1.md`.
- **Commit:** satu commit per fase, di branch baru dari `cashline_mus` (mis. `campaign_ntb`).
  Jangan push sebelum uji regresi Cashline Fase 3 lulus.
