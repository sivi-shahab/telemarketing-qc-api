# Katalog Error Code & Efek Banding — Telemarketing QC System

Referensi lengkap **46 error code**, arti **Risk Base**, kode mana yang **berdeduksi**
(memengaruhi skor), dan bagaimana **banding (Manual Check)** mengubah error card & skor.

- Sumber katalog runtime: `compliance/error_reasons.json` (di-generate dari Excel
  `compliance/Error Reason - Telemarketing QC_05082025 (1).xlsx`; JSON = sumber kebenaran saat runtime).
- Logika penurunan & banding: `compliance/error_codes.py`.
- Endpoint katalog untuk dropdown: `GET /error_reasons`.

> Jangan tertukar dengan `ERROR_CODES` di `compliance/error_codes.py` (**18 entri** per
> 14 Agustus 2026; distribusi risk_base H=5 / M=8 / L=4 / O=1) — itu kode yang dikenali
> mesin evaluasi. **46 kode** di bawah adalah katalog master lengkap untuk dropdown banding.
>
> Dari 18 entri itu, yang benar-benar **ditampilkan** hanya 10 (`ALLOWED_ERROR_CODES`, §4);
> `B08` dan `B11/B13/B15/B19/B20/B24/B26` dikatalogkan tetapi tidak diterbitkan. Tiap entri
> juga membawa `error_type` & `error_category` dari sheet — lihat §4.1.

---

## 1. Struktur Kode

Prefix kode menentukan **jenis error**:

| Prefix | Jenis (error_type) | Contoh |
|---|---|---|
| `A00` | **Approved** (bukan error) | A00 |
| `A01`–`A15` | **Error - System** | trouble recording, data blank, dsb. |
| `B01`–`B26` | **Error - Human** | salah input, verifikasi kurang, legal statement, dsb. |
| `C01`–`C04` | **Error - Customer** | cancel by customer, dokumen buram, dsb. |

Setiap entri katalog punya field: `code`, `error_type`, `category`, `risk_base`, `campaign`, `details`.

---

## 2. Arti Risk Base

| Risk Base | Arti | Deduksi skor? |
|---|---|---|
| **Approved** | Sentinel untuk A00 (tidak ada error) | Tidak |
| **O** | *Others* — error System/Customer/typo, tanpa penalti skor | Tidak |
| **L** | *Low risk* | Hanya bila kode berdeduksi (lihat §4) |
| **M** | *Medium risk* | Hanya bila kode berdeduksi |
| **H** | *High risk* | Hanya bila kode berdeduksi |
| **H+T** | *High + Terminasi* — 3 pelanggaran terberat (Never Apply, Pemalsuan, Kutipan/Imbalan) | (tidak muncul di tabel skor; sifatnya pelanggaran berat) |
| **N** | *New joiner* — **runtime only**, bukan di katalog | Tidak (di-soften) |

> **Aturan New Joiner** (`override_risk_base_for_new_joiner`, `error_codes.py`): bila agent
> bergabung **< 18 hari** sebelum `submit_time`, kode ber-risk_base **L atau M diturunkan
> jadi N**; **H tetap H**. `NEW_JOINER_RISK_BASE = "N"`.
>
> Sejak 14 Agustus 2026 kode dokumen dikecualikan: `NEW_JOINER_EXEMPT_CODES = {"B09","C03"}`
> tetap pada Risk Base aslinya — masa kerja agent tidak mengubah tenggat H+2. Lihat §5.1.

Distribusi risk_base di katalog (46 kode): **O=20, M=10, L=7, H=5, H+T=3, Approved=1**.

---

## 3. Tabel Katalog Lengkap (46 kode)

### Approved (1)
| Code | Category | Risk | Campaign | Details |
|---|---|---|---|---|
| A00 | Approved | Approved | — | Approved (tidak ada error) |

