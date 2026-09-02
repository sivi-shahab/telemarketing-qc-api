# CHANGELOG prompt_cashline_mus v72 -> v73

**Tanggal:** 28 Agustus 2026
**Cakupan:** disiplin pemilihan evidence + satu bentuk verifikasi yang selama ini
terlewat. KB tetap v34, scorecard tetap v3.
**Sumber:** 8 bug evidence pada `csv_bank/28 Agustus 2026/update.md` bagian 3.4.

---

## Diagnosis: 8 laporan itu bukan satu bug, melainkan empat pola

| Pola | Tiket |
|---|---|
| A. Kutipan tidak memuat klaim reason-nya | `170510CsbP` |
| B. Frasa benar, FASE panggilan salah | `140227gD7w`, `200446AYm5` |
| C. Berhenti di ucapan terpotong lalu menyimpulkan ketiadaan | `070840fvzq` |
| D. Pembacaan ulang oleh agent tidak dihitung sebagai verifikasi | `100537MsNl` |

`080145WhdT` DICORET dari daftar: seluruh data acuannya kosong sehingga tidak bisa
dipakai sebagai contoh apa pun — lihat bagian di bawah.

---

## 5b. Pemeriksaan silang reason <-> kutipan

Sebelum mengeluarkan item, kata kunci konkret pada `reason` (nama, nominal, nama
bank, frasa wajib) HARUS dapat ditemukan di dalam kutipan evidence-nya.

`170510CsbP` SC_CL_13:
- reason: "Agent menyebut rekening atas nama Bapak Stefanus Dani Kurniawan."
- kutipan: "...mohon maaf Pak untuk **pekerjaannya** kami cantumkan sebagai wirausaha,
  karyawan swasta, PNS, BUMN atau apa Pak?"

Kutipannya membahas pekerjaan. Nama itu tidak ada di dalamnya.

## 5c. Item yang terikat pembukaan panggilan — Greeting & Probing

`Greeting` (SC_CL_1..4) dan `Probing` (SC_CL_5) menilai apa yang terjadi DI PEMBUKAAN.
Evidence-nya wajib dari pembukaan panggilan pertama; dilarang dari Final Konfirmasi,
Legal Statement, penutup, atau pertengahan panggilan hanya karena kata kuncinya
muncul lagi.

Dua pembedaan yang ditulis eksplisit karena keduanya jadi sumber salah tangkap:
- Nama agent yang disebut ULANG di menit ke-6 bukan bukti perkenalan di pembukaan
  (`140227gD7w` SC_CL_2, evidence dari `[06:37.79 - 07:22.39]`).
- "Bapak memiliki fasilitas dari Bank Mega" menerangkan fasilitas NASABAH; itu bukan
  pernyataan ASAL AGENT. Begitu pula "tunainya dibayarkan ke Bank Mega" — itu bank
  TUJUAN PENCAIRAN (`200446AYm5` SC_CL_3, evidence dari Final Konfirmasi `[09:49.80]`).

## 5d. Ucapan terpotong bukan dasar menyimpulkan ketiadaan

Transkrip VTT memotong ucapan di tengah kalimat (tanda hubung di ujung, kalimat tanpa
predikat). Bila kandidat terbaik berupa ucapan terpotong, WAJIB membaca ucapan
berikutnya dan seluruh panggilan lain sebelum menyatakan BELUM_SESUAI.

`070840fvzq` SC_CL_31: evidence `[18:26.52 - 18:46.34]` "…limit terundang merupakan-"
lalu disimpulkan konfirmasi limit terpotong. Pernyataan lengkapnya ada di
`[19:32.90 - 21:42.28]` pada panggilan yang sama. Yang terpotong transkripnya, bukan
ucapan agent-nya.

## Pembacaan ulang oleh agent adalah verifikasi yang sah

Ditambahkan ke `DYNAMIC PARAM -> FIELD MAP + EVENT VERIFICATION`.

Verifikasi dinamis tidak selalu berbentuk pertanyaan terbuka. Bentuk yang paling
sering dipakai agent justru MEMBACAKAN nilai dari sistem lalu meminta nasabah
membenarkannya — dan itu tetap verifikasi.

Contoh frasa yang kini dikenali:
- "Ini saya bantu sampaikan kembali untuk alamat rumahnya, masih di … ya Pak ya?"
- "Untuk persamaan data dulu ya, alamat rumahnya masih di … betul ya Bu?"
- "Nomor teleponnya masih delapan satu dua … ya Pak?"

