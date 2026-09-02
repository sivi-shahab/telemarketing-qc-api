# Review Merge `main` → `dev` (2 September 2026)

Status: **semua konflik sudah di-resolve dan di-stage** (lihat §7). Keputusan §3.3(b)
= **rumus `dev`** (Avg Failure Rate = Total Failure ÷ Not Qualified). Merge belum
di-commit — tinggal `git commit`.

```
merge base : 8732836  Weekly Update 28 Agustus 2026
dev  (HEAD): 59f868e  feat(rbac): login campaign Collection ...      (26 commit)
main       : e8a634e  Daily Update 2 September 2026                   (1 commit besar)
```

Konflik: `api/routers/agent_error.py`, `api/sales_lookup.py`,
`compliance/stats_aggregate.py`, `dashboard/src/views/dashboard/ResultsView.vue`,
`dashboard/src/views/dashboard/StatsView.vue`, `db/crud.py`.

---

## 1. Ringkasan keputusan

| # | Perkara | Jenis | Siapa yang harus memutuskan |
|---|---------|-------|------------------------------|
| A | Rumus Failure Rate di Hierarki: **`_avg` (dev)** vs **`_rate` per transkrip (main)** | **Keputusan bisnis** | Anda / SPQ Head |
| B | Parser roster: inline di `api/sales_lookup.py` (dev) vs `compliance/sales_roster.py` (main) | Teknis — jawabannya sudah pasti | — |
| C | `agent_error.py`: snapshot-first (dev) vs `name_online` (main) | Teknis — keduanya harus masuk | — |
| D | `crud.py` versi signature: dua-duanya klaim `v19` | Teknis — naikkan ke `v21` | — |
| E | 3 konflik lain (Vue + satu blok stats) | Teknis — salah satu sisi akan **error runtime** kalau salah pilih | — |

Hanya **A** yang benar-benar butuh keputusan Anda. Sisanya punya jawaban yang
"benar" secara teknis dan saya jabarkan di bawah.

---

## 2. Apa yang dibawa `main` (di luar konflik)

Satu commit `Daily Update 2 September 2026`: **+3224 / −339** baris, 32 berkas.
Empat fitur besar:

### 2.1 Kepemilikan panggilan — `compliance/call_ownership.py` (BARU, 309 baris)
Satu ticket id bisa berisi PDF dari **beberapa agent**, padahal TMS hanya
meng-assign tiket itu ke **satu** agent. Sebelum ini semua PDF digabung jadi satu
percakapan, sehingga evidence scorecard bisa diambil dari panggilan agent lain
(contoh yang dikutip: tiket `180107uT48` — 4 item dinilai dari panggilan "Desi",
padahal tiketnya milik "ELVIN"/`nurha801`).

Cara kerjanya: nama yang diperkenalkan agent di pembuka panggilan diadu **fuzzy**
ke kolom **NAME ONLINE** roster. Dua syarat wajib sebelum sebuah panggilan dibuang:
1. nama agent TMS harus muncul di minimal satu panggilan tiket itu;
2. nama pada panggilan yang dibuang harus persis 100% sama dengan NAME ONLINE
   orang lain di roster.

Tanpa syarat (1) aturan ini akan menyentuh 74 dari 98 tiket — hampir semuanya keliru.

Konsumennya: `worker/tasks/process_transcript.py` langkah **2b** (baru), field
`excluded_calls` di `api/schemas/result.py`, dan kolom Call Duration di
`ResultsView.vue` (PDF yang dibuang tetap ditampilkan, dicoret + diberi label
agent-nya, supaya tidak "lenyap diam-diam").

### 2.2 `compliance/sales_roster.py` (BARU, 143 baris)
Pembacaan sheet roster dipindah dari `api/sales_lookup.py` ke `compliance/`
supaya **worker** bisa memakainya tanpa menarik FastAPI. Menambah kolom
**NAME ONLINE** (kolom E). `worker/requirements.txt` +`openpyxl`.