### Error - System — A01–A15 (15, semua Risk Base `O`)
| Code | Category | Campaign | Details |
|---|---|---|---|
| A01 | System | All Campaign | Perubahan data pada CCBM < 3 bulan |
| A02 | System | All Campaign | Trouble System Recording |
| A03 | System | All Campaign | Recording Not Found |
| A04 | System | All Campaign | Data blank (System Error) |
| A05 | System | All Campaign | Kartu Blokir/XPAC setelah submit |
| A06 | System | — | Transaksi sudah terproses/Double Proses oleh channel lain |
| A07 | System | Megabill | Data sudah terdaftar di sistem Recurring |
| A08 | System | NTB/Reinstate/Add On/Supplement | Kartu tipe sama sudah dimiliki CH |
| A09 | System | — | Product Information (butuh konfirmasi Team Product) |
| A10 | System | Aktivasi | Kartu sudah/belum aktif |
| A11 | System limitation | All Campaign | Terdapat tanda baca dalam data input |
| A12 | System | All Campaign | CH tidak ada di data terundang |
| A13 | System Validation | Cashline/LOC | Salah input tanpa financial loss & agent … |
| A14 | System | — | Supplement belum dapat diproses (basic card rejected) |
| A15 | System | — | Base on CCBM ada perubahan No HP |

### Error - Human — B01–B26 (26)
| Code | Category | Risk | Campaign | Details |
|---|---|---|---|---|
| B01 | Data Input | O | — | Penulisan nama typo/kurang 1 huruf/pelafalan Inggris salah |
| **B02** | Data Input | **L** | All Campaign | Salah input data risiko **low** |
| B03 | Data Input | **M** | All Campaign | Salah input data risiko **medium** (data finansial) |
| B04 | Data Input | M | All Campaign | Tidak dilakukan pengkinian data |
| **B05** | Data Input | **H** | Cashline/LOC | Salah input data risiko **tinggi** (potensi kerugian finansial) |
| B06 | Data checking | L | All Campaign | Kartu Blokir/XPAC sebelum submit (TMS base) |
| B07 | Data checking | L | Megapay | Transaksi tidak sesuai sistem (IITH) |
| B08 | Dokumen Pendukung | L | — | Type file dokumen terlampir kurang/tidak sesuai |
| B09 | Dokumen Pendukung | M | All Campaign | Dokumen unclear/buram/expired/tidak melampirkan |
| **B10** | TnC Product | **M** | All Campaign | Inaccurate product feature/script/fee |
| B11 | TnC Product | M | All Campaign | Ketentuan pembelian product (subscription requirement) |
| B12 | Probbing | L | All Campaign | Agent tidak menyebut nama/dari Bank Mega |
| B13 | Voice Mistake | M | — | Voice mistake |
| B14 | Open Data | M | — | Open data di luar data statik namun belum verifikasi |
| B15 | Open Data | H | All Campaign | Open data yang termasuk data statik namun belum verifikasi |
| **B16** | Verification | **M** | All Campaign | Verifikasi statik berhasil, dinamik kurang/tidak … |
| **B17** | Verification | **H** | All Campaign | Tidak ada verifikasi / verifikasi statik kurang/tidak berhasil |
| B18 | Legal Statement | H | All Campaign | Tidak ada legal statement |
| B19 | Over Promise | M | — | Menjanjikan hal-hal di luar kewenangan |
| B20 | Offering bukan kepada CH | H | All Campaign | Offering bukan kepada CH |
| B21 | Never Apply | **H+T** | All Campaign | Tidak ada penawaran - Never Apply |
| B22 | Pemalsuan | **H+T** | All Campaign | Pemalsuan data dan/atau dokumen |
| B23 | Kutipan/Imbalan | **H+T** | All Campaign | Meminta/menerima imbalan/hadiah |
| B24 | TnC Product | L | — | Customer cancel supplement (crosselling) namun sudah tersubmit |
| B25 | TnC Product | L | — | No HP supplement sama dengan basic |
| B26 | Legal Statement | M | — | Legal statement bersyarat |

### Error - Customer — C01–C04 (4, semua Risk Base `O`)
| Code | Category | Campaign | Details |
|---|---|---|---|
| C01 | Cancel by Customer | — | Customer cancel sesudah tutup telpon |
| C02 | Pemakaian Limit | Cashline/LOC | Perubahan available limit karena pemakaian |
| C03 | Dokumen Pendukung | All Campaign TMS2 | Dokumen unclear/buram/expired |
| C04 | Informasi Customer | — | Microsite tidak sesuai ketentuan |