`extracted_value` diisi dari nilai yang DIBACAKAN AGENT, bukan dibiarkan null.
Bila nasabah mengoreksi, yang dipakai koreksinya. Bila nasabah tidak merespons sama
sekali, itu BUKAN verifikasi — diam bukan persetujuan.

**Tidak berlaku untuk verifikasi STATIK** (tanggal lahir & nama ibu kandung): di sana
nasabah wajib menyebut sendiri, dan agent yang membacakan lebih dulu justru melanggar
B15 (membocorkan data verifikasi sebelum nasabah menjawab).

`100537MsNl`: agent membacakan alamat rumah DAN alamat kantor lengkap di
`[04:54.68 - 05:19.10]` dan nasabah membenarkan, tetapi keduanya tercatat
`extracted_value: null` + MISMATCH, sehingga `verified_count` hanya 1 dan SC_CL_24
gagal. Dengan aturan ini keduanya terhitung dan SC_CL_24 lolos.

---

## Fallback Final Konfirmasi — DITAHAN PERMANEN (keputusan 28 Agustus 2026)

Sempat diusulkan mencabut *fallback* pada aturan `EVIDENCE PHASE SELECTION`:

> Kategori "Penjelasan Mega Cashline": kandidat dibatasi pada posisi SEBELUM segmen
> Final Confirmation. **Bila item TIDAK disebutkan sama sekali sebelum Final
> Confirmation, BARU ambil evidence dari dalam segmen Final Confirmation (fallback).**

**Usul itu DITOLAK.** Item "Penjelasan Mega Cashline" yang requirement-nya hanya
terpenuhi di dalam Final Konfirmasi TETAP `SESUAI`. Yang dinilai adalah APAKAH hal
itu disampaikan kepada nasabah, bukan pada menit ke berapa.

Alasan pendukungnya, dari pengukuran atas 98 tiket: **344 item "Penjelasan"**
(~3,5 per tiket) bergantung pada fallback ini. Mencabutnya akan membalik semuanya
menjadi BELUM_SESUAI.

Keputusan ini dikunci di prompt v74, di DUA tempat (`GLOBAL EVIDENCE ORDERING`
pengecualian (a) dan `EVIDENCE PHASE SELECTION`), lengkap dengan catatan untuk
pemelihara berikutnya: bila suatu saat sebuah item memang harus gagal karena
TERLAMBAT disampaikan, yang diubah adalah requirement item ITU di scorecard — bukan
aturan pemilihan evidence yang berlaku untuk seluruh kategori.

### `080145WhdT` DICORET sebagai contoh

Tiket ini sempat dipakai sebagai bukti masalah fallback (SC_CL_8 & SC_CL_11 lulus
dengan evidence dari `[32:02.68]`). **Tidak sah.** Pemeriksaan datanya menunjukkan
SELURUH `reference_value` tiket itu bernilai `None` — TMS maupun Ascend:

| Sumber | Field | reference_value |
|---|---|---|
| cashline_data_verification (TMS) | 10 dari 10 | `None` |
| card_holder_verification (Ascend) | 11 dari 11 | `None` |

Tiket itu dievaluasi tanpa data acuan sama sekali, jadi ia tidak bisa membuktikan
apa pun tentang pemilihan evidence. Yang perlu ditelusuri justru KENAPA tiketnya
diproses tanpa baris TMS/Ascend yang cocok — itu isu data, bukan isu prompt.

---

## Dampak operasional

- Berlaku untuk evaluasi BARU. Tiket lama perlu **Reprocess**.
- Aturan 5b/5c/5d bersifat mengoreksi PEMILIHAN evidence, bukan menambah/mengurangi
  kegagalan secara sistematis: sebagian item Greeting/Probing yang tadinya lolos
  dengan evidence dari tengah panggilan akan jatuh ke BELUM_SESUAI (data: 1 baris
  Greeting dan 2 baris Probing memakai evidence Final Konfirmasi), sementara item
  yang tadinya gagal karena ucapan terpotong akan lolos.
- Aturan pembacaan ulang akan MENAIKKAN `verified_count` pada sebagian tiket,
  sehingga SC_CL_24 lebih sering SESUAI dan skornya naik (lihat juga tingkat tengah
  7.5 yang ditambahkan di v70).
