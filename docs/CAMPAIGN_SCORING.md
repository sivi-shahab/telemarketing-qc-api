# Campaign & Model Scoring — Telemarketing QC System

Menjelaskan **konfigurasi campaign** (prompt / knowledge base / scorecard / RIPLAY) dan
**cara skor QC dihitung** hingga menjadi status **PASS / FAIL / PENDING**. Ini adalah
pengetahuan inti untuk merawat logika QC.

Sumber: `compliance/scoring.py`, `compliance/error_codes.py`, `compliance/stats_aggregate.py`,
`compliance/documents.py`, `compliance/static_similarity.py`, `compliance/riplay.py`,
`api/routers/campaign.py`, `api/routers/stats.py`.

> **Prinsip penting:** logika penilaian sesungguhnya ada di **prompt LLM** (disimpan di DB,
> kolom `campaigns.prompt_text`). `compliance/scoring.py` adalah **mirror deterministik** dari
> perhitungan tersebut agar dashboard/export konsisten. Mengubah aturan penilaian = mengubah
> **prompt/scorecard**, lalu upload ulang campaign (tanpa rebuild/restart).

---

## 1. Konfigurasi Campaign

Setiap campaign punya 3 file `.txt` mentah (diberikan ke LLM apa adanya, tanpa parsing JSON)
plus **RIPLAY** PDF opsional.

| Berkas | Isi | Versi aktif (13 Agustus 2026) |
|---|---|---|
| **prompt.txt** | Instruksi/sistem prompt LLM — seluruh logika evaluasi & scoring | `prompt_cashline_mus_v54.txt` (~132 KB) |
| **knowledge_base.txt** | Materi acuan/KB (dirujuk scorecard lewat kode `KB_CL_*`) | `cashline_kb_v21.txt` (~59 KB) |
| **scorecard.txt** | Daftar item yang dinilai + bobot | `cashline_scorecard_v3.txt` (**39 item**) |
| **riplay.pdf** | Fact sheet produk resmi bank; jadi ground truth angka produk | `riplay_cashline.pdf` |

Salinan ketiga file teks ada di `docs/` dan riwayat lengkapnya di `campaign_cashline/`
(termasuk CHANGELOG antar versi).

**Campaign di DB saat ini (10 baris):** `cashline` (id 18, satu-satunya yang lengkap
prompt/KB/scorecard/RIPLAY), `ntb`, `loc`, `retention`, `reinstate`, `activation`, `megapay`,
`Informasi dan Status Transaksi`, `Informasi Biaya Kartu Kredit`,
`Informasi pembayaran kartu kredit`. Endpoint `GET /campaign_readiness` melaporkan kesiapan
tiap campaign (konfigurasi QC, roster, akun, data TMS, tiket).

### Format scorecard

Meski ber-ekstensi `.txt`, isinya **JSON array 39 item**: `SC_CL_1`..`SC_CL_38`, dengan
`SC_CL_23` dipecah menjadi **`SC_CL_23_1`** (tanggal lahir) dan **`SC_CL_23_2`** (nama ibu
kandung). Total bobot = **150.0**, terbagi 10 kategori.

```json
{
  "category": "Greeting",
  "item_code": "SC_CL_1",
  "requirement": "Agent menyampaikan salam pembuka",
  "kb_reference": "KB_CL_1",
  "weight": 2,
  "tolerable": "YES"
}
```

| Field | Arti |
|---|---|
| `item_code` | ID item (`SC_CL_*`), dipakai untuk mapping error code & banding |
| `requirement` | Kriteria yang dinilai |
| `kb_reference` | Kode KB pendukung (`KB_CL_*`) |
| `weight` | Bobot skor (boleh desimal, mis. 4.5, 7.5) |
| `tolerable` | `YES`/`NO`. **`NO` = non-tolerable** → bila BELUM_SESUAI memaksa FAIL (§3.4) |

> Hanya **3 item yang `tolerable: YES`** (SC_CL_1, SC_CL_2, SC_CL_3 — blok Greeting);
> **36 sisanya `NO`**. Artinya hampir setiap kegagalan item memicu veto FAIL.
>
> Berkas scorecard berakhir dengan **trailing comma** sebelum `]`, jadi bukan JSON yang
> valid secara ketat. Itu tidak masalah bagi LLM, tetapi parser Python perlu membersihkannya
> lebih dulu.

---

## 2. RIPLAY (overlay KB)

RIPLAY = *Ringkasan Informasi Produk dan Layanan*, fact sheet resmi bank. Saat diunggah
bersama campaign:

1. PDF dirender jadi gambar halaman (`RIPLAY_MAX_PAGES`, `RIPLAY_RENDER_SCALE`).
2. Dikirim ke model vision (`RIPLAY_MODEL`, fallback ke `LLM_MODEL`) untuk ekstraksi
   terstruktur → `campaigns.riplay_extraction`.
3. **Gate nama produk**: kemiripan nama produk pada RIPLAY vs nama campaign harus ≥
   `RIPLAY_MIN_SIMILARITY` (default 50.0), agar RIPLAY produk lain tidak tertimpa.
4. Hasilnya di-*overlay* ke KB: `kb_text = kb_text_raw + overlay`. **RIPLAY menang** bila
   berbeda dengan KB.

Bila upload campaign berikutnya tidak menyertakan RIPLAY, ekstraksi yang tersimpan
**diterapkan ulang** — KB tetap sinkron dengan fact sheet terakhir tanpa edit manual.
Karena `kb_text_raw` disimpan terpisah, overlay selalu bisa dibangun ulang dari basis bersih.

---

## 3. Cara Upload / Update Campaign

1. Dashboard → **Upload Data → Upload Campaign** → isi nama campaign + unggah file.
   **Menu ini hanya ada pada akun Admin** sejak 14 Agustus 2026.
2. Endpoint: `POST /upload_detail_campaign` (multipart: `scorecard`, `knowledge_base`,
   `prompt`, `campaign`, `riplay` opsional).
3. **Guard: `admin.campaign.write`** — sejak 14 Agustus 2026 **hanya `admin`** (SPQ Head sudah
   tidak punya, lihat [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) §4.1). Endpoint ini dulu terbuka
   untuk semua user login — sudah diperketat, karena menimpanya berarti menimpa seluruh aturan QC.
4. Disimpan **dua tempat**: DB (`campaigns.*`, `is_active=True`) **dan** arsip MinIO
   `campaigns/{campaign}/{prompt,knowledge_base,scorecard}.txt`.
5. **Tidak perlu restart** — worker membaca `campaigns.prompt_text` **fresh dari DB tiap task**.
6. **Wajib ada sebelum upload transkrip.**

---

## 4. Model Scoring (phase-2 → phase-3 → PASS/FAIL)

### 4.1 Skor Maksimal & Passing Grade

`maximum_score` diturunkan dari **minat produk** (`campaign_interest`):

| Kondisi | maximum_score |
|---|---|
| Hanya **Mega Cashline** INTERESTED | **108.75** |
| **Cashline + Mega Ultima Shield (MUS)** INTERESTED | **150** (108.75 + 41.25) |
| Tidak ada yang INTERESTED | 0 (lihat Zero-Score Rule) |

`passing_grade = 90% × maximum_score` (mis. 150 → **135.0**; 108.75 → **97.88**).

> `maximum_score` & `passing_grade` **dihasilkan LLM** di JSON evaluasi (bukan kolom DB;
> `passing_grade` sudah di-drop dari scorecard sejak migrasi 0003) — bersifat dinamis per tiket.

### 4.2 Tiga komponen skor

```
ai_score_phase_2  = scorecard_score
                  = maximum_score − Σ(weight setiap item scorecard BELUM_SESUAI)

ai_score_verification              = penalti field Cashline yang MISMATCH (§5.2)
ai_score_critical_compliance_check = penalti item kritis yang FAIL (§6)

ai_score_phase_3  = ai_score_phase_2 + ai_score_verification + ai_score_critical_compliance_check
```

**Keputusan status dasar:**

```
PASS  bila  ai_score_phase_3 ≥ passing_grade
FAIL  bila  ai_score_phase_3 <  passing_grade
```

(Referensi: `scoring.py::scorecard_score` / `base_ai_status`; mirror di `stats.py`.)

### 4.3 Zero-Score Rule

Bila **tidak ada** minat (Cashline maupun MUS) → `campaign_interest = []` →
`ai_score_phase_2 = 0`, `ai_score_phase_3 = 0`, `ai_status = FAIL`.

### 4.4 Veto Non-Tolerable (paksa FAIL)

`has_blocking_intolerable_item`: bila ada item scorecard **`tolerable = "NO"`** yang masih
**`BELUM_SESUAI`**, status **dipaksa FAIL berapa pun skornya**. Veto ini diterapkan oleh
pemanggil (`stats.py`), bukan di `scoring.py`.

---

## 5. Verifikasi Data

### 5.1 Card Holder (Ascend)

- **2 field statik**: `tanggal_lahir`, `nama_ibu_kandung`.
- **9 field dinamik** (KB_CL_24 / VD_1..VD_9): `alamat_pengiriman_tagihan`, `alamat_rumah`,
  `no_telpon_terdaftar`, `alamat_kantor`, `no_telpon_kantor`, `alamat_email_terdaftar`,
  `nama_kartu_suplement`, `jumlah_kartu_suplement`, `nama_keluarga_relasi`.