> Kode **bold** (B02, B03, B05, B10, B16, B17) adalah **kode berdeduksi** — lihat §4.

---

## 4. Kode Berdeduksi (memengaruhi skor)

Hanya sebagian kode yang benar-benar **menurunkan skor**; sisanya hanya label informatif.

```python
# compliance/error_codes.py
DEDUCTION_BEARING_CODES = {"B02", "B03", "B05", "B10", "B16", "B17"}
```

Deduksi ini **bukan** dari kode error itu sendiri, melainkan dari **bobot item scorecard**
(B10, B12→B18 dst.) atau **penalti field verifikasi** (B02/B03/B05 = cashline). Kode error
hanyalah label turunan; Risk Base hanya untuk pelaporan/statistik.

> **B17 tidak punya penalti field sendiri** (sejak v33 `CARD_HOLDER_STATIC_PENALTY = 0`,
> agar satu kegagalan tidak dihitung dua kali). Deduksinya datang dari item scorecard
> pasangannya lewat propagasi: field statik MISMATCH → `SC_CL_23_1`/`SC_CL_23_2`
> BELUM_SESUAI (−bobot item) → entri critical compliance `FAIL` (−`maximum_score/4`).
> Rantai itu baru berjalan pada tiket **tanpa** banding sejak **13 Agustus 2026**; sebelum
> itu B17 bisa tampil di tabel tanpa memotong skor sama sekali. Lihat
> [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) §5.1.

**Filter tampilan:** hanya kode dalam `ALLOWED_ERROR_CODES = {B02, B03, B05, B09, B10, B12,
B16, B17, B18, C03}` yang muncul di tabel Error Code. Kode lain (mis. B08, B11, B13, B15,
B19…) tidak ditampilkan — dan karena tidak berdeduksi, penyembunyian ini tidak mengubah skor.

---

## 4.1 Error Type & Error Category di Tabel Error Code (14 Agustus 2026)

Tiap baris tabel Error Code kini membawa dua kolom tambahan, **disalin apa adanya dari sheet
QC** (`csv_bank/Error Reason - Telemarketing QC_05082025.xlsx`, kolom *Error Type* dan
*Error Categories*):

| Kolom baris | Isi | Contoh |
|---|---|---|
| `error_type` | Deret kode = pihak yang gagal | `Error - Human`, `Error - Customer` |
| `error_category` | Pengelompokan kesalahan menurut sheet | `Data Input`, `Verification`, `Dokumen Pendukung` |

`details_error` juga **disamakan dengan kolom *Details Error* sheet**, menggantikan
parafrase yang sebelumnya ditulis sendiri di `ERROR_CODES`. Alasannya: sheet itulah kosakata
yang dipakai QC sehari-hari, dan wording tandingan membuat dua pihak menyebut kesalahan yang
sama dengan nama berbeda.

Keduanya muncul sebagai kolom **tambahan** — di tabel Error Code maupun di **Ringkasan
Kategori** — bukan pengganti judul kategori scorecard. Beberapa kategori scorecard memetakan
ke error category yang sama (mis. `SC_CL_23_*` dan `SC_CL_24` sama-sama `Verification`), jadi
mengganti judulnya justru menghapus pembeda.

Helper: `error_type_of(code)` / `error_category_of(code)` di `compliance/error_codes.py`.

---

## 5. Dari Mana Error Code Muncul

`build_error_code_table(evaluation)` (`compliance/error_codes.py`) menurunkan baris error dari
3 sumber evaluasi, ditambah 1 sumber di luar evaluasi (dokumen pendukung, §5.1):

| Sumber | Kondisi | Kode |
|---|---|---|
| **Scorecard** | Item `scorecard_result` berstatus `BELUM_SESUAI` | B10 (Penjelasan/Final Konfirmasi), B12 (Greeting), B18 (Legal Statement); + kode dari `evaluation["error_codes"]` LLM |
| **Card Holder Verification** | Field `card_holder_verification` = `MISMATCH` | **B17** |
| **Cashline Data Verification** | Field `cashline_data_verification` = `MISMATCH` | **B02 / B03 / B05** (risk-graded per field) |
| **Dokumen Pendukung** | Lihat §5.1 | **B09 / C03** |

