# CHANGELOG — Campaign NTB

## v1 — 5 Oktober 2026 (Fase 1, dikerjakan Sonnet 5.5)

Artefak baru di `docs/NTB/`:

| Berkas | Isi | Ukuran |
|---|---|---|
| `ntb_scorecard_v1.txt` | 75 item, 12 kategori, JSON valid | 17 KB |
| `ntb_kb_v1.txt` | `conversation_phases` + 75 item `KB_NTB_n`, JSON valid | 119 KB |
| `prompt_ntb_v1.txt` | prompt NTB (turunan `prompt_cashline_mus_v82.txt`) | 73 KB (v82: 196 KB) |
| `check_ntb_artifacts.py` | skrip cek konsistensi (jalankan setelah setiap edit) | — |

**Sumber:** `Score Card NTB_Supplement_MUS 05102026.xlsx` (berlaku), `Script NTB Okt 26.xlsx`.
**Acuan format/gaya:** `cashline_kb_v38.txt`, `cashline_scorecard_v31.txt`, `prompt_cashline_mus_v82.txt`.
Tidak ada perubahan backend, dashboard, maupun unggah campaign (itu Fase 2–5).

### Hasil pemeriksaan (`python3 docs/NTB/check_ntb_artifacts.py --xlsx`) — semua lulus
- 75 `item_code` unik; `kb_reference` ↔ `kb_code` 1:1 dan bernomor sama (`SC_NTB_n` ↔ `KB_NTB_n`).
- Subtotal 12 kategori sama dengan xlsx.
- Total varian: **Basic 100 / +Supplement 125 / +MUS 150 / +MUS+Supplement 175**; lulus 90/112,5/135/157,5.
- Total tiap varian sama dengan `Total Score` tiap sheet xlsx, dan jumlah bobot baris item xlsx sama dengan totalnya.
- 6 item kritis ada di scorecard dan disebut di prompt; semua kode `SC_NTB_`/`KB_NTB_` yang dirujuk prompt ada.
- KB dan prompt bebas `SC_CL_|KB_CL_|Cashline|Ascend|card_holder|tms_|verifikasi dinamis` (0 temuan; tanpa pengecualian).

### Struktur scorecard
- Skema item: `{category, item_code, requirement, kb_reference, weight, tolerable}` + **`applies_to`** opsional
  (`"SUPL"` / `"MUS"`; tanpa field = semua varian). Tidak ada `weight_by_variant` (tidak diperlukan sejak
  scorecard 05102026 aditif murni).
- Penomoran: Greeting 1–4 · Probing 5–7 · Pengisian Data Basic 8–41 · Pengisian Data Supplement 42–46 ·
  Penjelasan MUS 47–53 · Final Konfirmasi Basic 54–60 · Final Konfirmasi Supplement 61–65 ·
  Final Konfirmasi MUS 66–70 · Legal Basic 71 / Supplement 72 / MUS 73 · Closing 74–75.
- Item bobot 0 / opsional xlsx **tidak** dibuat item (NPWP, telepon rumah, ext. telepon kantor, lama bekerja,
  Provinsi/Kab-Kota/Kode Pos, kartu kredit bank lain, auto pay, memo); dicatat sebagai informasional di KB.
- Item kritis (potongan 25% per FAIL): `SC_NTB_4`, `71`, serta `46`/`72` (hanya bila SUPL) dan `50`/`73` (hanya bila MUS).

### Item KB yang diadaptasi dari KB Cashline v38 (logika sudah teruji di lapangan; rujukan Cashline dibuang)
`KB_NTB_2` ← KB_CL_2 (aturan `name_online`/`agent_name_said`, B12 vs B29) · `KB_NTB_4` ← KB_CL_4 (kesediaan waktu) ·
`KB_NTB_1–4` catatan multi-panggilan Greeting · `KB_NTB_47` ← KB_CL_17 · `KB_NTB_48` ← KB_CL_21 ·
`KB_NTB_51–53` ← KB_CL_18/19/20 (blok Health Declaration yang menyatu) · `KB_NTB_67` ← KB_CL_34 ·
`KB_NTB_68` ← KB_CL_43 · `KB_NTB_69` ← KB_CL_22 · `KB_NTB_70` ← KB_CL_35 · `KB_NTB_71/72/73` ← KB_CL_37/38
(persetujuan eksplisit + jawaban afirmatif nasabah). Kutipan tiket nyata Cashline pada `scoring_rule` asal **tidak** dibawa.

---

## Asumsi menunggu konfirmasi Bank Mega

Setiap baris = default dari `plan.md` yang dipakai karena jawaban belum ada. Ubah di sini bila jawaban berbeda.