### 2.3 Penyebut Failure Rate pindah ke jumlah transkrip
`_transcript_count()` + akumulator `transcripts` di seluruh
`compliance/stats_aggregate.py`. "Submissions" pada pohon Hierarki kini berarti
**jumlah PDF yang dinilai**, bukan jumlah tiket; kolom **Tiket** (`ticket_count`)
dipisah. Ini yang bertabrakan langsung dengan pekerjaan `dev` — lihat §3.3.

### 2.4 Lain-lain
- `compliance/error_codes.py` **+666 baris**, `compliance/scoring.py` **+177**:
  kolom **SCOREBOMB** — `score_bomb_items` menggabungkan pelanggaran kritis (iris 25%)
  dan item non-tolerable lain (iris 10%). Sebelumnya iris 10% memotong skor tanpa
  pernah terlihat di layar mana pun.
- Migrasi `0050` (cabut menu antrean QC dari SPQ Head, 1 Sep) lalu `0051`
  (kembalikan lagi, 2 Sep). Netto: tidak berubah — hanya jejaknya yang tertinggal.
- Prompt `v74 → v79` + KB `v34 → v35`, plus 3 berkas changelog.
- `LoginView.vue`, `RoleHierarchyView.vue`, `EvaluationView.vue`, `AgentErrorTable.vue`,
  `api/qc_scope.py`, `api/routers/document.py`, `compliance/pdf_parser.py`
  (`call_duration`, `transcript_plain_text`).

---

## 3. Konflik satu per satu

### 3.1 `db/crud.py` (1 konflik, baris 823) — **kedua sisi memakai `v19`**

| | isi |
|---|---|
| dev | `v19` = snapshot-first submit_time/agent_id, `v20` = Avg Failure Rate → `version = "v20"` |
| main | `v19` = daftar tiket tersembunyi ikut menentukan snapshot → `version = "v19"` |

Dua perubahan berbeda memakai nomor yang sama. Kalau salah satu sisi diambil
mentah-mentah, satu kelompok cache lama **tidak akan gugur** dan Statistics akan
menyajikan angka basi tanpa gejala apa pun (ini persis jebakan yang sudah pernah
kena: ubah rumus, angka di layar tidak berubah).

**Rekomendasi:** gabung catatannya, tulis ulang catatan main sebagai `v21`, dan
set `version = "v21"`. Menaikkan nomor itu murah; salah nomor mahal.

### 3.2 `api/sales_lookup.py` (2 konflik) — **wajib ambil sisi `main`, tapi porting `_person()`**

dev mempertahankan parser inline (`_norm`, `_person`, `_to_date`, `_PLACEHOLDERS`,
seluruh konstanta kolom); main menghapus semuanya dan memanggil
`parse_roster()` dari `compliance/sales_roster.py`.

**Sisi dev tidak bisa dipakai apa adanya** — auto-merge sudah menghapus
`import io` dan `from openpyxl import load_workbook` dari kepala berkas, jadi baris
133 (`load_workbook(io.BytesIO(data)…)`) akan `NameError` begitu ada yang membuka
halaman Results.

**Tapi sisi main juga tidak boleh diambil mentah.** `parse_roster()` membaca semua
kolom identitas lewat `norm()`, **bukan** `_person()`. Yang hilang kalau begitu:

- baris padding `USER ID = "0"` kembali menjadi satu "agent" hantu
  (main hanya `continue` saat uid kosong, dev juga membuang uid yang isinya `"0"`);
- placeholder `-`, `--`, `00000000`, `n/a`, `#N/A` kembali menjadi "orang" →
  dropdown **Semua AM** / **Semua TL** di Results memunculkan opsi bernama `-`;
- agent berstatus **MUTASI** (mis. EKO YULIONO, DINI HANDINI) kembali "punya atasan"
  bernama `-`.

Itu regresi yang sudah dijaga tes: `tests/test_sales_roster_placeholders.py`
(`test_padding_row_is_not_a_roster_entry`,
`test_mutasi_row_keeps_identity_but_drops_placeholder_hierarchy`,
`test_am_and_tl_dropdowns_list_names_only`) — ketiganya akan **gagal**.