- Field `SKIPPED_NULL` tidak memunculkan error.
- Verifikasi dinamik card holder yang sudah memenuhi aturan **"cukup 2 match"** ditekan
  (tidak jadi error). Lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md).
- **Critical compliance** terpisah (item `SC_CL_4 / SC_CL_23_1 / SC_CL_23_2 / SC_CL_37`),
  tetapi **tidak lepas**: `SC_CL_23_1`/`SC_CL_23_2` yang turun karena B17 ikut menjatuhkan
  entri kritisnya (§4).
- Kolom **Reason** baris B17 statik berasal dari baris verifikasinya. Untuk baris yang
  similarity-nya dihitung ulang Python, kalimat itu **ditulis ulang** agar cocok dengan
  vonis akhir — sebelum 13 Agustus 2026 baris MISMATCH bisa membawa kalimat LLM yang
  justru menyatakan nilainya masih di atas ambang match.

---

## 5.1 Sumber Dokumen Pendukung — B09 & C03 (14 Agustus 2026)

Sumber keempat, dan satu-satunya yang **tidak** berasal dari isi evaluasi: pemicunya berkas
yang diunggah — atau tidak diunggah. Dibangun oleh `document_error_code_rows()` dan
ditempelkan ke tabel oleh pemanggilnya, bukan oleh `build_error_code_table` sendiri.

| Kejadian | Kode | Error Type | Risk Base | Masuk Total Risk |
|---|---|---|---|---|
| Dokumen yang diminta **tidak pernah diunggah** sampai tenggat H+2 lewat | **B09** | `Error - Human` | **M** | ✅ |
| Dokumen **diunggah tetapi jenisnya keliru** (mis. KTP di slot NPWP) | **C03** | `Error - Customer` | **O** | ❌ |

**Garis pemisahnya adalah siapa yang gagal.** C03 memakai deret C karena berkasnya *datang*,
hanya keliru — memilih berkas memang pekerjaan nasabah. B09 tetap deret B karena berkasnya
*tidak pernah datang*: menagih kelengkapan sebelum tenggat habis adalah pekerjaan agent.

Sebelum 14 Agustus 2026 keadaan "lewat tenggat tanpa dokumen" hanya membuat tiket Not
Qualified **tanpa error code apa pun**, sehingga di tally Risk Base jatuh ke `O` (System) —
terbaca seolah kesalahan sistem, padahal kelalaian melengkapi berkas.

**Satu tiket bisa kena keduanya.** Slot NPWP diisi KTP → C03, dan karena kewajiban NPWP-nya
tetap kosong lalu tenggat lewat → B09. Dua baris terpisah dengan `reason` masing-masing.
Tally Risk Base tidak berlipat: tiap tiket tetap dihitung **satu** risk base tertinggi.

**Dokumen salah jenis tidak memenuhi kewajiban.** `_missing_docs_map` membuang slot ber-C03
dari daftar dokumen terunggah, jadi tiketnya tetap PENDING dan tetap bisa jatuh ke B09.
Dokumen yang OCR-nya belum/gagal selesai tetap dianggap memenuhi — menghukum tiket karena
antrean OCR belum jalan bukan penilaian atas pekerjaan agent.

**Deteksi jenis dokumen.** Skema OCR punya field wajib `jenis_dokumen`
(`prompt/_common.py`: `KTP | KK | NPWP | COVER_BUKU_TABUNGAN | LAINNYA | TIDAK_JELAS`),
dibandingkan dengan slot tujuan oleh `compliance.documents.wrong_document_type()`. Tiga hal
sengaja **tidak** dianggap salah jenis, karena semuanya berarti "tidak tahu":
`TIDAK_JELAS` (berkas tidak terbaca — itu keluhan mutu, bukan salah jenis), hasil OCR lama
yang belum punya field ini (dokumen lama tidak boleh tiba-tiba melahirkan error code baru),
dan slot yang tidak dikenal katalog.

