# CHANGELOG prompt_cashline_mus v69 -> v70

**Tanggal:** 28 Agustus 2026
**Sumber permintaan:** `csv_bank/28 Agustus 2026/update.md` bagian 3 (Update KB/Prompt)
**Menyentuh juga:** `compliance/error_codes.py` (katalog + surfacing B27/B28)
**TIDAK menyentuh:** KB (tetap v34), scorecard (tetap v3)

---

## 1. Error code baru B27 & B28

Ditambahkan ke katalog `compliance/error_codes.py` dan ke `ALLOWED_ERROR_CODES`
(tanpa yang kedua, kode ada di katalog tapi tidak pernah tampil di tabel).

| Kode | Error Type | Error Category | Details Error | Risk Base |
|---|---|---|---|---|
| B27 | Error - Human | Offering bukan kepada CH | Offering bukan kepada Nasabah terundang | **M** |
| B28 | Error - Human | Inappropriate Language | Melakukan penawaran dengan kata atau kalimat tidak sopan, sarkas, tidak pantas dan bersifat menyinggung | **M** |

Keempat kolom disalin APA ADANYA dari `Error Reason - Telemarketing QC_28082026.xlsx`
baris 44-45. Dua hal yang mudah salah kalau menebak:

- **`error_category` B27 = "Offering bukan kepada CH"** — sama dengan B20, bukan
  kategori sendiri. Kolom inilah yang dirender dashboard sebagai Failure Category,
  jadi ia harus persis sama dengan sheet.
- **Risk Base keduanya M, bukan H.** Karena M ikut dihitung, kedua kode ini akan
  menaikkan Total Failure & Failure Rate begitu muncul — itu memang yang dimaksud.

### B27 di prompt
Blok aturan baru di `ERROR CODE CLASSIFICATION RULE`, dengan batas tegas terhadap B20:
B20 = penawaran tidak sampai ke pemegang kartu UTAMA (orangnya tetap terundang);
B27 = orangnya memang tidak ada dalam daftar undangan (NTB Eksternal). Pemicunya
menuntut pernyataan jelas — ragu atau lupa punya kartu TIDAK cukup.

### B28 diturunkan dari badword, bukan dari LLM
Bagian baru **`--- 4) Badword -> B28`** di `build_error_code_table()`: satu temuan
`badword_check` = satu baris B28. Prompt secara eksplisit MELARANG LLM menerbitkan
B28 sendiri, supaya barisnya tidak digandakan.

`item_code` sengaja kosong (temuan badword tidak menempel pada item scorecard mana
pun), sehingga de-dup `add()` tidak aktif — benar, karena satu panggilan bisa memuat
beberapa ucapan bermasalah yang masing-masing berdiri sendiri. `badword_rows()`
sendiri sudah melipat temuan kembar (timestamp + kutipan sama).

Diuji: 3 temuan (satu di antaranya duplikat) -> 2 baris B28, masing-masing membawa
`reason`, `timestamp`, dan `quote`-nya sendiri.

---

## 2. Badword: contoh sarkas baru

Sepuluh contoh dari kolom "Sampling details case" B28 disisipkan ke kategori yang
sudah ada di `BADWORD DETECTION RULE` — bukan sebagai daftar terpisah, supaya
klasifikasinya tetap satu kerangka.

| Kategori | Tambahan |
|---|---|
| 2 (sindiran/sarkasme) | "bapak/ibu mau apalagi sih?", "kan kami cuma nanya aja pak/bu?", "memang sudah ketemu bu dengan tamunya?" |
| 4 (menyalahkan/menghakimi) | "owh, enggak bisa gitu dong pak itu namanya bapak buka tutup buka tutup", "kan masih bertugas pak, kalo memang dirasa terganggu tinggal sampaikan saja" |
| 5 (menyinggung kondisi keuangan) | "kalau nasabah banyak hutang" |
| 7 (memaksa/menekan) | "kalo memang keberatan harus tlf yaudah enggak usah ditelepon tapi dibayar aja", "kalo keberatan diajukan aja minta dihapus..." |