**Rekomendasi:** ambil sisi main (hapus parser inline), lalu **pindahkan
`_PLACEHOLDERS` + `_person()` ke `compliance/sales_roster.py`** dan ganti `cell()`
di `parse_roster()` supaya memakainya, termasuk `uid = _person(r[uid_i])`.
Bonus: worker (§2.1) ikut kebal placeholder, yang memang seharusnya.

Catatan kecil: `scripts/seed_cashline_users.py` mengimpor `_norm` dari
`api.sales_lookup` — tetap aman, karena aliasnya masih ada di baris import.

### 3.3 `compliance/stats_aggregate.py` (6 konflik) — **1 blocker teknis + 5 keputusan bisnis**

#### (a) Blocker teknis — konflik di baris ~3004: **wajib sisi `main`**

```
HEAD : cid = _customer_id(r.source_files) ; cid_key = (cid or "").strip()   # duplikat
main : n_tx = _transcript_count(...) ; total_transcripts += n_tx
```

`cid`/`cid_key` **sudah** di-assign beberapa baris di atas oleh hasil auto-merge,
jadi sisi HEAD murni duplikat. Sementara `n_tx` dipakai di **baris 3058, 3084,
3088 dan 3137** yang semuanya lolos auto-merge. Ambil sisi HEAD → `NameError:
n_tx` setiap kali snapshot Statistics dibangun. Tidak ada pilihan di sini.

#### (b) Lima konflik sisanya — **rumus Failure Rate**

| baris | dev (HEAD) | main |
|---|---|---|
| 2622 | `_avg_of(acc, acc["errors"])` | `_rate_of(acc, transcripts)` |
| 2682 | `_avg(tl_risk, tl_err)` | `_rate(tl_risk, tl_tx)` |
| 2697 | `_avg(tot_risk, tot_err)` | `_rate(tot_risk, tot_tx)` |
| 3458 | `_avg_of(v, v["errors"])` | `_rate_of(v, transcripts)` |
| 3541 | `_avg_of(grand, total_err)` | `_rate_of(grand, _tx)` |

Dua definisi yang tidak kompatibel untuk angka yang sama:

- **dev** (commit `817fc29`, 2 Sep): *Avg Failure Rate* = **Total Failure ÷ Not
  Qualified**, ditulis sebagai **kelipatan** (mis. `4.5x`) — "rata-rata berapa
  pelanggaran per tiket yang gagal".
- **main** (31 Ags): *Failure Rate* = **Total Failure ÷ jumlah transkrip**,
  ditulis sebagai **persen** — "berapa persen panggilan yang bermasalah".

Keduanya sudah lengkap sampai ke UI: `_avg`/`_avg_of` dan `avgText`/`avgColor`/
`avgClassOf` ada di dev; `_rate`/`_rate_of` dan `rateText`/`rateColor` ada di
keduanya. `tests/test_hierarchy_avg_failure_rate.py` (9 tes) mengunci versi dev —
termasuk `test_avg_of_bukan_persen`.

**Ini yang harus Anda putuskan.** Tidak ada resolusi "gabung" yang jujur: satu
kolom hanya bisa punya satu penyebut.

- Kalau **dev menang**: ambil `_avg*` di 5 tempat itu, dan tetap ambil sisi main
  di (a). Pekerjaan `transcripts`/`ticket_count` dari main tetap terpakai untuk
  kolom **Submissions** & **Tiket** — hanya kolom rate-nya yang memakai penyebut
  Not Qualified. Wajib cek ulang catatan kaki di `StatsView.vue` (§3.5) supaya
  tidak menjanjikan dua rumus sekaligus.
- Kalau **main menang**: ambil `_rate*`, dan `tests/test_hierarchy_avg_failure_rate.py`
  harus dihapus/ditulis ulang, bukan dibiarkan merah. `_avg`/`_avg_of` dan
  `avgText`/`avgColor`/`avgClassOf` jadi kode mati — kecuali tabel Hierarki versi
  ter-scope (AM/TL, `StatsView.vue:141`) memang sengaja dibiarkan pakai `avg`.

Karena commit dev lebih baru (2 Sep, 10:41 vs 11:13) dan disertai tes + bump
signature, dugaan saya rumus dev-lah yang diminta terakhir — **tapi ini tetap
keputusan bisnis, bukan teknis.**

