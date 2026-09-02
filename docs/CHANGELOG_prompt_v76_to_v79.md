# CHANGELOG prompt_cashline_mus v76 -> v77  (+ KB v34 -> v35)

**Tanggal:** 31 Agustus 2026
**Cakupan:** verifikasi CASHLINE ikut dipropagasikan ke scorecard; error code berhenti
memotong skor. Scorecard tetap v3.

---

## Model yang benar

Scorecard menilai **bukan hanya** apakah agent menanyakan/menjelaskan sesuatu,
melainkan juga **kebenaran data** yang akhirnya masuk ke TMS. Alurnya:

    scorecard dibuat -> error code -> error code menjatuhkan item scorecard

**Tidak ada pengurangan poin karena error code.** Satu-satunya sumber pengurangan
adalah item scorecard yang BELUM_SESUAI.

Sampai v76 verifikasi CARD HOLDER sudah mengikuti model ini (SC_CL_23_1/23_2 untuk
statik, SC_CL_24 untuk dinamis), tetapi verifikasi CASHLINE tidak: MISMATCH-nya
memotong lewat jalur sendiri (`item_score` per field -> `ai_score_verification`)
sementara item scorecard-nya tetap SESUAI. Dua jalur potongan paralel untuk satu
kegagalan.

## Pemetaan field -> item scorecard

| field cashline | item | bobot |
|---|---|---|
| `nominal_pencairan` | SC_CL_10 | 1 |
| `tenor_dalam_bulan` | SC_CL_6 | 1 |
| `nominal_cicilan_per_bulan` | SC_CL_9 | 1 |
| `bunga` | SC_CL_7 | 1 |
| `nama_bank` | SC_CL_12 | 2 |
| `penalti_pelunasan_dipercepat` | SC_CL_15 | 2 |
| `nomor_rekening` | SC_CL_14 | 2 |
| `nama_pemilik_rekening` | SC_CL_13 | 2 |
| `provisi` | SC_CL_8 | 4 |
| `biaya_admin` | SC_CL_11 | 5 |

Pemetaan ini **bukan tebakan**: penalti per-field yang selama ini ditulis LLM sama
persis dengan bobot item di kolom kanan — terukur pada **37 kejadian MISMATCH di 98
tiket, tanpa satu pun perkecualian**. Tabel penalti lama (`CASHLINE_FIELD_PENALTY` di
kode) juga cocok 9 dari 10; yang kesepuluh, `nama_pemilik_rekening`, memang belum
punya entri di sana walau LLM tetap menghukumnya -2 = bobot SC_CL_13.

Dipilih keluarga **"menjelaskan/menanyakan"** (SC_CL_6..15), tempat datanya pertama
kali ditegakkan di panggilan. Item "konfirmasi" (SC_CL_25..32) menilai kewajiban
berbeda — ada-tidaknya recap penutup — dan tetap dinilai sendiri.

## `ai_score_verification` menjadi 0

`cashline_verification_score` kini 0 SELALU, sama seperti `card_holder_verification_score`
sejak v33. Karena kedua sukunya nol, `ai_score_verification = 0` untuk seterusnya.
Field-nya dipertahankan supaya bentuk keluaran tidak berubah.

`item_score` per field cashline TETAP DITULIS — masih berguna menakar bobot temuan di
tabel verifikasi — hanya tidak lagi dijumlahkan ke skor.

## KB v35: KB_CL_14 dibalik

Aturan lama KB_CL_14 menyatakan kebalikan dari model ini:

> "nomor di transkrip yang berbeda dari TMS TETAP SESUAI di scorecard (selisih nilainya
> urusan cashline_data_verification, bukan scorecard)"

Kalimat itu diganti: koroborasi transkrip tetap hanya boleh MENAIKKAN status (menyelamatkan
item ketika nomornya didikte sepotong-sepotong — kasus tiket 030828TPgb yang melahirkan
aturan itu 24 Agustus 2026), TETAPI selisih TMS vs transkrip kini menjatuhkan SC_CL_14
lewat propagasi. Ini satu-satunya entri KB yang memuat doktrin lama itu.