| # | Pertanyaan plan §7 | Asumsi v1 | Letak | Risiko bila salah |
|---|---|---|---|---|
| Q2 | MUS/Supplement opsional? Tolak kartu utama? | MUS dan Supplement **opsional**. Nasabah tidak setuju kartu utama → **skor 0, FAIL** (ZERO-SCORE RULE, sama pola Cashline). | prompt: NTB VARIANT, SCORING RULE | Bila MUS ternyata wajib, perlu aturan "tidak valid" seperti Cashline 8 Sep. |
| Q3 | Item kritis | `SC_NTB_4, 71, 46, 72, 50, 73` (waktu, 3 Legal Statement, 2 PDP). | prompt: CRITICAL COMPLIANCE CHECK, AI SCORE PHASE 3 | Potongan sampai 6 × (max/4) — sangat berat; tinjau ulang dengan Bank Mega. |
| Q4a | Source code | `SC_NTB_39` **selalu `TIDAK_DINILAI`** ("by system"). Bobot 1 ikut penyebut `maximum_score` sehingga jadi 1 poin gratis. | KB_NTB_39 | Kecil. |
| Q4b | Jenis kartu, E-statement | Dinilai dari ucapan agent. Script **tidak memuat kalimat baku** keduanya; contoh frasa di KB adalah **rekaan**. | KB_NTB_8, KB_NTB_41 | **Tinggi**: keduanya `tolerable=NO` → bila agent tidak menyinggung, tiket FAIL lewat veto non-tolerable. Disarankan dicek di data nyata. |
| Q5 | Salam sesuai jam | **Tidak** dinilai ketat (sama seperti Cashline). Jam hanya informasi. | KB_NTB_1 | Bila ketat, tambahkan syarat jam di `scoring_rule`. |
| Q6 | Range Limit | Script tidak memuat kalimatnya. Diasumsikan: agent menyebut kisaran/rentang limit kartu. Contoh frasa rekaan. | KB_NTB_6 | Kecil (bobot 1, tolerable YES). |
| Q7 | Periode promo lewat | KB memuat angka apa adanya dari script; `catatan_periode` di `KB_NTB_5` menyatakan yang dinilai adalah **disampaikannya** promo, bukan masa berlakunya. Cashback kartu tambahan Rp75.000 (1 Mar–31 Agu 2026) **tidak** dijadikan item (informasional dan sudah lewat). | KB_NTB_5 | Bila script baru menambah promo, perbarui `details`. |
| — | Alamat pengiriman kartu pada Final Konfirmasi | Script Final Confirmation **tidak** memuat kalimat ini, tapi scorecard memintanya. Diasumsikan agent mengulang alamat pengiriman di dalam/tepat sebelum blok konfirmasi akhir. | KB_NTB_59 | Sedang: bisa BELUM_SESUAI massal. |
| — | Info OJK POJK 22/2023 | Catatan xlsx "tidak ada di campaign NTB", tapi bobot 2 dan kalimat ada di script Supplement. **Tetap dinilai** (hanya bila SUPL). | KB_NTB_65 | Kecil. |
| — | Persetujuan data nasabah | Catatan xlsx "tidak ada di NTB" (sheet MUS) tapi bobot 1 dan ada di script (Persetujuan Sharing Data). **Tetap dinilai**; nasabah boleh menolak, yang dinilai agent meminta. | KB_NTB_40 | Kecil. |
| — | Hari/tanggal konfirmasi | Wajib nama hari + tanggal + bulan; tahun toleran (ASR). | KB_NTB_54 | Kecil. |
| — | Iuran tahunan | Wajib ketiga unsur (gratis tahun pertama, dikenakan tahun kedua, rentang Rp500rb–1jt) sesuai script. | KB_NTB_56 | Sedang (ketat). |
| — | Pemberitahuan rekaman | Item `SC_NTB_75` mensyaratkan disebut pada **penutup**; pemberitahuan di awal tidak menggantikan. | KB_NTB_75 | Sedang. |

---

## Penyimpangan dari `plan.md` (butuh review Opus)

1. **MUS yang tidak berlaku → SEMUA item MUS `TIDAK_DINILAI`**, termasuk item yang sempat dijelaskan agent sebelum
   nasabah menolak / berhenti di Health Declaration. `plan.md` D7 menulis "item sebelumnya (penawaran, PDP, kesediaan HD)
   tetap dinilai". Saya ubah karena `maximum_score` memakai tabel varian (Basic = 100): menilai item MUS di luar penyebut
   membuat skor bisa di bawah nol/tak konsisten dengan `phase2 = max − Σ deduksi`. Konsekuensi: agent tidak dihukum bila
   nasabah menolak MUS lebih awal. Aturan ini ada di prompt (NTB VARIANT CONDITIONAL RULE, butir 3) — **putuskan di Fase 3**
   apakah dipertahankan; bila tidak, penyebut dan deduksi MUS parsial harus dirancang ulang.
2. **Format KB**: array JSON **valid** dengan elemen pertama `{"conversation_phases": {...}}`. KB Cashline v38 memakai
   tata letak yang bukan JSON valid (`[ "conversation_phases": {...}, {...}`); tidak ada kode Python yang mem-parse KB
   untuk NTB (parser hanya di `riplay.py`, tidak dipakai NTB).