- **Aturan "cukup 2 match"**: minimal **2 dari 9** field dinamik ter-verifikasi
  (`CARD_HOLDER_DYNAMIC_REQUIRED = 2`). Field dihitung bila `match == MATCH` **atau** `event_verified`.

> **Penting (v33+):** penalti card holder = **0** untuk `ai_score_verification`. Kegagalan
> verifikasi dinyatakan lewat item **scorecard**: statik gagal → `SC_CL_23_1`/`SC_CL_23_2`
> BELUM_SESUAI; dinamik < 2 match → `SC_CL_24` BELUM_SESUAI (menurunkan phase_2) — agar tidak
> double-counting. `_card_holder_address_group_score` selalu mengembalikan 0.
> Mekanismenya diuraikan di **Propagasi** di bawah.

#### Grey band → minta dokumen (bukan langsung salah)

Field statik yang **hampir** cocok bukan MATCH bersih dan bukan kesalahan agent: bank
meminta dokumen pendukung. Selama dokumen belum ada, tiket **PENDING** (`compliance/documents.py`):

| Field | MATCH bersih | Grey band → dokumen | MISMATCH (error agent) |
|---|---|---|---|
| `nama_ibu_kandung` | ≥ 90 | 80 .. < 90 → **KK** | < 80 |
| `tanggal_lahir` | = 100 | 87.5 .. < 100 → **KTP** | < 87.5 |

Batas bawah band **sama** dengan batas MISMATCH pada prompt, sehingga keputusan LLM sejalan
dengan tabel ini. Mengubah ambang berarti mengubah keduanya bersamaan.

> **Cutoff retroaktif:** band hanya berlaku untuk result dengan
> `uploaded_at >= CARD_HOLDER_DOC_BANDS_EFFECTIVE_FROM` (**2026-08-06 07:00 WIB**). Tanpa
> cutoff, tiket lama yang jendela unggahnya sudah lama tutup akan berbalik
> Qualified → Not Qualified seketika tanpa bisa ditindaklanjuti siapa pun.

#### Similarity & reason dihitung ulang di Python

`error_codes.py::normalize_static_verification` **tidak mempercayai angka LLM** untuk kedua
field statik. Dipanggil di **semua** jalur baca (detail tiket, daftar Results, XLSX,
agent error, agregat Statistics), jadi dashboard/export selalu memakai angka yang sama.

| Tahap | Yang dilakukan |
|---|---|
| 1. Hitung ulang | Levenshtein ternormalisasi (`compliance/static_similarity.py`). Nama dibulatkan ke bilangan bulat; tanggal lahir dihitung atas bentuk baku `DDMMYYYY` dan **tidak** dibulatkan (87,5 tetap 87,5) |
| 2. Penyebutan terbaik | Setiap elemen `extracted_mentions` **plus** nilai pilihan LLM diadu ke Ascend; similarity tertinggi menang, seri dimenangkan penyebutan **paling baru** |
| 3. Tegakkan band | `match` diset ulang dari tabel di atas, bukan dari vonis LLM |
| 4. Tulis ulang `reason` | Baris yang angkanya berubah mendapat kalimat deterministik: nilai disebut, nilai Ascend, persentase, tindak lanjut |

Kenapa perlu: angka LLM terbukti meleset — "ARNIYETTI" vs "Sarieti" pernah dilaporkan 44%
padahal 56%, dan selisih sebesar itu memindahkan tiket melewati ambang 80 / 87,5. Tahap 4
ditambahkan **13 Agustus 2026**: sebelumnya `match` dan `similarity_percent` dikoreksi tetapi
`reason`-nya tetap kalimat LLM untuk vonis lama, sehingga tiket bisa berbunyi *"masih di atas
ambang match Ascend"* tepat di sebelah kolom Match yang berbunyi **MISMATCH** — dan kalimat
itu ikut terbawa ke kolom Reason tabel Error Code.

Dua larangan kata dipatuhi kalimat baru itu, keduanya punya konsekuensi mesin:

- **zona abu-abu tidak memakai "sesuai"/"cocok"** — nilainya memang belum sama, itu justru
  sebabnya dokumen diminta;
- **"tidak konsisten"/"inkonsisten" tidak pernah dipakai** — frasa itu penanda kegagalan
  tahap 1 yang dibaca `_reason_says_inconsistent`, jadi menuliskannya akan salah memvonis
  tiket sebagai indikasi fraud.