## Dampak: nyaris netral, dan memperbaiki satu double-count

Potongannya berpindah jalur, bukan bertambah:

| | Jumlah |
|---|---|
| Item scorecard yang kini dijatuhkan MISMATCH cashline | 37 (di 98 tiket) |
| Tiket yang `ai_score_phase_3`-nya berubah | **1** |

Satu-satunya yang bergeser, `160908U5GK` (85,5 -> 86,5), justru **memperbaiki
double-count**: `nominal_pencairan` di sana sudah BELUM_SESUAI karena agent memang tidak
menjelaskannya, sehingga -1 yang sama dihitung dua kali — sekali lewat bobot SC_CL_10,
sekali lagi lewat penalti per-field. Sekarang dihitung sekali.

Contoh `010714jUKH`, persis seperti yang diminta bisnis:

```
SC_CL_24  BELUM_SESUAI  (verifikasi dinamis 1 dari 2)   -> -7,5
SC_CL_14  BELUM_SESUAI  (TMS 4820008469 vs transkrip 4823008469) -> -2
ai_score_verification = 0
phase2 = 150 - 9,5 = 140,5
```

## Penegakan di kode

`compliance.error_codes._propagate_cashline_to_scorecard` + konstanta
`CASHLINE_FIELD_SCORECARD`, dipanggil berdampingan dengan
`_propagate_verification_to_scorecard`. Berlaku juga untuk tiket LAMA tanpa diproses
ulang — prompt & KB ini adalah cerminnya.

---

# Tambahan v77 -> v78 (hari yang sama)

## Zona PENDING untuk `nama_pemilik_rekening`

v77 menyatakan cashline "TIDAK punya zona abu-abu PENDING". Pengukuran setelahnya
menunjukkan itu keliru dan berakibat serius: **15 tiket berpindah dari PENDING ke
Not Qualified**, dan seluruhnya PENDING justru karena menunggu **cover buku tabungan**
untuk `nama_pemilik_rekening` — field yang MISMATCH-nya kini menjatuhkan SC_CL_13.
Aturan propagasi memotong jalur dokumennya sendiri: bank meminta dokumen untuk
membuktikan nama pemilik rekening, tetapi tiketnya sudah gagal sebelum dokumen datang.

v78 memasang penangguhan yang sama dengan verifikasi statik card holder:

| Keadaan | Baris cashline | SC_CL_13 |
|---|---|---|
| dokumen sudah diunggah | MATCH | tidak disentuh |
| belum, tenggat H+2 berjalan | **PENDING** | **PENDING** (tidak memotong, tidak memveto) |
| belum, tenggat lewat | MISMATCH | BELUM_SESUAI (potongan berlaku) |

`cashline_doc_requirements` ikut diperluas agar dipicu `PENDING` juga — kalau tidak,
permintaan dokumennya justru hilang tepat saat masa tunggunya dimulai.

Setelah perbaikan ini, flip vonis karena propagasi cashline turun dari **15 menjadi 3**
(+1 PASS -> FAIL). Ketiganya sah: yang menjatuhkan tiket adalah field cashline LAIN
(`penalti_pelunasan_dipercepat`, `nomor_rekening`, `nominal_cicilan_per_bulan`) yang
memang tidak punya dokumen pembuktian.

---

# Tambahan v78 -> v79 (hari yang sama)

## Format kalimat `reason` untuk item BELUM_SESUAI

Kalimat `reason` item scorecard muncul APA ADANYA di kolom **SCOREBOMB / Critical
Failure(s)** pada daftar Results dan di panel Critical Compliance Check. Selama ini
bentuknya pasif dan tidak menyebut pelakunya:

> "Bunga disebut 2,20% per bulan, tetapi frasa wajib effective rate tidak disebutkan."

