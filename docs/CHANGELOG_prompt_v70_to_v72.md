# CHANGELOG prompt_cashline_mus v70 -> v71 -> v72

**Tanggal:** 28 Agustus 2026
**Cakupan:** `nama_pemilik_rekening` saja. KB tetap v34, scorecard tetap v3.

---

## v70 -> v71 — mencabut kontradiksi di dalam prompt

Prompt memuat DUA instruksi berlawanan tentang field yang sama:

| Blok | Bunyi |
|---|---|
| AMBANG KHUSUS (24 Agu) | `< 90` -> MISMATCH -> **WAJIB** minta cover buku tabungan |
| SHORT NAME (21 Agu) | "TIDAK ada zona abu-abu dan **TIDAK ada dokumen pendukung** untuk field ini" |

Kalimat 21 Agustus lupa dicabut ketika bank menambahkan permintaan cover buku
tabungan pada 24 Agustus. Yang usang itu juga bertentangan dengan sistem:
permintaan cover buku tabungan SUDAH berjalan di kode
(`compliance/documents.py`, `reference_data.py::DOC_COVER_BUKU_TABUNGAN_COLS`).

Blok SHORT NAME kini menunjuk ke AMBANG KHUSUS sebagai yang berwenang, dengan
catatan koreksi agar tidak dicabut balik. Yang tetap benar dari kalimat lama:
zona abu-abu memang TIDAK ADA di sini — di bawah 90 tetap MISMATCH dan tetap
dihukum, berbeda dari `nama_ibu_kandung`. Yang salah hanya bagian dokumennya.

---

## v71 -> v72 — penyelarasan nama TMS yang terpotong

**Masalahnya:** kolom nama pemilik rekening di TMS dibatasi lebar field, sehingga
nama panjang terpotong di ujungnya. Levenshtein bekerja huruf-per-huruf atas
seluruh string, jadi ekor yang hilang dihitung sebagai kesalahan — pada
`0110505ngB`, `"K"` vs `"Kurnadi"` saja menjatuhkan nilainya ke 67%. Yang dihukum
justru nasabah yang menyebut namanya LEBIH LENGKAP.

**Aturan barunya** mencerminkan `_align_abbreviations` yang sudah dipakai
`nama_ibu_kandung`, dengan satu penyesuaian: token TERAKHIR TMS boleh menjadi
awalan berapa pun panjangnya (di situlah kolom terpotong), sementara token tengah
tetap dibatasi <= 3 huruf. Yang dipendekkan adalah token TRANSKRIP; **nilai TMS
tidak pernah diubah**.

Langkah terakhir — **pakai nilai TERTINGGI** antara similarity biasa dan hasil
penyelarasan — membuat aturan ini SATU ARAH: hanya bisa menaikkan, tidak pernah
menurunkan.

**Ambang 90 TIDAK berubah**, dan tidak ada normalisasi fonetik (keputusan bisnis
28 Agustus 2026). Yang berubah hanya angka yang diadu ke ambang itu.

### Kalibrasi atas 97 baris nyata

| TMS | Transkrip | Lama | Baru | Vonis |
|---|---|---:|---:|---|
| DOROTA MEIANTIKO K | Dorota Meantiko Kurnadi | 67 | **94** | MISMATCH -> MATCH |
| SANDY DWI CAHYANA SO | Sandi Dwi Cahyana Sofian | 79 | **95** | MISMATCH -> MATCH |
| SHANDRA UMAYA ADRI | Sandra Umaya Adriasin | 74 | **94** | MISMATCH -> MATCH |
| RYKE CONSTAN | Rike Constanza | 79 | **92** | MISMATCH -> MATCH |
| SAMUEL ADIN NUGROHO SETI | Samuel Adinugroho Setiawan | 79 | **92** | MISMATCH -> MATCH |
| PARAMITA ADHI KURNIA | Paramitha Adi Kurniasari | 84 | **90** | MISMATCH -> MATCH |
| BAHTIAR RAHMANDA ADI PUT | Bahtiar Rahmanda Adiputra | 91 | 91 | MATCH (tetap) |
| IBU LUSINDA WEINA MARIA BO | Lusinda Wena Maria Bokong | 92 | 92 | MATCH (tetap) |
| SIM KHENG | Simkeng | 88 | 88 | MISMATCH (tetap) |

**6 pulih, 0 regresi, 0 bocor.**

Empat nama yang memang milik orang BERBEDA tidak tersentuh — tidak ada hubungan
awalan di antara tokennya, jadi penyelarasan tidak pernah terjadi:

| TMS | Transkrip | Nilai |
|---|---|---:|
| DHUHURI AL ALIF MEGANTAR | Duhuri | 25 |
| ANDREAN TISTONI | Adrian Sifoni | 64 |
| ANDI HIDA PUSPAKASIH | Andi Hida Kuswatasi | 68 |
| ZEFANIA KARIENTA CHARA | Devania Karienta Carakel | 73 |

### Yang TIDAK dikerjakan, dan kenapa

`similarity_nama()` milik `nama_ibu_kandung` sempat diuji untuk dipakai apa adanya
di field ini. **Ditolak: 9 regresi.** Fungsi itu dibangun untuk pasangan
Ascend vs ucapan nasabah, dan `_norm_name` hanya membersihkan sisi KANDIDAT —
sesuai prinsipnya "acuan Ascend tidak pernah dimanipulasi". Di sini sapaan justru
ada di sisi REFERENSI (`"SDRI RETNO WULANDARI"`, `"BPK STEFANUS..."`,
`"IBU LUSINDA..."`), sehingga tidak ikut dibersihkan dan nilainya jatuh:

| TMS | Transkrip | LLM sekarang | similarity_nama |
|---|---|---:|---:|
| SDRI SRI  WAHYUNI | Sri Wahyuni | 100 | 69 |
| SDRI RETNO  WULANDARI | Retno Wulandari | 100 | 75 |
| SDR LUIGI CREMONA LORD | LUIGI CREMONA LORD | 100 | 82 |

Karena itu yang dipindahkan hanya BAGIAN yang memang cocok — penyelarasan
awalan — bukan seluruh fungsinya.

### Yang sudah benar sejak awal (tidak perlu diubah)

Keputusan "cashline data verif GT transkrip, cardholder verif GT ascend" ternyata
sudah terpasang: prompt menetapkan acuan efektif = TRANSKRIP untuk `nama_bank` /
`nomor_rekening` / `nama_pemilik_rekening`, dan atribusinya benar di data nyata
("agent salah input ke TMS"). `nama_pemilik_rekening` juga tidak pernah muncul di
`card_holder_verification`, jadi tidak ada tabrakan aturan.

---

## Dampak operasional

- Berlaku untuk evaluasi BARU. Tiket lama perlu **Reprocess**.
- ~6 tiket akan kehilangan error code B02 pada `nama_pemilik_rekening` beserta
  penalti −2 dan permintaan cover buku tabungan.
- Variasi ejaan nama (OE/U, DH/D, KH/H) **tidak** ditangani versi ini — 13 baris
  MISMATCH sisanya berasal dari sana dan tetap MISMATCH sesuai keputusan bisnis
  untuk mempertahankan ambang 90 tanpa normalisasi fonetik.