> **Baris yang gugur tahap 1 tidak disentuh sama sekali.** Pada baris itu
> `similarity_percent` berisi kemiripan **antar-penyebutan nasabah**, bukan terhadap Ascend
> (lihat §7 baris 2b). Membacanya sebagai nilai band akan "menyelamatkan" tiket yang justru
> gagal karena jawabannya berubah-ubah. Dikenali dari bendera `consistency_failed` (prompt
> v52) **dan** teks alasannya — hasil lama belum punya bendera itu.

#### Propagasi: verifikasi → scorecard → critical compliance

Kegagalan verifikasi tidak berhenti di tabel verifikasi; ia menuruni tiga tingkat:

```
card_holder_verification MISMATCH
        │  _propagate_verification_to_scorecard
        ▼
scorecard SC_CL_23_1 / SC_CL_23_2 BELUM_SESUAI  (item_score 0 → phase_2 turun)
        │  _sync_critical_compliance   (SC_CL_23_x termasuk item kritis)
        ▼
critical_compliance_check entry FAIL  → satu iris −(maximum_score / 4)
```

`SC_CL_24` (dinamik < 2 match) ikut diturunkan di langkah pertama, tetapi **bukan** item
kritis sehingga tidak memicu iris beku. Propagasi hanya pernah **menurunkan**; memulihkan
item ke SESUAI adalah wewenang banding.

Keduanya berjalan lewat `apply_added_score_appeals`, sesudah semua banding diterapkan —
sehingga banding B17 yang disetujui (MISMATCH → MATCH) menang atas propagasi.

Ketiga tingkat memakai **satu sumber kalimat**, `static_verification_failure_reason`, agar
tidak ada permukaan yang berbunyi lain: `reason` item scorecard ditulis ulang saat item itu
dipaksa turun (tanpa itu tabel Scorecard berbunyi BELUM_SESUAI dengan alasan yang justru
menyatakan item terpenuhi), dan entri critical compliance mendapat kalimat yang sama dari
`annotate_critical_compliance_reasons`, yang jalan **sesudah** propagasi di jalur baca.

> **Diperbaiki 13 Agustus 2026.** Sebelumnya kedua langkah ikut terjaga di balik
> `if not added_appeals: return` — jadi hanya jalan pada tiket yang kebetulan punya banding
> `add`, yakni minoritas. Akibatnya pada mayoritas tiket sebuah field statik MISMATCH
> **tidak pernah** menurunkan SC_CL_23_x: tiket menampilkan B17 di tabel Error Code
> sementara skornya utuh dan AI Status-nya tetap PASS — error yang terlihat tapi tidak
> pernah dipotong. Perbaikan ini menurunkan skor **3 dari 98** tiket tersimpan (semuanya
> `SC_CL_23_2`), **2** di antaranya berpindah PASS → Not Qualified.

Nilai per tiket untuk `nama_ibu_kandung` bisa ditarik lewat `GET /get_nama_ibu_kandung`
(lihat [`API_REFERENCE.md`](./API_REFERENCE.md) §5.2).

### 5.2 Cashline Data — penalti per field MISMATCH

Ditambahkan ke `ai_score_verification` (negatif):

| Field | Penalti | Field | Penalti |
|---|---|---|---|
| `nominal_pencairan` | −1 | `nama_bank` | −2 |
| `tenor_dalam_bulan` | −1 | `penalti_pelunasan_dipercepat` | −2 |
| `nominal_cicilan_per_bulan` | −1 | `nomor_rekening` | −2 |
| `bunga` | −1 | `nama_pemilik_rekening` | −2 |
| `provisi` | −4 | `biaya_admin` | −5 |

Kode error yang muncul: **B02/B03/B05** (risk-graded per field). Lihat [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md).

---

## 6. Critical Compliance Check

4 item kritis: **`SC_CL_4`, `SC_CL_23_1`, `SC_CL_23_2`, `SC_CL_37`**. Setiap item **FAIL**
mengurangi `−(maximum_score / 4)`. Rentang total: 0 s/d `−maximum_score`.

Contoh: maximum_score 150, 2 item kritis FAIL → `2 × −(150/4) = −75.0`.

**Setiap item kritis yang BELUM_SESUAI wajib berentri `FAIL`.** `_sync_critical_compliance`
menegakkan itu di setiap jalur baca, tanpa membedakan asal kegagalannya — banding `add` dari
QC, MISMATCH temuan LLM, dan MISMATCH hasil hitung ulang Python (§5.1) memicu iris beku yang
sama. Fungsi ini no-op bila semuanya sudah selaras, dan hanya membalik `PASS → FAIL`
(pemulihan adalah wewenang banding), jadi menjalankannya berulang tidak menggandakan hukuman.