### 3.4 `api/routers/agent_error.py` (2 konflik) — **keduanya harus masuk**

- dev: `agent_id`/`submit_time` dibaca **snapshot `reference_data.cashline` dulu**,
  DWH live hanya kalau snapshot belum lengkap → Agent ID/Name/Tanggal tidak lagi
  `—` saat App A tidak menjawab, dan nol panggilan HTTP saat snapshot utuh.
  (dikunci `tests/test_agent_error_snapshot_first.py`, 7 tes)
- main: kolom **Name Online** + `entry.get("name_online")`, tanpa fallback ke agent_id.

**Bahaya:** sisi main memanggil `new_joiner_info(cashline_row, db)`, sedangkan
`cashline_row` **hanya ada di versi main** (dev menggantinya dengan `ref`/snapshot).
Ambil sisi main mentah-mentah → `NameError: cashline_row` setiap kali dropdown
Agent Error Summary dibuka. `grep` membuktikannya: satu-satunya kemunculan
`cashline_row` di berkas hasil merge adalah baris 161 itu sendiri.

**Rekomendasi resolusi:**
```python
agent_name = None
name_online = None
if agent_id:
    entry = active_sales_map(db).get(agent_id.casefold())
    if entry:
        agent_name = (entry.get("name") or "").strip() or None
        name_online = entry.get("name_online") or None
    if not agent_name:
        agent_name = _agent_name(agent_id)
nj = new_joiner_info({"agent_id": agent_id, "submit_time": submit_time}, db)
```
`new_joiner_info()` hanya membaca key `agent_id` dan `submit_time` dari dict yang
diberikan (baris 468–470), jadi bentuk panggilan dev tetap sah.

### 3.5 `dashboard/src/views/dashboard/StatsView.vue` (3 konflik) — ikut keputusan §3.3(b)

- KPI "All Telesales": label **AVG FAILURE RATE** + sub `… / not qualified` (dev)
  vs **Failure Rate** + sub `… / transkrip` (main).
- Dua blok catatan kaki di bawah tabel Hierarki: penjelasan rumusnya.

Catatan kaki versi main memuat penjelasan yang **tetap benar dan tetap berguna
walau rumus dev yang menang** (kolom **Tiket** vs **Submissions**; Qualified +
Pending + Not Qualified menjumlah ke Tiket, bukan Submissions; panggilan agent
lain tidak ikut dihitung). Jangan dibuang bulat-bulat — ganti kalimat rumusnya
saja, pertahankan paragraf penjelas kolomnya.

`StatsView.vue:141` (tabel Hierarki **ter-scope**, login AM/TL) memakai
`avgText`/`avgClassOf` di dev dan lolos auto-merge tanpa konflik. Kalau §3.3(b)
dimenangkan main, baris 141 akan jadi **satu-satunya** tempat yang masih `avg` —
inkonsistensi diam-diam antara tampilan SPQ Head dan tampilan AM/TL untuk kolom
yang sama. Harus ikut diseragamkan.

### 3.6 `dashboard/src/views/dashboard/ResultsView.vue` (3 konflik)

- **Baris 247** — `callDurations(group.primary)` (dev) vs `callDurations(item)` +
  `:class="{ 'cd-excluded': c.excluded }"` (main).
  dev sudah merombak tabel jadi baris ter-grup (`v-for="group in pagedGroups"`),
  jadi **`item` tidak ada di scope itu**. Ambil sisi main mentah → template error.
  Resolusi: `callDurations(group.primary)` **plus** binding `cd-excluded` dari main.
- **Baris 1580 & 1604** — `cccItems()` versi main (baca `score_bomb_items` dulu,
  fallback ke `critical_compliance_check`) + komentarnya. Ambil sisi **main**;
  perbedaan dev cuma `item?.` vs `item.`. Tanpa ini kolom SCOREBOMB (§2.4) tidak
  pernah muncul walau backend sudah mengirimnya.

Sisa plumbing-nya sudah aman: `callDurations()` (baris 1519–1539) dan CSS
`.cd-excluded` sudah masuk lewat auto-merge dan sudah membaca `excluded_calls`.

