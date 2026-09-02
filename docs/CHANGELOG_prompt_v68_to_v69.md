# CHANGELOG prompt_cashline_mus v68 -> v69

**Tanggal:** 28 Agustus 2026
**Cakupan:** satu aturan saja — pencocokan `alamat_kantor`, `alamat_rumah`,
`alamat_pengiriman_tagihan` pada `card_holder_verification`.

## Ringkasan

Aturan ADDRESS diganti dari **CONTAINMENT/SUBSTRING + Levenshtein** menjadi
**TOKEN COVERAGE**. Tidak ada bagian prompt lain yang disentuh.

## Kenapa

Penelusuran 3 tiket (`020354Sy0q`, `180936d7F2`, `200441mo6r`, total 6 field alamat)
menemukan aturan lama menjatuhkan MISMATCH pada alamat yang dibacakan agent dengan
benar dan lengkap:

| Tiket | Field | Levenshtein lama | Sebab gagal |
|---|---|---:|---|
| 200441mo6r | rumah | 78% | hanya kode pos yang tidak diucapkan |
| 200441mo6r | kantor | 79% | Ascend `CIMEUNYAN` vs transkrip `Cimenyan` — beda satu huruf |

Tiga penyebab struktural yang berulang:

1. **Kode pos ada di acuan tapi tidak pernah dibacakan** (6 dari 6 field).
   Sendirian saja ini sudah mematahkan aturan substring.
2. **Substring menuntut kecocokan persis.** Beda satu huruf (`Cimeunyan`/`Cimenyan`)
   atau satu varian ejaan (`Jendral`/`Jenderal`) langsung menjatuhkan field ke
   Levenshtein — yang atas string panjang selalu bernilai rendah.
3. **Singkatan alamat tidak dinormalkan** (`jl`/`jalan`, `no`/`nomor`, `RT 003`/`RT 3`).
   Diuji tersendiri: memperbaiki ini saja TIDAK menolong satu pun dari 6 field —
   perlu, tapi tidak cukup.

## Perubahannya

Blok `- ADDRESS (...)` di FIELD-SPECIFIC MATCHING RULES, dan blok `- EXCEPTION (...)`
di bagian ambang 80%.

Alur baru:

1. Tokenisasi kedua sisi (tanda baca jadi spasi).
2. Normalisasi token: singkatan alamat, nol di depan RT/RW, angka-sebagai-kata.
3. **Buang token angka 5 digit (kode pos) dari kedua sisi.**
4. Padanan token boleh beda satu-dua huruf.
5. Hitung dua arah:
   - `COVERAGE` = % token ACUAN yang terucap -> ditulis ke `similarity_percent`
   - `BALIK` = % token UCAPAN yang ada di acuan -> tidak ditulis, hanya pengaman
6. **MATCH bila COVERAGE >= 85 DAN BALIK >= 60**, selain itu MISMATCH.
7. `reason` wajib menyebut bagian alamat mana yang tidak terucap.

`BALIK >= 60` menahan kasus nasabah membacakan alamat LAIN yang kebetulan memuat
seluruh acuan (mis. menyebut alamat lama lalu alamat baru) — alamat benar yang
diucapkan ringkas tidak pernah tertahan di sini.

## Kalibrasi

Dijalankan atas 6 field dari 3 tiket di atas:

| Tiket | Field | COVERAGE | BALIK | Vonis baru | Vonis lama |
|---|---|---:|---:|---|---|
| 200441mo6r | rumah | 100% | 83% | **MATCH** | MISMATCH (78%) |
| 200441mo6r | kantor | 100% | 100% | **MATCH** | MISMATCH (79%) |
| 180936d7F2 | kantor | 75% | 100% | MISMATCH | MISMATCH (76%) |
| 020354Sy0q | rumah | 75% | 60% | MISMATCH | MISMATCH (71%) |
| 180936d7F2 | rumah | 43% | 56% | MISMATCH | MISMATCH (60%) |
| 020354Sy0q | kantor | 27% | 67% | MISMATCH | MISMATCH (54%) |

Dua false positive hilang; empat temuan yang sah tetap tertangkap.

Catatan: `180936d7F2` alamat_rumah tetap MISMATCH karena VTT merusak transkripnya
(`JL T NYAK ARIEF COMP AWAK` terbaca "Jalan Teknik Arifom"). Ini batas VTT, bukan
batas aturan pencocokan — perlu dengar audio untuk memastikan agent salah atau tidak.

## Dampak operasional

- Error code **B02 (verifikasi data)** pada ketiga field alamat akan berkurang.
- MISMATCH alamat yang tersisa sekarang lebih bisa dipertanggungjawabkan: `reason`
  menyebut bagian alamat mana yang dilewati.
- Tiket LAMA tidak berubah — prompt hanya berlaku untuk evaluasi baru. Tiket lama
  perlu di-Reprocess kalau mau memakai aturan ini.