> Karena `SC_CL_23_1`/`SC_CL_23_2` sekaligus item kritis **dan** `tolerable: NO`, satu field
> statik yang MISMATCH memukul tiket dari tiga arah: bobot item hilang dari phase_2, satu
> iris `−(maximum_score/4)` masuk ke phase_3, lalu veto non-tolerable (§4.4) mengunci
> statusnya ke FAIL. Contoh nyata (tiket `020338gGlU`, maximum_score 108.75):
> `phase_2 108,75 → 93,75`, iris kritis `−27,1875`, `phase_3 = 66,5625` — jauh di bawah
> passing grade 97,88.

---

## 7. Status Akhir: Urutan Precedence

Skor **selalu** dihitung apa adanya (kolom AI Score, tabel Error Code, dan Ringkasan
Kategori harus jujur). Yang dikunci hanyalah **status**. Urutan di `api/routers/stats.py`
(aturan 7 Agustus 2026):

| # | Aturan | Hasil |
|---|---|---|
| 1 | Veto non-tolerable (§4.4) | `PASS → FAIL` |
| 2 | **Kekurangan dokumen wajib** | dalam tenggat H+2 → **PENDING**; lewat tenggat → **FAIL** |
| 2b | **Indikasi fraud** — penyebutan nasabah tidak konsisten antar pengulangan (gugur tahap 1 verifikasi statik) | **FAIL**, menimpa PENDING (tiket ber-indikasi fraud tidak menunggu dokumen) |
| 2c | **Badword** — agent mengucapkan kalimat bersentimen negatif kepada nasabah (prompt v53+) | **FAIL**, menimpa PENDING, tidak peduli skor |
| 3 | **Manual Status yang sudah disetujui** | otoritas final, menimpa semua di atas |

Bila 2b dan 2c kena bersamaan, **keduanya** ditulis di kolom AI Status dipisah ` · ` — QC
perlu tahu tiketnya gugur karena dua sebab, bukan satu.

### 7.1 AI Status dihitung, tidak pernah disimpan

**Tidak ada kolom `ai_status` di satu pun tabel.** Status dihitung ulang setiap request oleh
`compliance/stats_aggregate.py::_result_ai_status`, dari empat sumber sekaligus:

| Sumber | Perannya |
|---|---|
| `result_data.result_json → evaluation` | skor mentah LLM + `passing_grade` + `badword_check` |
| `error_code_appeals` | banding disetujui → skor disesuaikan sebelum dinilai |
| `qc_status_requests` | Manual Status disetujui → **mengunci** status (aturan 3) |
| `documents` + `tms_cashline.submit_time` | dokumen kurang & tenggat H+2 (aturan 2) |

Ini **desain, bukan utang teknis**. Vonis adalah fungsi murni atas data mentah **plus aturan
yang berlaku sekarang** — dan aturan itu berubah tiga kali dalam dua minggu (7, 10, 13 Agustus
2026). Kalau statusnya di-materialize, setiap perubahan aturan wajib disertai backfill; lupa
sekali saja, DB dan dashboard bercerita beda. Status juga bergantung **waktu berjalan**: tiket
berpindah PENDING → FAIL semata-mata karena tenggat H+2 lewat, tanpa satu baris pun berubah.

> ⚠️ **Jangan pernah query `result_json->'evaluation'->>'ai_status'` untuk laporan, export,
> atau integrasi.** Field itu tebakan LLM saat pemrosesan pertama dan **tidak pernah ditulis
> ulang** — `save_result_data` hanya `INSERT`, tidak ada `UPDATE` ke `result_data` di seluruh
> repo, dan `_adjusted_evaluation` bekerja pada salinan di memori. Pengukuran 14 Agustus 2026:
> **29 dari 98 tiket (30%) menyimpang**, seluruhnya tersimpan `PASS` padahal vonisnya `FAIL`.
> Penyimpangannya selalu ke arah yang sama — terlalu longgar — karena semua aturan yang
> menambah kegagalan lahir **sesudah** penilaian LLM. Prompt sendiri menyatakannya:
> *"ai_status is NOT computed here. It is computed LATER."*

Yang benar: `ai_status_for_result(db, result)` untuk satu tiket, atau endpoint `/list_results`.
Keduanya sengaja tidak mempercayai nilai kiriman klien — bila bisa dikarang, alur banding bisa
dilewati hanya dengan mengubah satu field di request.

### 7.2 Export XLSX mengikuti vonis kanonik (14 Agustus 2026)

