# CHANGELOG prompt_cashline_mus v75 -> v76

**Tanggal:** 31 Agustus 2026
**Cakupan:** pembagian ulang B16/B17 untuk verifikasi, dan SC_CL_24 menjadi item
kritis (score bomb). KB tetap v34, scorecard tetap v3.

---

## 1. B17 hanya untuk verifikasi STATIK; verifikasi dinamis memakai B16

Katalog kodenya sudah lama menyebut pembagian ini:

| Kode | Arti | Risk |
|---|---|---|
| **B16** | Verifikasi Statik Berhasil, Verifikasi Dinamik kurang/tidak sesuai | M |
| **B17** | Tidak ada Verifikasi / verifikasi statik kurang / tidak berhasil | H |

Sampai v75 field DINAMIS card holder yang MISMATCH ikut menerbitkan B17, satu baris
per field. Tiket `180107uT48` karena itu membawa **tiga** B17 (Alamat Rumah, Alamat
Kantor, Alamat Email Terdaftar) padahal verifikasi statiknya sama sekali tidak gagal —
tanggal lahir MATCH 100%, nama ibu kandung PENDING di zona abu-abu. Tiket yang
statiknya justru berhasil diberi label "verifikasi statik tidak berhasil", dan dihukum
Risk **H** alih-alih **M**.

Sejak v76: **B17 hanya terbit dari `tanggal_lahir` / `nama_ibu_kandung` yang MISMATCH.**
Kegagalan dinamis diwakili B16, satu baris, sesuai definisinya.

`PENDING` dan `SKIPPED_NULL` tetap tidak menerbitkan apa pun. Begitu tenggat H+2 lewat
tanpa dokumen, baris statiknya menjadi MISMATCH dan B17 terbit sebagaimana mestinya.

## 2. B16 diturunkan sistem, tidak lagi menunggu LLM

Pengukuran 98 tiket menemukan **2 tiket** (`030808fLO1`, `100537MsNl`) yang
SC_CL_23_1/23_2-nya SESUAI dan SC_CL_24-nya BELUM_SESUAI — kondisi B16 persis —
tetapi tidak menerbitkan B16 sama sekali. Tanpa perbaikan ini, pencabutan B17 dinamis
akan membuat kedua tiket kehilangan SELURUH kode verifikasinya.

Sistem kini menurunkan B16 sendiri (`build_error_code_table`), sama seperti B10/B12/B18,
dan tidak menggandakannya bila LLM sudah menuliskannya. Syarat statiknya dilonggarkan
dari "keduanya SESUAI" menjadi "tidak ada yang BELUM_SESUAI", supaya tiket ber-item
statik PENDING tetap mendapat B16.

### Angka korpus (98 tiket)

| | v75 | v76 |
|---|---|---|
| Baris B17 dinamis | 16 | **0** |
| Baris B17 statik | 20 | 20 |
| Baris B16 | 4 | **6** |
| Total Failure | 114 | **100** |
| Tiket SC_CL_24 gagal tanpa kode verifikasi | — | **0** |

## 3. SC_CL_24 menjadi item kritis — SCORE BOMB

**Permintaan bisnis.** Sebelumnya hanya verifikasi STATIK yang mengebom skor
(SC_CL_23_1/23_2 ada di `critical_compliance_check`), sementara kegagalan verifikasi
DINAMIS cuma memotong bobot itemnya sendiri: 15 dari 150. Akibatnya tiket yang
verifikasi dinamisnya gagal total masih berskor **135/150** — terbaca "nyaris
sempurna" untuk kegagalan yang bank anggap kritis.

`SC_CL_24` kini menjadi item kritis kelima. Kegagalannya menambah satu iris penuh
`-(maximum_score / 4)` ke `ai_score_critical_compliance_check`.

Irisnya TETAP seperempat maksimal walau itemnya kini lima: iris itu adalah besaran
HUKUMAN per pelanggaran kritis, bukan pembagian kue tetap. Rentang
`ai_score_critical_compliance_check` karena itu menjadi 0 sampai
`-(5 * maximum_score / 4)`.

### Dampak

Vonisnya TIDAK berubah — keenam tiket ber-SC_CL_24 BELUM_SESUAI sudah Not Qualified
lewat veto non-tolerable (`tolerable = NO`). Yang diperbaiki adalah ANGKANYA:

| Tiket | phase_3 sebelum | phase_3 sesudah |
|---|---|---|
| `010714jUKH` | 135 | **97,5** |
| `180107uT48` | 120 | **82,5** |

## Penegakan di kode (berlaku untuk tiket LAMA juga)

Ketiga aturan ditegakkan deterministik di Python — `build_error_code_table` untuk
B16/B17, dan `CRITICAL_ITEM_CODES` + `_sync_critical_compliance` untuk score bomb-nya.
`_sync_critical_compliance` MENAMBAHKAN entri `SC_CL_24` bila belum ada di
`checked_items`, karena seluruh hasil evaluasi lama hanya memuat empat entri; tanpa itu
score bomb-nya tidak akan pernah menyala.

Artinya tiket lama ikut dinilai dengan aturan baru tanpa diproses ulang, dan prompt ini
adalah cerminnya — bila salah satunya diubah, yang lain WAJIB menyusul.