---

## 4. Yang lolos auto-merge tapi perlu dilihat

1. **`worker/tasks/process_transcript.py` langkah 2b** memanggil
   `crud.get_tms_cashline_by_result_id()` — yang di `dev` sudah berubah menjadi
   panggilan **DWH API**, bukan tabel `tms_cashline`. Saat pemrosesan berlangsung
   DWH hidup, jadi mestinya aman; tapi kalau App A tidak menjawab, `except`-nya
   mengembalikan `(None, None, ())` dan penyaringan panggilan **diam-diam tidak
   jalan** — tiket dua-agent lolos tanpa jejak selain satu baris log.
2. **`openpyxl` baru ditambahkan ke `worker/requirements.txt`.** Container worker
   harus di-**rebuild**, bukan sekadar restart, kalau tidak langkah 2b selalu
   masuk `except`.
3. **`MINIO_BUCKET_SALES_DATABASE`** dibaca worker lewat `os.getenv` dengan default
   `"sales-database"`. Sudah ada di `.env.example`; pastikan container worker
   di-**recreate** (bukan restart) supaya variabelnya terbaca.
4. **Migrasi `0050` + `0051`** saling meniadakan. Aman, tapi urutannya harus utuh —
   jangan cherry-pick salah satu saja.
5. `api/routers/stats.py` disentuh **kedua** sisi (main +100, dev +125) tanpa
   konflik. Berkasnya lolos parse, tapi `_HIER_RISK_FIELDS` di sana ikut menentukan
   field mana yang ditahan dari sisi sales — pantas dicek ulang setelah §3.3(b)
   diputuskan.

---

## 5. Checklist sebelum `git commit` merge

```bash
# 1. tidak ada penanda konflik yang tersisa
grep -rn '^<<<<<<<\|^>>>>>>>\|^=======$' --include='*.py' --include='*.vue' . | grep -v node_modules

# 2. semua berkas Python bisa di-parse
python3 -c "import ast,pathlib;[ast.parse(p.read_text()) for p in pathlib.Path('.').rglob('*.py') if 'node_modules' not in str(p)]"

# 3. identifier yang cuma ada di satu sisi tidak tertinggal
grep -rn 'cashline_row' api/routers/agent_error.py     # harus kosong
grep -rn 'load_workbook\|io\.BytesIO' api/sales_lookup.py  # harus kosong
grep -n 'n_tx' compliance/stats_aggregate.py           # harus ada assignment-nya

# 4. tes (pytest belum terpasang di container — jalankan di venv/host)
pytest tests/test_sales_roster_placeholders.py \
       tests/test_agent_error_snapshot_first.py \
       tests/test_hierarchy_avg_failure_rate.py

# 5. frontend
cd dashboard && npm run build
```

Setelah merge masuk: **paksa hitung ulang snapshot Statistics** (signature hanya
melacak perubahan data, bukan perubahan rumus) dan **rebuild container worker**
karena `openpyxl` baru.

---

## 6. Urutan kerja yang saya sarankan

1. Putuskan §3.3(b) — rumus Failure Rate. Semua yang lain menunggu ini.
2. Resolve 4 konflik yang jawabannya sudah pasti: `crud.py` (→ `v21`),
   `agent_error.py` (gabung), `sales_lookup.py` (sisi main + porting `_person`),
   `ResultsView.vue` (`group.primary` + `cd-excluded`, `cccItems` versi main).
3. Resolve `stats_aggregate.py`: sisi main di (a), sisi terpilih di (b).
4. Selaraskan `StatsView.vue` — label, catatan kaki, dan baris 141.
5. Jalankan checklist §5.


---

## 7. Hasil resolve (2 September 2026)

Keputusan §3.3(b): **rumus `dev` menang** — *Avg Failure Rate* = Total Failure ÷
tiket Not Qualified, ditulis sebagai kelipatan (`4.5x`).

