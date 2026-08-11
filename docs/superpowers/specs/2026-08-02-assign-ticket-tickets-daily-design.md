# Assign Ticket: pindah sumber data ke `tickets-daily`

Tanggal: 2026-08-02
Halaman: `/qc/assign` — `dashboard/src/views/qc/AssignTicketView.vue`

## Masalah

Halaman Assign Ticket mengambil daftar tiket dari `/list_results`, yaitu tabel
`results` lokal — isinya hanya tiket yang sudah masuk ke sistem ini lewat
`/webhook/process_ticket`. Akibatnya Team Leader QC baru bisa membagi tiket
setelah tiket tersebut selesai di-ingest, bukan begitu tiket tersedia di hulu.

Halaman Transkrip sudah membaca langsung dari feed harian hulu
(`tickets-daily`). Assign Ticket harus mengikuti sumber yang sama supaya
pembagian tiket bisa dilakukan atas dasar data H-1 yang sama.

## Sumber data

Tiga panggilan, digabung di klien:

| Sumber | Cara | Dipakai untuk |
|---|---|---|
| `{C_API_BASE}/tickets-daily` | `fetch()` + header `X-API-Key` | baris tabel |
| `/list_results` | `apiClient` | join QC / Assign Date / Approved At |
| `/qc_assignment/qc_users` | `apiClient` | dropdown QC (tidak berubah) |

`C_API_BASE` = `VITE_TMS_API_URL`, default `https://call-qc.bankmega.local`.
Nginx host mem-proxy `/tickets-daily` ke `localhost:8008` ("App C").

### Bentuk respons `tickets-daily`

```json
{"mode":"yesterday","load_date":null,"page":1,"total":192,"total_pages":2,"items":[...]}
```

Field item yang dipakai: `id`, `context`, `processed_at`.
Batas `limit` adalah 100 (di atas itu HTTP 422), sehingga penarikan harus
melakukan loop paginasi.

Tanpa parameter `load_date`, API memakai `mode: "yesterday"` — inilah sumber
perilaku H-1; tidak ada logika tanggal di sisi dashboard.

## Isi kolom

| Kolom | Sumber | Aturan |
|---|---|---|
| Ticket ID | tickets-daily `id` | kunci grup |
| Campaign | tickets-daily `context` | nilai unik dalam grup, digabung `", "` |
| Status | tickets-daily `processed_at` | `done` bila SEMUA tiket dalam grup terisi; selain itu `belum diproses` |
| QC ditugaskan | `/list_results` → `assigned_qc` | join by ticket id |
| Assign Date | `/list_results` → `assigned_at` | join by ticket id |
| Approved At | `/list_results` → `qc_checked_at`, `qc_checked_by` | join by ticket id |
| Assign ke | aksi | `POST /qc_assignment` dengan `ticket_id = group.id` |

Catatan atas dua keputusan yang sempat diperdebatkan:

- **Campaign diisi dari `context`, bukan `campaign`.** Payload punya keduanya:
  `campaign` bernilai kode seperti `NTB002`/`LOC26`, sedangkan `context`
  bernilai `card`/`usage`/`cashline`/`ntb`/`tbfu`/`alloblast`. Pilihan jatuh
  pada `context` atas keputusan eksplisit pemilik fitur. Perlu diingat halaman
  Transkrip memakai `campaign` untuk kolom Campaign-nya, jadi kedua halaman
  akan menampilkan hal berbeda di kolom bernama sama.
- **Status hanya `done` bila seluruh tiket dalam grup punya `processed_at`.**
  Satu tiket yang belum diproses membuat seluruh grup `belum diproses`.

## Pengelompokan

Satu baris = satu `id` (ticket id). Satu `id` bisa memuat beberapa `tiket_id`
(rekaman). Pada data 2026-07-28: 192 tiket → 112 id, 48 di antaranya punya
lebih dari satu tiket.

`context` umumnya seragam dalam satu grup; ditemukan 2 dari 112 grup yang
campuran (`cashline` + `ntb`). Karena itu Campaign menggabungkan nilai unik,
bukan mengambil yang pertama.

## Join ke data lokal

`assigned_qc`/`assigned_at` di backend sudah di-map dengan ticket id
(`stats.py:605-606`), jadi langsung bisa dijoin.

