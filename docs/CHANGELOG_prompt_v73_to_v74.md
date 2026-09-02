# CHANGELOG prompt_cashline_mus v73 -> v74

**Tanggal:** 28 Agustus 2026
**Cakupan:** satu keputusan kebijakan, tanpa perubahan aturan penilaian.
KB tetap v34, scorecard tetap v3.

---

## Fallback Final Konfirmasi dikunci PERMANEN

Aturan `LATEST_MENTION_BEFORE_FINAL_CONFIRMATION` untuk kategori "Penjelasan Mega
Cashline" punya fallback: bila sebuah item tidak disebutkan sama sekali sebelum
segmen Final Confirmation, evidence-nya BARU diambil dari dalam segmen itu.

Pencabutan fallback ini sempat diusulkan — agar item "Penjelasan" yang hanya
terpenuhi saat recap penutup menjadi BELUM_SESUAI. **Usul DITOLAK** (keputusan
bisnis 28 Agustus 2026): yang dinilai adalah APAKAH hal itu disampaikan kepada
nasabah, bukan pada menit ke berapa ia disampaikan.

Keputusan itu kini ditulis di prompt, di **dua tempat**, agar tidak tercabut tanpa
sengaja oleh pemelihara berikutnya:

1. `GLOBAL EVIDENCE ORDERING` — pengecualian (a)
2. `EVIDENCE PHASE SELECTION` — butir kategori "Penjelasan Mega Cashline"

Keduanya memuat arahan yang sama: bila suatu saat sebuah item memang harus gagal
karena TERLAMBAT disampaikan, yang diubah adalah **requirement item itu di
scorecard** — bukan aturan pemilihan evidence yang berlaku untuk seluruh kategori.

### Angka pendukung

Pengukuran atas 98 tiket: **344 item "Penjelasan Mega Cashline"** (rata-rata ~3,5
per tiket) lulus dengan evidence dari segmen Final Konfirmasi. Mencabut fallback
akan membalik semuanya menjadi BELUM_SESUAI.

### `080145WhdT` bukan contoh yang sah

Tiket ini sempat dipakai sebagai bukti masalah fallback. Pemeriksaan datanya
menunjukkan SELURUH `reference_value`-nya bernilai `None`:

| Sumber | Field | reference_value |
|---|---|---|
| cashline_data_verification (TMS) | 10 dari 10 | `None` |
| card_holder_verification (Ascend) | 11 dari 11 | `None` |

Tiket itu dievaluasi tanpa data acuan sama sekali, sehingga MISMATCH pada
`nama_bank` / `nomor_rekening` / `nama_pemilik_rekening` di situ hanyalah artefak
reference kosong — bukan temuan, dan bukan bukti apa pun tentang pemilihan evidence.
Yang perlu ditelusuri adalah KENAPA tiketnya diproses tanpa baris TMS/Ascend yang
cocok; itu isu data, bukan isu prompt.

---

## Dampak operasional

Tidak ada. Versi ini hanya mendokumentasikan perilaku yang sudah berjalan sejak
awal; tidak ada aturan penilaian yang berubah, sehingga tiket lama TIDAK perlu
di-Reprocess karena versi ini.