Sejak v79 formatnya WAJIB:

    Agent tidak <perbuatan yang kurang> pada <konteks>

Contoh: *"Agent tidak menggunakan frasa efektif rate pada penjelasan bunga Mega
Cashline."*

`<konteks>` diturunkan dari requirement item-nya (`menjelaskan X` -> `pada penjelasan
X`, `melakukan konfirmasi X` -> `pada konfirmasi X`, `menanyakan X` -> `pada
pertanyaan X`, dan seterusnya), sedangkan `<perbuatan yang kurang>` HARUS hal
spesifik yang ditemukan penilai — bukan pengulangan requirement. Negasi generik
("Agent tidak menjelaskan bunga Mega Cashline") ikut dilarang, karena pada kasus ini
agent JELAS menjelaskan bunganya; yang kurang frasanya.

Hasil evaluasi LAMA tetap membawa kalimat lamanya sampai tiketnya diproses ulang —
format ini ditulis LLM, bukan disusun ulang di kode.

---

# Perbaikan kode (bukan prompt) — penangguhan SC_CL_13 yang tidak pernah berlaku

**Tanggal:** 31 Agustus 2026 · `compliance/error_codes.py`

Zona PENDING v78 di atas tidak pernah benar-benar bekerja. Dua aturan yang keduanya
sah saling meniadakan:

1. prompt menyuruh LLM menuliskan sendiri propagasi `MISMATCH -> BELUM_SESUAI`,
   sehingga SC_CL_13 **sudah** BELUM_SESUAI di dalam JSON hasil evaluasi;
2. LLM DILARANG menerbitkan PENDING (keadaan dokumen & tenggat H+2 hanya diketahui
   sistem), jadi penangguhannya dihitung belakangan oleh
   `apply_cashline_document_status`.

`_propagate_cashline_to_scorecard` hanya bisa MENURUNKAN `SESUAI -> PENDING`;
penjaganya (`status not in ("BELUM_SESUAI", "PENDING")`) melewati item yang sudah
BELUM_SESUAI. Hasilnya baris cashline berbunyi **PENDING** sementara item
scorecard-nya tetap **BELUM_SESUAI** — `tolerable = NO`, jadi tiketnya divonis Not
Qualified DAN kena iris 10% `non_tolerable_bomb`, justru selama masa tunggu dokumen
yang seharusnya menahan vonis itu.