> **B08 tidak diterbitkan sistem.** Kode sheet untuk "Type File Doc. terlampir kurang/tidak
> sesuai" (`Error - Human`, Risk L) tetap dikatalogkan tetapi dicabut dari
> `ALLOWED_ERROR_CODES`. Kalau suatu saat salah jenis dokumen harus membebani agent, yang
> diubah adalah **kodenya** (C03 → B08) — bukan `risk_base` C03, karena angka di katalog
> disalin dari sheet dan tidak boleh menyimpang.

**Pengecualian new joiner.** `NEW_JOINER_EXEMPT_CODES = {"B09", "C03"}`: kode dokumen tidak
ikut dilunakkan jadi `N`. Pelunakan itu memaafkan kesalahan yang wajar bagi agent baru **di
telepon**; masa kerja tidak mengubah tenggat H+2. (Untuk C03 aturannya tidak pernah menggigit
karena Risk Base-nya `O` — didaftarkan sebagai pernyataan niat.)

---

## 6. Banding (Manual Check): Hapus / Ubah / Tambah

QC (dan langsung oleh TL QC / SPQ Head) dapat mengajukan **banding** pada baris error.
Tiga jenis (`appeal_kind`):

| Jenis | Efek saat di-approve |
|---|---|
| **remove** (Hapus) | Baris error dihilangkan; item scorecard `BELUM_SESUAI→SESUAI` atau field verifikasi `MISMATCH→MATCH`, sehingga **deduksi dikembalikan (skor naik)** |
| **change** (Ubah) | Kode di-relabel ke `qc_new_error_code` (+ risk_base/details dari katalog). **Deduksi** dipertahankan bila kode baru **berdeduksi**; bila tidak, deduksi dinetralkan (skor naik) dan baris tetap ditampilkan dengan kode baru |
| **add** (Tambah) | Kebalikan remove — menempel error **baru** ke item/field (`item SESUAI→BELUM_SESUAI` / `MATCH→MISMATCH`), **skor turun**. Sumber `others` hanya tampilan (tidak mengubah skor) |

**Aturan kunci "change"** (`appeals_that_flip`):
- Ubah → kode **∈ `DEDUCTION_BEARING_CODES`** (mis. B17→B05) = **relabel saja**, deduksi tetap, skor tidak berubah.
- Ubah → kode **∉ set** (mis. B17→B26) = item/field di-*flip* (skor naik) **dan** baris di-inject ulang dengan kode baru agar error tetap terlihat.

Contoh: `B17 (−15) → Ubah → B26 (0)` ⇒ deduksi −15 ditiadakan, skor +15, baris tetap tampil sebagai B26.

---

## 7. Alur Persetujuan Banding (berjenjang)

`effective_appeal_status` (`compliance/error_codes.py`) — status final di bawah alur
**QC → Team Leader QC → [SPQ Head]**:

| Kondisi | Status efektif |
|---|---|
| TL QC **approve** (final) | `approved` |
| TL QC **reject** (final) | `rejected` |
| TL QC **escalate** + SPQ Head **approve** | `approved` |
| TL QC **escalate** + SPQ Head **reject** | `rejected` |
| Menunggu TL QC, atau escalated menunggu SPQ | `pending` |

Hanya banding **approved** (latest per `(error_code, item_code)`) yang diterapkan ke skor & tabel.

### Edit langsung tanpa hierarki (`origin`)
Kolom `error_code_appeals.origin` menandai asal banding:

| `origin` | Arti |
|---|---|
| `qc` | Diajukan QC, lewat alur berjenjang di atas |
| `tl_direct` | **Edit langsung oleh Team Leader QC** — berlaku seketika (auto-approved) |
| `spq_direct` | **Edit langsung oleh SPQ Head** — berlaku seketika |

QC wajib lewat hierarki; TL QC & SPQ Head bisa Hapus/Ubah/Tambah **langsung**.

Permission yang menggerakkannya (bukan lagi nama role): `results.error_code.appeal` (ajukan),
`results.error_code.direct_edit` (edit langsung), `results.error_code.review_tl`,
`results.error_code.review_spq`. **Admin tidak memilikinya satu pun** — lihat
[`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §3.

---

## Referensi terkait
- [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md) — model scoring & verifikasi
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — role & alur banding
- [`DATA_MODEL.md`](./DATA_MODEL.md) — tabel `error_code_appeals`
