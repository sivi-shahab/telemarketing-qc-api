# Katalog Error Code & Efek Banding — Telemarketing QC System

Referensi lengkap **46 error code**, arti **Risk Base**, kode mana yang **berdeduksi**
(memengaruhi skor), dan bagaimana **banding (Manual Check)** mengubah error card & skor.

- Sumber katalog runtime: `compliance/error_reasons.json` (di-generate dari Excel
  `compliance/Error Reason - Telemarketing QC_05082025 (1).xlsx`; JSON = sumber kebenaran saat runtime).
- Logika penurunan & banding: `compliance/error_codes.py`.
- Endpoint katalog untuk dropdown: `GET /error_reasons`.

> Jangan tertukar dengan `ERROR_CODES` di `compliance/error_codes.py` (**15 entri**) — itu
> hanya kode yang benar-benar bisa diterbitkan mesin evaluasi (distribusi risk_base
> H=5 / M=7 / L=3). **46 kode** di bawah adalah katalog master lengkap untuk dropdown banding.
> Diverifikasi 12 Agustus 2026.

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
(B10, B12→B18 dst.) atau **penalti field verifikasi** (B02/B03/B05 = cashline, B17 = card
holder). Kode error hanyalah label turunan; Risk Base hanya untuk pelaporan/statistik.

**Filter tampilan:** hanya kode dalam `ALLOWED_ERROR_CODES = {B02, B03, B05, B10, B12, B16,
B17, B18}` yang muncul di tabel Error Code. Kode lain (mis. B11, B13, B15, B19…) tidak
ditampilkan — dan karena tidak berdeduksi, penyembunyian ini tidak mengubah skor.

---

## 5. Dari Mana Error Code Muncul

`build_error_code_table(evaluation)` (`compliance/error_codes.py`) menurunkan baris error dari
3 sumber:

| Sumber | Kondisi | Kode |
|---|---|---|
| **Scorecard** | Item `scorecard_result` berstatus `BELUM_SESUAI` | B10 (Penjelasan/Final Konfirmasi), B12 (Greeting), B18 (Legal Statement); + kode dari `evaluation["error_codes"]` LLM |
| **Card Holder Verification** | Field `card_holder_verification` = `MISMATCH` | **B17** |
| **Cashline Data Verification** | Field `cashline_data_verification` = `MISMATCH` | **B02 / B03 / B05** (risk-graded per field) |

- Field `SKIPPED_NULL` tidak memunculkan error.
- Verifikasi dinamik card holder yang sudah memenuhi aturan **"cukup 2 match"** ditekan
  (tidak jadi error). Lihat [`CAMPAIGN_SCORING.md`](./CAMPAIGN_SCORING.md).
- **Critical compliance** terpisah (item `SC_CL_4 / SC_CL_23_1 / SC_CL_23_2 / SC_CL_37`).

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