`qc_checked_at`/`qc_checked_by` di-map dengan UUID result (`stats.py:607-608`),
bukan ticket id. Join tetap dilakukan lewat field `id` pada item `/list_results`
— field itu berisi ticket id hasil `_customer_id_from_files()`, sehingga satu
item `/list_results` membawa sekaligus ticket id dan nilai `qc_checked_*`
miliknya.

Tiket yang belum ada di sistem ini menampilkan `— belum —` pada ketiga kolom
dan tetap dapat di-assign: `POST /qc_assignment` (`qc_assignment.py:49-65`)
hanya menyimpan `ticket_id` + `qc_username` tanpa memvalidasi keberadaan
ticket di tabel `results`.

## Toolbar

Tambah satu input tanggal yang dipetakan ke parameter `load_date`. Kosong
berarti parameter tidak dikirim, sehingga API memakai mode `yesterday`.

Filter yang sudah ada (cari Ticket ID, filter QC, tombol muat ulang) tetap.

## Perubahan teknis wajib

- `:key="t.result_id"` → `:key="t.id"`. Baris tickets-daily tidak punya
  `result_id`, sehingga key lama akan bernilai `undefined` untuk semua baris.
- `/list_results` saat ini ditarik sekali dengan `limit=100`
  (`AssignTicketView.vue:83`). Satu hari saja sudah 112 id, jadi ini memotong
  data secara diam-diam dan harus diganti loop paginasi.
- Penarikan `tickets-daily` memakai `AbortController` + penanda `requestId`
  agar hanya respons dari permintaan terakhir yang menulis ke state — menyalin
  pola di `TranscriptsView.vue:327-377`, termasuk konstantanya:
  `FETCH_LIMIT = 100` (batas API) dan `MAX_FETCH_PAGES = 100` (pengaman loop).

## Penanganan error

| Kegagalan | Perilaku |
|---|---|
| `tickets-daily` gagal | tampilkan pesan error, tabel kosong |
| `/list_results` gagal | baris tetap tampil; tiga kolom join jadi `— belum —` |
| `AbortError` | diabaikan, bukan error yang ditampilkan |

Degradasi lunak pada kegagalan `/list_results` disengaja: fungsi utama halaman
ini adalah membagi tiket ke QC, dan itu hanya butuh ticket id.

## Cakupan

Backend tidak disentuh. Perubahan terbatas pada
`dashboard/src/views/qc/AssignTicketView.vue`.

## Verifikasi

Dashboard tidak punya framework test. Verifikasi yang dipakai:

1. Pemeriksaan komponen Vue yang dipakai di template tapi tidak di-import —
   regresi yang pernah terjadi di `ResultsView.vue`. Skripnya saat ini ada di
   direktori scratchpad sesi, belum masuk repo; kalau dipakai berulang,
   pindahkan dulu ke repo (mis. di samping `scan_undefined_vars.py`).
2. Build ulang container dashboard, pastikan chunk `AssignTicketView-*.js`
   terbentuk dan tidak mengandung panggilan `resolveComponent`.
3. Probe HTTP `tickets-daily` dengan `load_date=2026-07-28` → harus 112 baris
   setelah pengelompokan, dan `load_date` kosong → mode `yesterday`.
4. Pemeriksaan manual di browser oleh pemilik fitur: assign dan lepas satu
   tiket, pastikan kolom QC/Assign Date terisi setelah muat ulang.

## Risiko yang diketahui

- **Halaman kosong secara default.** Per 2026-08-02, `load_date` kemarin
  (2026-08-01) mengembalikan 0 baris; data terakhir yang tersedia adalah
  2026-07-28. Ini perilaku yang benar sesuai desain, bukan kerusakan, tetapi
  akan terlihat oleh user. Input tanggal ada untuk menutupi keadaan ini.
- **`X_API_KEY` hardcoded.** `TranscriptsView.vue:170` menyimpan API key
  sebagai nilai fallback, dan seluruh `VITE_*` ter-inline ke bundle JS sehingga
  terbaca siapa pun yang membuka dashboard. Halaman ini akan memakai key yang
  sama. Tidak memperburuk keadaan, tetapi memperluas jejaknya. Rotasi key
  ditangani terpisah, di luar cakupan spec ini.
- **Kolom Campaign berbeda arti antar halaman.** Transkrip memakai `campaign`,
  Assign Ticket memakai `context`.