3. **Legal Statement Basic/SPL/MUS** boleh memakai **satu** pertanyaan persetujuan gabungan dengan satu jawaban
   YA/SETUJU, asalkan pertanyaannya menyebut tiap produk (script Final Confirmation memang satu blok).
4. **`SC_NTB_60` (link microsite)** satu-satunya item kategori Final Konfirmasi yang evidence-nya boleh dari segmen
   microsite yang langsung menyusul blok konfirmasi (ucapan itu letaknya di luar blok).
5. **`ntb_mus_eligibility.kategori`** ditambah nilai `MENOLAK_HD` (selain `SAKIT`/`HAMIL`) untuk nasabah yang tetap
   menolak memberi pernyataan kesehatan setelah ditanya ulang — sesuai script.
6. **B25 dan A08 tidak ada di prompt** (B25 "No HP supplement sama dengan basic" tidak bisa dipercaya dari transkrip).
   B24 dipertahankan. **B27 ditulis ulang**: aturan Cashline ("nasabah tidak punya kartu Bank Mega") akan salah
   menembak pada NTB karena nasabah NTB memang belum punya kartu.
7. **Blok `ntb_application_extraction`** (34 field + kartu tambahan) ditambahkan ke keluaran sesuai plan. Murni transkripsi,
   tanpa verifikasi. Menambah token keluaran; bisa dimatikan bila tampilan QC tidak membutuhkannya.
8. `matching_type` dan `dynamic_verification_detail` dibuang dari urutan field keluaran; `point_of_improvement`
   dimasukkan ke urutan (v82 menambahkannya di format tetapi tidak di aturan urutan).
9. **Keluaran yang dihapus dibanding v82:** `bank_name`, `disbursement_amount`, `tenor_months`, `cashline_interest`,
   `mus_interest`, `mus_exemption`, `campaign_interest_verification`, `card_holder_extraction/verification`,
   `cashline_data_extraction/verification`. **Ditambah:** `ntb_interest`, `ntb_supplement_interest`, `ntb_mus_interest`,
   `ntb_mus_eligibility`, `ntb_variant`, `ntb_application_extraction`. `campaign_interest` dipertahankan dengan nilai NTB.
   Backend/dashboard yang membaca kunci lama harus diaudit di Fase 2–4 (worker `required_keys`, `scoring.max_score`,
   `EvaluationView.vue`).
10. `ai_score_verification` dipertahankan di keluaran dengan nilai **0 selalu** (kompatibilitas bentuk).

### Bagian prompt v82
| Dipertahankan (rujukan diganti) | Dihapus | Ditulis ulang |
|---|---|---|
| INPUT SCHEMA, speaker label, multi-call, tag `[Pn]` · Objective · Contextual compliance · Interaction rule · Must-include term · Item/Category scoring · Error Code Evidence Rule · Badword Detection · Global Evidence Ordering (aturan tunggal) · Evidence Extraction 5, 5b, 5d, 6, 8, 9 · Scorecard Reason · Point of Improvement · AI Summary · Value-only & Number/Date normalization · Output Order · Performance Safety | Verification→Scorecard Propagation (kedua) · aturan bunga/provisi · Dynamic Verification · B15 Disclosure · Verification Evidence Routing · Address Source Mode · Card Holder & Cashline Data Extraction/Verification · Static Verification Matching · Fuzzy Matching/Text Similarity · Dynamic Param Map · Verification Item Scoring · Campaign Interest Verification · MUS Exemption · B02/B03/B05/B15/B16/B17 | Campaign Context · Error Code Classification · Critical Compliance Check · Segmen Final Konfirmasi (+pengecualian evidence) · Evidence 5/5c/7 · Customer Interest (3 produk + eligibility) · NTB Variant & Conditional Rule · Scoring Rule (aditif) · Structured Data Extraction · AI Score Phase 3 · Output Format |

Catatan: keterangan tanggal historis di teks yang dipertahankan (mis. "berlaku 24 Agustus 2026") adalah provenance v82,
bukan tanggal NTB.

---

## Inkonsistensi xlsx yang masih tersisa (tidak "dibetulkan")
- Catatan "dapat diisi titik-titik bila cukup menggunakan Alamat Kantor 1" menempel pada **Nama Perusahaan** di sheet
  Supplement/MUS (di sheet *NTB Only* ada di Alamat Kantor 2). Diperlakukan sebagai milik **Alamat Kantor 2**.
- Subtotal "Final Konfirmasi Basic + MUS Score" pada sheet *NTB Only* salah label (tanpa MUS); diabaikan.
- Sheet *Tampilan TMS2* hanya screenshot form (tidak dipakai di Fase 1; relevan bila nanti ada perbandingan TMS, plan §8).

## Belum dilakukan (Fase 2–5)
`campaign_profile`, gerbang data acuan, `scoring.max_score` NTB, item kritis & error code per kategori, dashboard,
unggah ke campaign `ntb`, validasi dengan rekaman nyata (DB belum punya satu pun rekaman NTB).
