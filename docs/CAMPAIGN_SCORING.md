# Campaign & Model Scoring — Telemarketing QC System

Menjelaskan **konfigurasi campaign** (prompt / knowledge base / scorecard / RIPLAY) dan
**cara skor QC dihitung** hingga menjadi status **PASS / FAIL / PENDING**. Ini adalah
pengetahuan inti untuk merawat logika QC.

Sumber: `compliance/scoring.py`, `compliance/error_codes.py`, `compliance/stats_aggregate.py`,
`compliance/documents.py`, `compliance/riplay.py`, `api/routers/campaign.py`,
`api/routers/stats.py`.

> **Prinsip penting:** logika penilaian sesungguhnya ada di **prompt LLM** (disimpan di DB,
> kolom `campaigns.prompt_text`). `compliance/scoring.py` adalah **mirror deterministik** dari
> perhitungan tersebut agar dashboard/export konsisten. Mengubah aturan penilaian = mengubah
> **prompt/scorecard**, lalu upload ulang campaign (tanpa rebuild/restart).

---

## 1. Konfigurasi Campaign

Setiap campaign punya 3 file `.txt` mentah (diberikan ke LLM apa adanya, tanpa parsing JSON)
plus **RIPLAY** PDF opsional.

| Berkas | Isi | Versi aktif (12 Agustus 2026) |
|---|---|---|
| **prompt.txt** | Instruksi/sistem prompt LLM — seluruh logika evaluasi & scoring | `prompt_cashline_mus_v52.txt` (~124 KB) |
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
2. Endpoint: `POST /upload_detail_campaign` (multipart: `scorecard`, `knowledge_base`,
   `prompt`, `campaign`, `riplay` opsional).
3. **Guard: `admin.campaign.write`** (SPQ Head / Admin). Endpoint ini dulu terbuka untuk
   semua user login — sudah diperketat, karena menimpanya berarti menimpa seluruh aturan QC.
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
| 3 | **Manual Status yang sudah disetujui** | otoritas final, menimpa semua di atas |

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
                  campaign_interest, maximum_score, passing_grade,
                  ai_score_phase_2/verification/critical/phase_3, ai_status
                    │
                    ▼
   scoring.py / stats.py (mirror deterministik) ─► skor
                    │
                    ▼
   precedence §7 (veto → dokumen/H+2 → fraud → Manual Status) ─► status final
                    │
                    ▼
   build_error_code_table ─► tabel Error Code (+ banding/appeal diterapkan)
```

Reference data (TMS Cashline + Ascend card holder) di-append ke scorecard sebelum evaluasi
(`build_reference_data`), sehingga LLM membandingkan transkrip vs data acuan.

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
- Artefak campaign aktif di `docs/`: `prompt_cashline_mus_v52.txt`, `cashline_kb_v21.txt`, `cashline_scorecard_v3.txt`