Sheet `ringkasan_penilaian_ai` (`GET /export_result_xlsx/{id}`) dulu menyimpulkan sendiri baris
**"Hasil"** dari dict evaluasi saja. Karena dict itu tidak membawa akses DB, dua aturan
precedence tak pernah terlihat olehnya — **aturan 2** (dokumen + tenggat H+2) dan **aturan 3**
(Manual Status disetujui). Akibatnya **21 dari 98 tiket ter-export "LULUS" padahal daftar
Results memvonisnya Not Qualified**, seluruhnya karena dokumen wajib lewat tenggat; sheet itu
juga mustahil berbunyi PENDING.

Sekarang `export_result_xlsx` mengambil vonis dari `ai_status_for_result(db, result)` — helper
yang **sama persis** dengan kolom AI Status di Results — lalu mengopernya ke
`_append_ringkasan_rows`. Helper lama `_ai_status_pass` dihapus supaya tidak ada jalur kedua
yang bisa menyimpang lagi. Verifikasi: 98/98 tiket cocok (sebelumnya 77/98).

**Setiap sebab gugur yang tidak terbaca dari angka wajib punya barisnya sendiri**, tepat sebelum
baris "Hasil" — kalau tidak, ekspor bertuliskan "TIDAK LULUS" dengan skor di atas batas lulus
terbaca persis seperti salah hitung:

| Baris | Muncul bila |
|---|---|
| `Tidak dapat ditoleransi — <alasan>` | veto non-tolerable (aturan 1) — satu baris per item |
| `Menunggu dokumen pendukung (SLA H+2)` | dokumen kurang, masih dalam tenggat → PENDING |
| `Dokumen pendukung tidak diunggah sampai tenggat (SLA H+2)` | dokumen kurang, tenggat lewat → FAIL |
| `Indikasi fraud …` | aturan 2b |
| `Terindikasi Badword …` + satu baris per ucapan | aturan 2c |

Baris non-tolerable adalah celah lama yang ikut ditutup: bobot itemnya memang sudah muncul
sebagai pengurangan di bagian scorecard, tetapi angka itu tidak menjelaskan apa pun — yang
menggugurkan bukan besarnya pengurangan melainkan sifat **tidak dapat ditoleransi**-nya.
Contoh nyata: skor akhir 148 dari batas lulus 135, hasilnya TIDAK LULUS.

### Badword — ucapan agent bersentimen negatif (13 Agustus 2026)

Ditambahkan setelah analisis 10 komplain nyata (`Data Komplain penawaran tidak sopan.xlsx`,
Fault Category *Sales Fault*). Temuannya: yang dikeluhkan nasabah **hampir tidak pernah kata
kasar baku**, melainkan kalimat agent yang merendahkan, menyindir, menyalahkan, atau
menggerutu — sering diucapkan **sesudah** nasabah menolak.

Karena ini soal **sentimen**, bukan pencocokan daftar kata, deteksinya dikerjakan LLM
(prompt v53 §`BADWORD DETECTION RULE`, output blok `badword_check`). `compliance/badwords.py`
hanya membaca, menormalkan, dan menjadikannya vonis.

| Aspek | Aturan |
|---|---|
| Siapa dinilai | **hanya agent**; peran ditentukan dari isi ucapan, bukan label diarization (sering tertukar) |
| Sasaran | wajib **kepada nasabah**. Gerutuan tentang rekan kerja, sistem, bank, atau "orang pada umumnya" **bukan** temuan (v54) |
| Bukti | kutipan verbatim + timestamp + `ticket_id`. **Temuan tanpa kutipan dibuang** — `has_badword` dihitung dari baris berbukti, bukan dari `badword_check.status` |
| Ambang | tandai hanya bila pendengar wajar tersinggung; **bila ragu, jangan ditandai** |
| Efek skor | **tidak ada**. Semua `ai_score_*` tetap dihitung apa adanya; hanya STATUS yang dikunci |

> **Vonis tanpa bukti tidak boleh berdiri.** Tabel ini menuduh seorang agent berucap tidak
> pantas dan vonisnya mengunci AI Status, jadi temuan tanpa kutipan yang bisa dibaca QC
> dibuang diam-diam. Baris kembar (timestamp + kutipan sama) dilipat jadi satu.

Permukaannya: tabel **Badword Summary** di dropdown Results (di bawah Agent Error Summary,
disuplai `/agent_error_summary/{id}`), komentar **"Terindikasi Badword — N ucapan…"** di
kolom AI Status, dan sheet `ringkasan_penilaian_ai` pada export XLSX (baris "Hasil" menjadi
**TIDAK LULUS**, didahului baris alasan + satu baris per ucapan). Baris alasan itu wajib:
skornya bisa berada **di atas** batas lulus sementara hasilnya tidak lulus, dan tanpa
keterangan ekspornya terbaca seperti salah hitung.