Empat contoh lain dari sheet ("gembel", "ikh nasabahnya blo'on deh ini", "tidak niat
lo namanya", "ibu keberatan kita sudah berikan solusi...") sudah ada sejak v53 dan
tidak diduplikasi.

---

## 3. NOMOR REKENING: identifier, bukan teks

Aturan baru di `FIELD-SPECIFIC MATCHING RULES` + pengecualian di blok ambang 80%.

**Masalahnya:** nomor rekening jatuh ke ambang fuzzy 80% umum. Pada nomor 10 digit,
ambang itu memaafkan sampai DUA digit salah — padahal satu digit saja sudah membuat
dana masuk ke rekening orang lain.

**Alur baru:**
1. Buang semua non-angka.
2. Buang nol di depan pada kedua sisi.
3. MATCH hanya bila kedua string angka SAMA PERSIS. Selain itu MISMATCH, berapa pun
   kemiripannya.
4. `similarity_percent` tetap dilaporkan tetapi TIDAK menentukan vonis.
5. `reason` wajib menyebut digit ke berapa yang berbeda.

**Kalibrasi (dari update.md):**

| Nilai | similarity | Vonis lama | Vonis baru |
|---|---:|---|---|
| `4629790567` vs `4639790567` (010550Vosa) | 90 | MATCH ❌ | **MISMATCH** ✅ |
| `183348253` vs `0183348253` (200904GDcK) | 100 | MATCH ✅ | **MATCH** ✅ |

Ikut menyelesaikan `220336w7rv`.

---

## 4. EMAIL: local & domain dinilai TERPISAH

**Masalahnya:** similarity dihitung atas alamat UTUH. Domain hampir selalu identik
(`@gmail.com` vs `@gmail.com` = 100), sehingga ia menyeret bagian local yang buruk
melewati ambang 80.

**Aturan baru:** pecah pada `@`, hitung `sim_local` dan `sim_domain` sendiri-sendiri.
MATCH hanya bila **keduanya >= 80**. `similarity_percent` = `min(sim_local, sim_domain)`.
Dilarang merata-ratakan atau menghitung atas alamat utuh.

| Pasangan | Cara lama | Cara baru |
|---|---|---|
| `DEWIFITRI112@YAHOO.COM` vs `fitri112@yahoo.com` | 82 -> MATCH ❌ | local 67 -> **MISMATCH** ✅ |
| `andreantistoni@gmail.com` vs `adriansifoni@gmail.com` (200931kWpM) | 100 -> MATCH ❌ | local 64 -> **MISMATCH** ✅ |

---

## 5. SC_CL_24: skor verifikasi dinamis BERTINGKAT

**Masalahnya:** satu parameter yang terverifikasi benar dihukum sama beratnya dengan
nol parameter. Bobot SC_CL_24 = 15, dan status hanya SESUAI / BELUM_SESUAI.

**Aturan baru** (dua tempat: `VERIFICATION -> SCORECARD PROPAGATION` dan
`DYNAMIC VERIFICATION SCORECARD RULE` langkah 6):

| verified_count | status | item_score | pengurangan |
|---:|---|---:|---:|
| 0 | BELUM_SESUAI | 0 | **-15** |
| 1 | BELUM_SESUAI | **7.5** | **-7.5** |
| >= 2 | (hasil transkrip) | 15 bila SESUAI | **0** |

Yang dihitung hanya field yang benar-benar terverifikasi (`match = "MATCH"` ATAU
`event_verified = true`).

**Kenapa 7.5 tidak hilang tertelan aturan kategori.** `SC_CL_24` `tolerable = "NO"`
dan satu-satunya penghuni kategori "Verifikasi Dinamis", jadi status BELUM_SESUAI
membuat `category_result = "FAIL"` dan `category_score = 0`. Tetapi `ai_score_phase_2`
menjumlahkan **`item_score`**, bukan `category_score` — jadi 7.5 tetap masuk skor
akhir. Keduanya benar sekaligus: syaratnya memang belum terpenuhi, tetapi separuh
usahanya diakui. Ini ditulis eksplisit di prompt supaya model tidak "merapikan"
7.5 menjadi 0 atau 15.

Tidak ada risiko double-count: penalti -15 terpisah di `ai_score_verification` sudah
dihapus sejak v66, dan SC_CL_24 bukan bagian dari 4 item `critical_compliance_check`.

Menyelesaikan temuan `180936d7F2` butir 4 dan `040228HM7s`.

---

## Dampak operasional

- **B28 akan mulai muncul** di tabel Error Code untuk tiket ber-badword. Tiket lama
  tidak berubah kecuali di-Reprocess; tetapi karena B28 diturunkan di sisi KODE (bukan
  prompt), tiket lama yang evaluasinya SUDAH punya `badword_check` akan langsung
  menampilkannya tanpa reprocess.
- **B27 butuh evaluasi baru** — kode ini diterbitkan LLM, jadi hanya berlaku untuk
  tiket yang dievaluasi setelah v70 aktif.
- **Aturan nomor rekening & email lebih ketat** -> jumlah MISMATCH (dan B02/B03/B05)
  pada kedua field itu akan NAIK. Kenaikan ini adalah koreksi, bukan regresi: yang
  sebelumnya lolos memang seharusnya gagal.
- **Skor sebagian tiket naik 7.5** karena tingkat tengah SC_CL_24. Tiket yang tadinya
  tepat di bawah passing grade bisa berbalik menjadi Qualified setelah di-Reprocess.
- Tiket lama perlu **Reprocess** untuk memakai aturan prompt yang baru.

---

## 6. Sinkronisasi status Card Holder Verification ↔ Scorecard (KODE, bukan prompt)

**Masalahnya:** `_propagate_verification_to_scorecard()` hanya menangani `MISMATCH`.
Baris verifikasi yang berstatus `PENDING` (zona abu-abu, dokumen pendukung masih
ditunggu dalam tenggat H+2) tidak pernah dipropagasikan, sehingga item scorecard-nya
tetap `SESUAI`. Dua permukaan yang menjelaskan hal yang sama saling bertentangan di
layar yang sama.

Tidak bisa diperbaiki lewat prompt: `PENDING` dihitung SISTEM sesudah LLM selesai
(`apply_static_document_status`), dan prompt justru melarang LLM menerbitkannya
sendiri. Perbaikannya harus di kode.

**Aturan baru:**

| card_holder_verification | item scorecard | item_score | veto non-tolerable |
|---|---|---|---|
| MATCH | (dibiarkan) | (dibiarkan) | tidak |
| **PENDING** | **PENDING** | **dipertahankan** | **tidak** |
| MISMATCH | BELUM_SESUAI | 0 | ya |

`item_score` sengaja TIDAK disentuh untuk PENDING: zona abu-abu adalah
**penangguhan**, bukan vonis — tiketnya sedang menunggu dokumen, belum gagal.
Konsekuensinya otomatis benar di seluruh sistem tanpa perubahan lain:

- `scorecard_score()` hanya mengurangi bobot item `BELUM_SESUAI` → skor utuh.
- `has_blocking_intolerable_item()` hanya memveto `BELUM_SESUAI` → tidak memaksa FAIL.
- `_sync_critical_compliance()` hanya menjatuhkan item kritis `BELUM_SESUAI` → tidak
  ada score bomb untuk item yang masih ditunggu.

Begitu tenggat H+2 lewat tanpa unggahan, `apply_static_document_status` mengubah
barisnya menjadi `MISMATCH` dan jalur `BELUM_SESUAI` yang biasa mengambil alih.

`BELUM_SESUAI` menang bila keduanya menunjuk item yang sama — kegagalan yang sudah
pasti mengalahkan penangguhan.

**`reason` ditulis ulang** oleh `static_verification_pending_reason()` yang baru.
Tanpa itu item berbunyi PENDING sambil membawa kalimat LLM yang menjelaskan status
SESUAI ("nasabah menyebutkan tanggal lahir dengan benar") — persis kebingungan yang
dilaporkan. Kalimat barunya menyebut angka similarity dan jenis dokumen yang ditunggu.

**Verifikasi atas tiket yang dilaporkan:**

| Tiket | Field PENDING | Scorecard sebelum | Scorecard sesudah |
|---|---|---|---|
| `0602247CJA` | tanggal_lahir (87,5%) | SC_CL_23_1 = SESUAI ❌ | **SC_CL_23_1 = PENDING** ✅ |
| `010753NldX` | nama_ibu_kandung (75%) | SC_CL_23_2 = SESUAI ❌ | **SC_CL_23_2 = PENDING** ✅ |

Item pasangannya tidak ikut berubah — hanya field yang benar-benar PENDING.

**FE:** badge status scorecard sebelumnya hanya dua warna (`SESUAI` hijau, sisanya
merah), sehingga PENDING terbaca sebagai kegagalan. Kini tiga keadaan lewat
`scorecardStatusBadge()`: hijau / amber (PENDING) / abu-abu (TIDAK_DINILAI) / merah.

**Catatan:** prompt tidak diubah untuk butir ini dan tetap di v70 — `PENDING`
dihitung sesudah LLM selesai, jadi tidak ada instruksi LLM yang perlu berubah.

---

## 7. Revamp `reason` error code = `reason` scorecard (KODE, bukan prompt)

**Masalahnya:** baris Error Code yang diturunkan dari item scorecard BELUM_SESUAI
(kode B10/B12/B18) memakai `not_fulfilled_reason()`, yang hanya **menegasikan teks
requirement**. Hasilnya selalu benar tetapi selalu generik — ia tidak pernah bisa
menyebut sebab spesifik yang ditemukan penilai.

Pada `180936d7F2`, satu kegagalan berbunyi dua macam di dua tabel:

| Permukaan | Kalimat |
|---|---|
| Scorecard SC_CL_7 | "Agent menyebut bunga 2,09% per bulan, tetapi **frasa wajib effective rate tidak disebutkan**" ✅ |
| Error Code B10 | "Agent tidak menjelaskan bunga Mega Cashline" ❌ |

Yang generik itu bukan sekadar kurang detail — ia **menyesatkan**: agent jelas
menjelaskan bunganya, yang salah frasanya.

**Perbaikan:** parameter baru `prefer_item_reason` pada `not_fulfilled_reason()`.
Bila aktif, `reason` MILIK item scorecard dipakai (dibersihkan `clean_reason()`),
jatuh kembali ke negasi requirement bila item itu tidak punya reason.

Dibuat **opt-in, bukan perilaku bawaan**, karena pemanggil satunya —
`stats._non_tolerable_reasons()`, kolom "Critical Failure" pada tabel Results —
memang menghendaki negasi pendek satu baris (kebijakan 21 Agustus 2026).

Urutan prioritas dalam fungsi itu sekarang:
1. `static_verification_failure_reason()` untuk SC_CL_23_1/23_2 (paling spesifik)
2. `reason` milik item scorecard — bila `prefer_item_reason`
3. negasi requirement

**Regresi atas 98 tiket:** 30 baris berubah, **0 menjadi kosong**. Semua kalimat baru
lebih spesifik:

| Item | Lama | Baru |
|---|---|---|
| SC_CL_4 | Agent tidak menanyakan kesediaan waktu nasabah | Agent membuka percakapan tanpa menanyakan kesediaan waktu nasabah |
| SC_CL_10 | Agent tidak menjelaskan nominal pencairan Mega Cashline | Agent hanya menyebut rentang pengajuan, bukan nominal pencairan spesifik |
| SC_CL_27 | Agent tidak melakukan konfirmasi bunga Mega Cashline | Bunga sudah menyebut persen dan effective rate, tetapi belum menyebut per bulan |

**Efek samping yang disengaja:** pada Agent Error Summary, SC_CL_7 dan SC_CL_27 kini
runtuh menjadi SATU baris. Keduanya kode B10 dengan reason dan evidence yang sama
persis — sebelumnya terpisah hanya karena kalimat generiknya kebetulan berbeda
("menjelaskan" vs "melakukan konfirmasi"). Satu baris lebih jujur: agent melakukan
SATU kesalahan (tidak menyebut "effective rate") yang melanggar dua persyaratan.
Tabel Error Code pada detail tiket tetap menampilkan kedua barisnya, dibedakan
`item_code`.