| Berkas | Resolusi |
|---|---|
| `db/crud.py` | Catatan kedua sisi digabung. `v19` milik main ditulis ulang jadi **`v21`** (daftar tiket tersembunyi) dan ditambah **`v22`** (Submissions = jumlah transkrip). `version = "v22"` — memastikan SELURUH cache lama gugur, dari sisi mana pun perubahannya datang. |
| `api/routers/agent_error.py` | Snapshot-first dev **+** `name_online` dari main. `new_joiner_info()` dipanggil dengan `{"agent_id", "submit_time"}` hasil snapshot — `cashline_row` milik main tidak dipakai (variabelnya memang tidak ada di jalur dev). |
| `api/sales_lookup.py` | Sisi **main** utuh — parser inline dibuang, memanggil `parse_roster()`. Berkasnya kini **identik byte-per-byte dengan main** (`git diff MERGE_HEAD -- api/sales_lookup.py` kosong). |
| `compliance/sales_roster.py` | `_PLACEHOLDERS` + `person()` **diporting dari dev**; `parse_roster()` membaca semua kolom identitas lewat `person()` dan membuang baris padding ber-USER ID `"0"`. Worker (`call_ownership`) ikut kebal placeholder. |
| `compliance/stats_aggregate.py` | 5 tempat pakai `_avg`/`_avg_of` (rumus dev). Blok `n_tx`/`total_transcripts` **ambil sisi main** — bukan pilihan rumus, `n_tx` dipakai 4 baris di bawahnya yang lolos auto-merge. Kolom `Submissions` tetap jumlah transkrip; hanya rasionya yang berpenyebut Not Qualified. Komentar `tl_tx` yang jadi menyesatkan ikut diluruskan. |
| `dashboard/.../ResultsView.vue` | `callDurations(group.primary)` (scope dev) **+** `:class="{ 'cd-excluded': c.excluded }"` (main). `cccItems()` versi main (baca `score_bomb_items` dulu) dengan optional chaining dev dipertahankan. |
| `dashboard/.../StatsView.vue` | Label & rumus versi dev. Paragraf penjelas kolom dari main **dipertahankan** dengan kalimat rumusnya diganti — pembaca tetap diberitahu bahwa `Submissions` = transkrip dan `Tiket` = ticket id, sekaligus bahwa `Submissions` **bukan** penyebut rasio. |

Baris 141 `StatsView.vue` (tabel "Tim Saya", login Team Leader) sudah memakai
`avgText`/`avgClassOf` — konsisten dengan keputusan ini, tidak perlu diubah.
Baris 453 memakai `rateText` untuk kolom **Not Qualified Rate** — metrik yang lain,
memang bukan bagian dari perubahan ini.

### Verifikasi yang sudah dijalankan

```
grep penanda konflik (*.py, *.vue, *.js)      -> bersih
ast.parse seluruh *.py                        -> semua OK
grep cashline_row / load_workbook / n_tx      -> sesuai harapan
pytest tests/test_sales_roster_placeholders.py
       tests/test_agent_error_snapshot_first.py
       tests/test_hierarchy_avg_failure_rate.py -> 21 passed
pytest tests/                                 -> 6 failed, 144 passed
npm run build (dashboard)                     -> built in 3.52s
```

**6 kegagalan itu baseline yang memang sudah ada sebelum merge** —
`test_evaluator.py::test_evaluate_direct_json` dan 5 tes `test_pdf_parser.py` yang
PDF fixture-nya tidak ada di repo (`glob(...)` mengembalikan `[]`, lalu
`assert 0 == 3`). Tidak ada satu pun kegagalan baru.

### Yang masih harus dikerjakan SETELAH commit merge

1. **Rebuild container worker** — `openpyxl` baru masuk `worker/requirements.txt`;
   tanpa rebuild, penyaringan panggilan (§2.1) selalu jatuh ke `except` dan diam-diam
   tidak menyaring apa pun.
2. **Recreate container** (bukan restart) supaya `MINIO_BUCKET_SALES_DATABASE` terbaca.
3. **Paksa hitung ulang snapshot Statistics** — signature `v22` memang sudah
   menggugurkan cache, tapi pastikan angkanya benar-benar berubah di layar.
4. Jalankan migrasi `0050` + `0051` berurutan (netto tidak mengubah apa pun).