> **Hasil lama tidak berubah.** Evaluasi sebelum v53 tidak punya blok `badword_check`; semua
> helper mengembalikan kosong, jadi tabelnya berbunyi "✓ Tidak ada badword" dan status tiket
> lama tetap. Tiket lama hanya terdeteksi bila **dievaluasi ulang** dengan prompt v53+.

Dokumen wajib dipicu oleh **perubahan data TMS**, **limit ≥ 50 juta** (NPWP), atau **grey
band card holder** (§5.1).

### Tenggat H+2 (SLA unggah dokumen)

- **"H+2" = 48 jam sejak `tms_cashline.submit_time`** (`SLA_HOURS = 48`).
- Selama tenggat belum lewat & dokumen belum diunggah → **PENDING**; setelah lewat → **FAIL**
  (Not Qualified).
- `submit_time` kosong/tak terbaca → dianggap **sudah lewat** (tidak ada masa tenggang yang
  bisa dibuktikan).
- Timer live-nya tampil di menu **Pending Check** (`SLA_HOURS` di `ResultsView.vue`;
  hijau → kuning < 12 jam → merah lewat tenggat).
- Sejak 14 Agustus 2026 tiket yang lewat tenggat tanpa dokumen juga **menerbitkan error code
  B09** (Risk Base `M`) — sebelumnya ia jadi Not Qualified tanpa error code apa pun sehingga
  di tally Risk Base jatuh ke `O`. Dokumen yang diunggah tetapi **salah jenis** tidak dianggap
  memenuhi kewajiban: ia menerbitkan **C03** dan tiketnya tetap bisa jatuh ke B09. Lihat
  [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) §5.1.

**Sakelar:** `compliance/stats_aggregate.py::DOC_SLA_ENABLED`.

| Nilai | Perilaku |
|---|---|
| `True` (**aktif sekarang**, sejak 12 Agustus 2026) | aturan berlaku penuh |
| `False` | tenggat dianggap **tidak pernah lewat** → tiket kekurangan dokumen tetap PENDING selamanya |

Sempat dimatikan 11 Agustus 2026 supaya status PENDING bisa diuji (semua data uji sudah jauh
melewati tenggatnya sehingga PENDING tak pernah muncul di layar). Satu baris itu adalah
**satu-satunya** yang perlu diubah — semua pembaca lewat `_doc_sla_expired()`, dan teks alasan
"(SLA H+2)" di `stats.py` ikut mengikuti flag yang sama.

> ⚠️ Mengubah sakelar ini **tidak** meng-invalidate cache snapshot Statistics (signature-nya
> berbasis data, bukan kode). Jalankan `POST /stats/refresh` sesudahnya — lihat
> [`RUNBOOK.md`](./RUNBOOK.md) §11.

---

## 8. Ringkasan Alur Evaluasi

```
Transkrip PDF ─► LLM (prompt + KB[+RIPLAY] + scorecard + reference data)
                    │
                    ▼
   JSON evaluasi: scorecard_result, card_holder_verification,
                  cashline_data_verification, critical_compliance_check,
                  badword_check (v53+), campaign_interest, maximum_score,
                  passing_grade,
                  ai_score_phase_2/verification/critical/phase_3, ai_status
                    │
                    ▼
   normalize_static_verification ─► similarity/match/reason statik dihitung ulang (§5.1)
                    │
                    ▼
   banding disetujui diterapkan ─► propagasi verifikasi → scorecard → critical (§5.1)
                    │
                    ▼
   scoring.py / stats.py (mirror deterministik) ─► skor
                    │
                    ▼
   precedence §7 (veto → dokumen/H+2 → fraud → badword → Manual Status) ─► status final
                    │
                    ▼
   build_error_code_table ─► tabel Error Code (+ banding/appeal diterapkan)
```

Reference data (TMS Cashline + Ascend card holder) di-append ke scorecard sebelum evaluasi
(`build_reference_data`), sehingga LLM membandingkan transkrip vs data acuan.

---

## 8.1 Error Rate: Satu Rumus untuk Seluruh Dashboard (14 Agustus 2026)

Sebelumnya halaman Statistics memakai **dua** definisi Error Rate yang bersebelahan tanpa
penjelasan: KPI Overview dan pohon Hierarki memakai *Not Qualified ÷ tiket dinilai*,
sementara tabel Performa Campaign memakai *Total Risk ÷ Submission*. Angka yang seharusnya
menjawab pertanyaan sama tidak pernah cocok. Sekarang **satu rumus** berlaku di semua panel:

```
Error Rate = Total Risk (H + M + L) ÷ Submissions
```

Implementasi: `_rate_of()` di `compliance/stats_aggregate.py`.