Contoh `060228OEvG`: `nama_pemilik_rekening` 89% ("Vonny Salomi Amnifu" vs TMS "VONI
SALOMI AMNIFU"), baris cashline PENDING menunggu cover buku tabungan, tetapi SC_CL_13
BELUM_SESUAI -> skor 148 turun ke 133 dengan SCOREBOMB SC_CL_13 (-15) dan vonis FAIL.

Sejak perbaikan ini penangguhan boleh MENGANGKAT item dari BELUM_SESUAI ke PENDING,
dan `item_score` dikembalikan ke bobot penuh (PENDING tidak memotong skor, jadi 0 di
kolom Skor menyesatkan).

**Syaratnya `extracted_value` terisi.** Bila transkrip tidak pernah menyebut nama
pemilik rekening (`111030VH2c`), yang gagal adalah kewajiban
"menyebutkan/menanyakan"-nya sendiri, bukan beda ejaan — dan cover buku tabungan tidak
bisa membuktikan sesuatu yang tidak pernah diucapkan. Item itu TETAP BELUM_SESUAI.

Dampak pada korpus 98 tiket: 10 tiket berada dalam keadaan ini, seluruhnya SC_CL_13.
7 di antaranya berpindah **FAIL -> PENDING**; tidak ada tiket PASS yang berubah dan
tidak ada yang berpindah ke arah sebaliknya.

| Tiket | Sebab tetap FAIL |
|---|---|
| `111030VH2c` | `extracted_value` kosong — agent tidak pernah menyebutkannya |
| `061050ugYQ` | SC_CL_23_1 (verifikasi statik) |
| `180107uT48` | SC_CL_24, SC_CL_7, SC_CL_8, SC_CL_27, SC_CL_28 |

---

# Perbaikan kode (bukan prompt) — status PENDING di Ringkasan Kategori

**Tanggal:** 31 Agustus 2026 · `compliance/error_codes.py`,
`dashboard/src/components/EvaluationView.vue`

Ringkasan Kategori hanya mengenal **PASS / FAIL / TIDAK DINILAI**. Sejak item scorecard
bisa DITANGGUHKAN menunggu dokumen — SC_CL_23_1/23_2 lewat
`_propagate_verification_to_scorecard`, SC_CL_13 lewat
`_propagate_cashline_to_scorecard` — item PENDING jatuh ke cabang `else` dan
kategorinya terbaca **PASS dengan nilai penuh**. Satu-satunya permukaan yang meringkas
scorecard per kategori justru menyembunyikan bahwa tiketnya sedang menunggu bukti,
padahal tabel Scorecard dan tabel verifikasi di halaman yang sama sudah berbunyi
PENDING.

`derive_category_summary` sekarang menerbitkan **empat** nilai `category_result`:

| Keadaan kategori | `category_result` |
|---|---|
| >= 1 item BELUM_SESUAI | `FAIL` |
| seluruh itemnya TIDAK_DINILAI | `TIDAK_DINILAI` |
| tidak ada yang gagal, >= 1 item PENDING | **`PENDING`** |
| sisanya | `PASS` |

FAIL tetap menang atas PENDING: sekali ada item yang sudah pasti gagal, kategorinya
gagal — sama seperti di kedua fungsi propagasi. `earned_score` TIDAK berubah karena
PENDING; penangguhan memang tidak memotong skor, jadi angkanya tetap sama dengan yang
dipakai `ai_score_phase_2`. Kolom **Alasan** kategori PENDING diisi `reason` item-item
yang ditangguhkan, sehingga berbunyi sama dengan tabel verifikasi asalnya.

Di dashboard: badge kategori **amber** (sewarna PENDING di tabel verifikasi & kolom
Status tabel Scorecard), kolom "Item Belum Sesuai" menjadi **"Item Belum Sesuai /
Pending"** dan ikut memuat item PENDING dengan tanda `PENDING` di sebelah kodenya —
tanpa itu kategori berstatus PENDING tidak menyebut item MANA yang ditunggu. Kolom
Error Type / Error Category item PENDING sengaja `—`: error code-nya baru terbit kalau
tenggat H+2 lewat tanpa dokumen.

Skema keluaran prompt TIDAK berubah (`"category_result": "PASS | FAIL"`). LLM memang
tidak boleh menerbitkan PENDING sendiri — keadaan dokumen & tenggat H+2 hanya diketahui
sistem — dan `derive_category_summary` menyusun ulang blok ini di waktu baca.

Dampak pada korpus 98 tiket: 46 baris kategori berpindah dari PASS ke PENDING.

---

# Perbaikan kode (bukan prompt) — filter AI Status membaca evaluasi yang berbeda

**Tanggal:** 31 Agustus 2026 · `compliance/stats_aggregate.py`, `api/routers/stats.py`,
`db/crud.py`

Tiket `060228OEvG` berkolom **AI Status = PENDING**, tetapi ikut muncul saat pengguna
menyaring **Not Qualified**. Kolom dan filternya menghitung vonis dari evaluasi yang
BERBEDA.

`_result_ai_status` menerima `doc_status` (`(uploaded_types, sla_expired)` dari
`document_status_map`) sebagai bahan OPSIONAL. Bila tidak dikirim,
`_adjusted_evaluation` melewati `apply_static_document_status` dan
`apply_cashline_document_status`, sehingga baris verifikasi yang sedang menunggu
dokumen tidak pernah ditangguhkan: barisnya tetap MISMATCH, item scorecard-nya
BELUM_SESUAI, dan veto non-tolerable menjatuhkannya ke FAIL.

Seluruh 10 pemanggil di `stats_aggregate` sudah mengirimkannya. **Tiga penyaring tidak:**

| Tempat | Menu |
|---|---|
| `api/routers/stats.py::list_results` | Results, Manual Check, Pending Check |
| `api/routers/stats.py` ekspor XLSX tiket | tombol Export |
| `db/crud.py::list_transcripts` | Transcripts (lebih parah: `missing_docs`, tenggat H+2, dan `data_gap` juga tidak dikirim) |

Ketiganya menyusun sendiri bahan `_result_ai_status` — sepuluh baris boilerplate yang
disalin ulang di tiap tempat, dan justru itu yang membuat satu bahan tercecer.

Perbaikannya menghapus penyalinan itu: helper berkelompok baru
`stats_aggregate.ai_status_map(db, results)` — versi banyak-tiket dari
`ai_status_for_result`, menyusun SELURUH bahannya sendiri — dan ketiga penyaring kini
memanggilnya. Satu tempat yang tahu cara menghitung AI Status, jadi kolom dan filter
tidak bisa lagi berbeda.

Dampak pada korpus 98 tiket — vonis filter sekarang identik dengan kolomnya
(PASS 23 / FAIL 36 / PENDING 39); sebelumnya filter membaca 44 FAIL / 31 PENDING:

| Tiket | Filter lama | Kolom (dan filter baru) |
|---|---|---|
| `020849In4o`, `200931kWpM`, `1708263H7L`, `060228OEvG`, `030424nJOA`, `0301246FpW`, `18043791Yr`, `200904GDcK` | FAIL | **PENDING** |

---

# Perbaikan kode (bukan prompt) — peran pembicara TERTUKAR di transkrip hulu

**Tanggal:** 31 Agustus 2026 · `compliance/call_ownership.py`,
`compliance/pdf_parser.py`

Pada tiket `0210052AQd`, kolom **Transkrip** baris verifikasi statik card holder KOSONG
untuk `tanggal_lahir` dan `nama_ibu_kandung`, padahal item scorecard pasangannya
(SC_CL_23_1 / SC_CL_23_2) membawa `evidence.quote` yang JELAS memuat jawaban nasabah —
"28 Juli 1980" (Ascend `19800728`) dan "Hajah Aminah" (Ascend `AMINAH`).

Sebabnya bukan LLM yang ceroboh. **Diarization hulu MENUKAR label `Agent` dan
`Customer`** pada berkas itu: pihak yang dilabeli `Customer` justru memperkenalkan diri
("Iya nama saya Rukawa, Pak, dari bagian kartu kreditnya Bank Mega"), dan jawaban
nasabah tercatat sebagai ucapan `Agent`.

Dari situ semuanya mengikuti dengan benar tetapi salah:

1. prompt mewajibkan `extracted_mentions` memuat **UCAPAN NASABAH**; pada berkas yang
   tertukar tidak ada satu pun ucapan nasabah yang menyebut nilainya, jadi array itu
   ditulis kosong dan `reason`-nya berbunyi "Agent tidak memperoleh penyebutan ... dari
   nasabah";
2. `normalize_static_verification` menghitung similarity DARI array itu — kosong, jadi
   0 -> **MISMATCH**;
3. `_propagate_verification_to_scorecard` menjatuhkan SC_CL_23_1 / SC_CL_23_2, KEDUANYA
   item KRITIS -> iris **25% masing-masing** + veto Not Qualified.

`evidence.quote` tidak peduli siapa yang bicara, `extracted_mentions` peduli — itulah
mengapa keduanya bertentangan di layar yang sama.

Modul `call_ownership` memang sudah menolak mempercayai label diarization untuk
menentukan pemilik panggilan (dan docstring-nya sudah mencatat label tertukar pada
`180107uT48`). Sekarang labelnya tidak cuma diabaikan, tetapi **diperbaiki**:
`fix_speaker_roles` mengenali pihak yang memperkenalkan diri dari Bank Mega di
pembukaan panggilan sebagai agent, dan menukar balik kedua label bila perkenalan itu
justru ada di sisi nasabah. Dipanggil `build_transcript`, jadi berlaku sebelum
transkrip dikirim ke LLM.

Sangat konservatif — tidak menyentuh apa pun kecuali: tepat dua label (satu bersifat
agent, satu bersifat nasabah; label netral `SPEAKER_0/1` dilewati), ada perkenalan
terbaca di 8 segmen pertama, dan hanya SATU pihak yang membawanya (seri = dibiarkan).

Pengukuran atas SELURUH transkrip yang ada — **217 PDF pada 98 tiket**:

| | Jumlah |
|---|---:|
| label sudah benar / tidak disentuh | 186 |
| **label ditukar balik** | **31** (di **24 tiket**) |
| kasus seri (tidak bisa dipastikan) | 0 |

Ke-31-nya diperiksa manual satu per satu dan memang tertukar; sesudah perbaikan tidak
tersisa satu berkas pun yang pihak-pemerkenalkan-dirinya masih berlabel nasabah.

Tiket yang terdampak: `010753NldX`, `020532VF8Y`, `020940PdrO`, `021006rNU6`,
`0210052AQd`, `030808fLO1`, `0301246FpW`, `040228HM7s`, `070840fvzq`, `0904182mae`,
`090312OQfA`, `0912072CMV`, `100505VSuR`, `110847Ef1L`, `140909co8Q`, `161040q6ZO`,
`170510CsbP`, `1708263H7L`, `180107uT48`, `180914y1bK`, `18043791Yr`, `200524vd3x`,
`220934ZhkY`, `221048EkC8`.

**PERLU PROSES ULANG.** Berbeda dari perbaikan waktu-baca lain di changelog ini, yang
ini bekerja di HULU — pada transkrip yang dikirim ke LLM. Evaluasi yang sudah tersimpan
tetap membawa `extracted_mentions` kosongnya sampai tiketnya diproses ulang lewat menu
Reprocess Tickets.

## Proses ulang 24 tiket terdampak (31 Agustus 2026)

Ke-24 tiket di atas diproses ulang setelah perbaikan dipasang dan worker di-restart
(kode-nya bind-mount, jadi proses celery lama masih memegang modul versi sebelumnya).

* satu job `scope=campaign` berisi 24 item; 23 selesai pada percobaan pertama,
  `021006rNU6` gagal dua kali karena gangguan sementara (LLM `Connection error`, lalu
  MinIO `Max retries exceeded`) dan berhasil pada percobaan ketiga;
* **30+ perbaikan label** tercatat di log worker (`peran pembicara tertukar pada ...`);
* sesudahnya TIDAK ADA satu pun baris verifikasi statik pada ke-24 tiket yang kolom
  Transkrip-nya masih kosong (sebelumnya 6 baris di 5 tiket), dan tiap tiket menyisakan
  tepat satu row.

Contoh `0210052AQd`: `tanggal_lahir` MATCH 100% ("28 Juli 1980" vs `19800728`) dan
`nama_ibu_kandung` MATCH 100% ("Aminah" vs `AMINAH`) — kedua scorebomb 25%
SC_CL_23_1/23_2 hilang. Tiketnya TETAP Not Qualified, tetapi kini karena temuan yang
berdiri sendiri: SC_CL_4 (agent tidak meminta kesediaan waktu di pembukaan), item
kritis, skor 105,5 dari passing 135.

CATATAN: proses ulang menjalankan evaluasi LLM dari NOL dengan prompt yang berlaku
sekarang, jadi perubahan vonis pada ke-24 tiket itu bukan semata akibat perbaikan label
pembicara. Vonis seluruh korpus bergeser dari PASS 23 / FAIL 36 / PENDING 39 menjadi
**PASS 22 / FAIL 35 / PENDING 41**.

---

# Perbaikan tampilan — Failure Rate di atas 100% dibatasi jadi "100%+"

**Tanggal:** 31 Agustus 2026 · `dashboard/src/views/dashboard/StatsView.vue`,
`compliance/stats_aggregate.py`

Kolom **Failure Rate** pada tab Hierarki Failure Rate (pohon Area Manager → Team
Leader → Agent) bisa menampilkan angka seperti **550%**. Itu BUKAN salah hitung:

* pembilangnya `risk_base_tally` — SETIAP risk base milik tiket Not Qualified, bukan
  satu yang tertinggi (perubahan 28 Agustus 2026);
* penyebutnya jumlah **transkrip**, bukan jumlah risk base.

Jadi satu tiket bisa menyumbang lebih dari satu. Tiket `160908U5GK` menyumbang 11 risk
base atas 2 transkrip = 550%.

Di layar presentasi angka itu terbaca seperti sistemnya rusak, jadi yang di atas 100
kini ditulis **"100%+"** (`rateText`). Pembatasannya MURNI TAMPILAN — nilai aslinya
tetap dipakai untuk warna badge, pengurutan baris, dan penyorotan baris berisiko;
membatasi angkanya sendiri akan membuat dua agent yang jauh berbeda tampak setara di
urutan.

Berlaku pada keempat permukaan yang menampilkan metrik yang sama: KPI "All Telesales —
Failure Rate", pohon AM → TL → Agent, tabel Daftar Sales Agent, dan tabel agent milik
Team Leader.

Docstring `_rate_of` ikut diperbaiki: kalimatnya masih berbunyi "tiap tiket menyumbang
paling banyak 1 ke H/M/L, jadi rasionya selalu <= 100%" — sudah tidak berlaku sejak
pembilangnya pindah ke `risk_base_tally`.

---

# Tiket tersembunyi: 12 dari 18 dibuka kembali

**Tanggal:** 31 Agustus 2026 · `app_settings.hidden_ticket_ids`

Daftar tetap 18 ticket id yang ditahan dari menu Statistik/Results/Transcripts (lihat
`crud.get_hidden_ticket_ids`) disusun dari DUA sebab yang tidak dicatat terpisah.
Dipisahkan ulang dari datanya:

| Sebab | Jumlah | Bukti |
|---|---:|---|
| data acuan kosong (`data_gap` Ascend/TMS/agent) | 6 | rasio failure 0%, `data_gap` terisi |
| Failure Rate di atas 100% | 12 | tidak punya `data_gap`, rasio 100%-550% |

Pemisahannya bersih — tidak ada satu tiket pun yang masuk kedua golongan.

**12 tiket golongan Failure Rate dibuka kembali** dan diproses ulang: `160908U5GK`,
`060231O23U`, `020940PdrO`, `180936d7F2`, `0110505ngB`, `0609511Z4f`, `180107uT48`,
`220336w7rv`, `010550Vosa`, `140217uYfB`, `010714jUKH`, `030357DUdr`. Alasan
penyembunyiannya sudah tertangani oleh pembatasan "100%+" di atas.

6 tiket ber-`data_gap` TETAP disembunyikan: sebabnya bukan tampilan melainkan data
acuan yang memang belum ada — `080145WhdT`, `0904182mae`, `110847Ef1L`, `161040q6ZO`,
`180918etUh`, `210501UAgM`.

CATATAN angka: rasio pada tabel di atas dihitung SESUDAH proses ulang 24 tiket
sebelumnya, jadi tiga di antaranya sudah bergeser dari nilai saat daftar itu disusun —
`020940PdrO` kini 0% (vonisnya berubah menjadi PENDING), sedangkan `010714jUKH` dan
`180107uT48` kini tepat 100%. Ketiganya tetap dibuka: tak satu pun punya `data_gap`,
jadi ketiganya memang golongan Failure Rate.
