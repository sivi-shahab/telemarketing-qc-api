# State: Campaign NTB

Terakhir diperbarui: **5 Oktober 2026** (Fase 1 selesai, menunggu review Opus). Branch kerja: `cashline_mus`. Baru `plan.md` dan `state.md` yang di-commit
(`c3a62f1`); belum ada kode atau artefak campaign NTB.

## Posisi saat ini
- ✅ Sumber sudah dibaca dan dianalisis:
  - `Script NTB Okt 26.xlsx`
  - `Score Card NTB_Supplement_MUS 05102026.xlsx` — **scorecard yang berlaku** (4 sheet varian +
    screenshot TMS2). Versi lama (`M19 - Axel-M07-Dhea-M20`) sudah dihapus.
- ✅ Pipeline campaign dipetakan. Temuan dan lokasi kodenya ada di `plan.md` §0.
- ✅ `plan.md` ditulis. Perencana Opus, pelaksana Sonnet, Fase 1–5.
- ⏳ **Menunggu jawaban 9 pertanyaan tersisa di `plan.md` §7 (Q1 sudah terjawab)** sebelum Fase 1 final.
- ✅ **Fase 1 selesai (Sonnet, belum di-commit):** `ntb_scorecard_v1.txt` (75 item), `ntb_kb_v1.txt`, `prompt_ntb_v1.txt`,
  `CHANGELOG_ntb.md`, `check_ntb_artifacts.py`. Semua pemeriksaan lulus (total 100/125/150/175 cocok dengan xlsx; grep bersih).
- ⏳ **Review Opus atas Fase 1** — baca `CHANGELOG_ntb.md` bagian "Penyimpangan dari plan.md" (terutama butir 1: MUS tidak
  berlaku → semua item MUS TIDAK_DINILAI) dan tabel "Asumsi menunggu konfirmasi Bank Mega".
- ⬜ Fase 2–5 belum dimulai.

## Fakta kunci (jangan diulang analisisnya)
- **Tanpa Ascend:** NTB tidak dibandingkan dengan Ascend, dan tidak ada verifikasi
  statik/dinamis.
- **Backend memblokir NTB saat ini:**
  - Gerbang TMS/Ascend di `worker/tasks/process_transcript.py:422-464` membuat semua tiket NTB
    langsung PENDING.
  - `scoring.max_score` terpaku 100 (Cashline) + 50 (MUS).
  - Item kritis dan error code per kategori memakai kode/nama Cashline.
  - Detail lengkap ada di `plan.md` §0.
- **DB:**
  - Campaign `ntb` sudah ada sebagai placeholder kosong.
  - **Belum ada rekaman NTB.** Seluruh 54 result adalah `cashline`. Nilai `CashLine NTB` di
    TMS adalah sub-segmen Cashline, **bukan** campaign ini.
- **Skor NTB per varian (xlsx):**

  | Varian | Total |
  |---|---|
  | Basic | 100 |
  | +Supplement | 125 |
  | +MUS | 150 |
  | +MUS+Supplement | 175 |

  Passing grade 90% di semua varian.
- **Struktur skor aditif murni** (scorecard 05102026): **Basic 100 + Supplement 25 + MUS 50**.
  Bobot item Basic sama di keempat varian.
- **MUS maksimal = 50, sama di NTB dan Cashline, tapi komposisinya beda:**
  - Cashline: Penjelasan 20,5 + Final 14,5 + Legal Statement **15**.
  - NTB: T&C 24,5 + Final 20,5 + Legal Statement **5**.
- **Keputusan desain D1–D9** (`plan.md` §1):
  - Satu campaign, satu scorecard. Varian dibaca dari percakapan.
  - Kode `SC_NTB_*` / `KB_NTB_*`.
  - Kunci minat baru `ntb_interest`, `ntb_supplement_interest`, `ntb_mus_interest`,
    `ntb_mus_eligibility`. **Jangan** memakai `mus_interest`.
  - MUS dan Supplement opsional.
  - Registry `core/compliance/campaign_profile.py`. Perilaku Cashline wajib identik (uji
    regresi 54 tiket).

## Pertanyaan terbuka (ringkas — detail di `plan.md` §7)
1. ~~Total gabungan 173 atau 175?~~ Terjawab: 175 (scorecard 05102026).
2. MUS/Supplement opsional? Nasabah yang menolak kartu utama → skor 0?
3. Item kritis NTB.
4. Source code / Jenis kartu / E-statement: bisa dinilai dari audio?
5. Salam sesuai jam dinilai ketat?
6. Kalimat "Range Limit" (tidak ada di script).
7. Periode promo di script sudah lewat. Ada script yang lebih baru?
8. Mapping error code kategori NTB; aktifkan A08/B24/B25?
9. Nanti ada perbandingan isian TMS2?
10. Sumber rekaman NTB dan hasil QC manual untuk validasi.

## Keputusan 5 Okt 2026: lanjut Fase 1 tanpa menunggu jawaban (opsi 2)
- **Siapa:** Sonnet mengerjakan **Fase 1 saja** (KB, scorecard, prompt v1).
- **Q2–Q7:** pakai default di `plan.md`. Setiap asumsi dicatat di `CHANGELOG_ntb.md` di bawah
  judul "Asumsi menunggu konfirmasi Bank Mega", supaya mudah dikoreksi saat jawaban datang.
- **Jangan sentuh** backend, dashboard, atau upload campaign. Itu Fase 2–5.
- **Setelah Fase 1:** kembali ke Opus untuk review, terutama aturan varian, blok recap, dan
  seksi prompt yang dihapus/ditulis ulang.

## Langkah berikutnya saat dilanjutkan
0. Review Opus Fase 1 (lihat atas), lalu commit artefak Fase 1 (satu commit).
1. Isi jawaban §7 di sini (atau di `plan.md`). Sesuaikan D5/D8/D9 bila jawabannya berbeda dari
   default.
2. Jalankan Fase 1 sesuai `plan.md` §2. Mulai dari skrip dump xlsx di Lampiran A.
3. Commit per fase di branch baru (mis. `campaign_ntb`).

## Berkas di folder ini
- `Script NTB Okt 26.xlsx`, `Score Card NTB_Supplement_MUS 05102026.xlsx`: sumber dari Bank
  Mega (berlaku).
- `ntb_scorecard_v1.txt`, `ntb_kb_v1.txt`, `prompt_ntb_v1.txt`, `CHANGELOG_ntb.md`, `check_ntb_artifacts.py`: hasil Fase 1.
- `plan.md`: rencana lengkap.
- `state.md`: berkas ini.