**Satu risk base tertinggi per tiket.** Berapa pun error code yang dikandung sebuah tiket, ia
menyumbang **paling banyak 1** ke H/M/L (urutan H > M > L > N > O), jadi rasionya tidak pernah
melewati 100%. Fungsinya: `top_risk_base(rows, evaluation)`. `N` (new joiner) dan `O` (System)
di luar Total Risk — keduanya bukan kesalahan yang dibebankan ke agent.

**Yang memakai rumus ini:**

| Panel | Sebelumnya |
|---|---|
| KPI **Error Rate** di Overview (global & per campaign) | Not Qualified ÷ dinilai |
| KPI **Error Rate** ter-scope (Sales Agent / Team Leader) | Not Qualified ÷ dinilai |
| **Performa Sales** (global & per campaign) | Not Qualified ÷ submissions |
| **Performa Campaign** — month to month | *(sudah memakai rumus ini)* |
| **Hierarki Error Rate** — AM → TL → Agent | Not Qualified ÷ submissions |
| **Daftar Sales Agent Tim Anda** & hierarki ter-scope AM | Not Qualified ÷ submissions |

**Yang sengaja TIDAK ikut**, karena mengukur hal lain:

- **Daftar QC** — mengukur beban & hasil kerja QC, bukan kesalahan sales.
- **Breakdown Manual Status** — vonis human tidak punya risk base sama sekali.
- **Tab Failure Reason** — mengukur kegagalan kategori scorecard, bukan risk base.
- **Chart "AI Status — per waktu"** — komposisi status yang harus berjumlah 100%.

**Kolom `Errors` tetap ditampilkan** di Hierarki & Performa Sales (jumlah tiket Not
Qualified) meski bukan lagi pembilang. Ia tetap informasi yang dicari pengawas; yang berubah
hanya persentasenya. Payload `overview` membawa `total_risk` terpisah dari `error_count`
supaya KPI bisa menuliskan pecahannya apa adanya ("72 total risk / 98 dinilai").

### Pengecualian L-tolerable

Bila risk base tertinggi sebuah tiket adalah **`L`** dan **setiap** baris `L`-nya menempel
pada item scorecard ber-`tolerable: YES`, tiket itu **tidak menyumbang risk base sama sekali**
(`top_risk_base` mengembalikan `None`).

Alasannya: pelanggaran seperti itu tidak membuat tiket Not Qualified — agent yang hanya gagal
di Greeting (B12, `SC_CL_1/2/3`, semuanya `tolerable: YES`) tetap Qualified. Memasukkannya ke
Total Risk berarti Error Rate menghukum kesalahan yang sistem sendiri maafkan.

Yang **tidak** ikut dikecualikan, dan itu disengaja:

- `L` dari verifikasi data (**B02**) — tidak punya `item_code`, jadi tidak punya `tolerable`.
  Salah input data tetap salah input data.
- Tiket yang risk base tertingginya `M`/`H`, walau kebetulan juga mengandung `L` yang
  tolerable — yang dihitung tetap yang tertinggi.

> ⚠️ Mengubah rumus ini **tidak** meng-invalidate cache snapshot Statistics. Wajib
> `POST /stats/refresh` sesudah deploy — lihat [`RUNBOOK.md`](./RUNBOOK.md) §11.

---

## 9. Cara Mengubah Aturan Penilaian (checklist)

1. Edit **prompt.txt** (aturan/scoring) dan/atau **scorecard.txt** (item/bobot/tolerable)
   dan/atau **KB** / **RIPLAY**.
2. Upload ulang via dashboard (Upload Campaign) — DB & MinIO ter-update, `is_active=True`.
3. **Proses ulang** tiket sampel (hapus + upload ulang; lihat [`RUNBOOK.md`](./RUNBOOK.md) §7).
4. Bandingkan skor/status sebelum-sesudah pada 1 tiket untuk memastikan efeknya benar.
5. Simpan versi baru + CHANGELOG di `campaign_cashline/`, dan perbarui salinan di `docs/`.

> Perubahan pada `compliance/*.py` (mirror Python, ambang band, sakelar SLA) **perlu**
> `docker compose restart api worker`; perubahan prompt/scorecard/KB **tidak** (dibaca fresh
> dari DB tiap task).

---

## Referensi terkait
- [`ERROR_CODE_CATALOG.md`](./ERROR_CODE_CATALOG.md) — katalog kode & banding
- [`INTEGRATION.md`](./INTEGRATION.md) — bagaimana transkrip diproses (worker + LLM)
- [`RUNBOOK.md`](./RUNBOOK.md) — proses ulang tiket, sakelar SLA, refresh snapshot
- Artefak campaign aktif di `docs/`: `prompt_cashline_mus_v54.txt`, `cashline_kb_v21.txt`, `cashline_scorecard_v3.txt`
