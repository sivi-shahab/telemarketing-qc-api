# Stats Collection — Desain

Tanggal: 17 September 2026
Status: disetujui di percakapan, menunggu review spec
Repo terdampak: telemarketing-qc-api, -worker (salinan core), -core, -dashboard
Prasyarat: fitur Collection Results (`docs/superpowers/plans/2026-09-17-collection-weighted-results.md`) sudah ada di branch `feat/collection-weighted-results`.

## Latar belakang

Menu Stats saat ini sepenuhnya berbentuk Cashline (hierarki AM/TL/agent dari roster sales, dokumen/SLA, risk base, snapshot harian ter-cache). Sejak fitur Collection Results, tiket campaign Collection (`COLLECTION_CAMPAIGNS`) sengaja dikeluarkan dari seluruh agregasi Stats. Akibatnya login Collection tidak punya statistik sama sekali, dan login Collection-only melihat Stats Cashline yang kosong.

## Tujuan

1. Stats menampilkan statistik **Collection** atau **Cashline** sesuai hak akses login.
2. Login yang boleh melihat keduanya memilih lewat toggle **Cashline | Collection**.
3. Stats Collection memuat empat kelompok metrik: KPI & tren PASS/FAIL, kepatuhan per kategori, Critical & Error Code, per agent & komitmen bayar.
4. Tanpa TMS, Ascend, maupun roster sales untuk sisi Collection.

## Di luar lingkup

- Snapshot/cache harian untuk Stats Collection (dihitung saat request; volume awal kecil).
- Hierarki AM/TL/agent berbasis roster untuk Collection.
- Perubahan isi Stats Cashline.
- Keputusan produk yang masih terbuka (eksklusi kategori agunan, veto Critical FAIL) — agregasi memakai skor & verdict apa adanya dari `normalize_stored_report`.

## Aturan role (`stats_views`)

Dihitung di server, satu fungsi di `api/rbac.py`:

```
stats_views_for(db, user) -> list[str]   # subset berurutan dari ["cashline", "collection"]
```

Keputusan user (17 September 2026): **hanya Admin dan login yang di-assign campaign Collection DAN Cashline** yang mendapat keduanya (toggle). Login tanpa batas campaign selain Admin tidak otomatis mendapat Stats Collection.

Semua syarat di bawah hanya berlaku bila user memegang `menu.stats` (tanpa itu `stats_views = []`) dan fitur Collection hidup (`COLLECTION_CAMPAIGNS` tidak kosong); env kosong ⇒ `["cashline"]` untuk setiap pemegang `menu.stats` (perilaku lama).

- **Admin** (`role` ∈ `ADMIN_LIKE_ROLES`, yaitu `admin` dan `demo` yang izinnya disamakan dengan Admin) ⇒ `["cashline", "collection"]`.
- **Selain Admin**, dengan `campaigns = effective_campaigns_for(db, user)`:
  - `None` (tidak dibatasi campaign) ⇒ `["cashline"]`.
  - daftar berisi **hanya** campaign Collection ⇒ `["collection"]`, kecuali cakupan sales (Collection tidak punya pemetaan roster sales) ⇒ `[]`.
  - daftar berisi **hanya** campaign non-Collection ⇒ `["cashline"]`.
  - daftar berisi **keduanya** ⇒ `["cashline", "collection"]`; bila cakupan sales ⇒ `["cashline"]`.
  - daftar kosong ⇒ `[]`.
- Untuk "collection" pada login non-Admin, `api.qc_scope.collection_view_scope` tetap menjadi gerbang data; bila ia `None` (mis. cakupan tak dikenal) "collection" tidak diberikan.

Catatan: aturan ini sengaja lebih sempit daripada visibilitas menu **Collection Results** (`collection_results_visible`, yang juga memberi menu itu ke login non-sales tanpa batas campaign). Keputusan lanjutan user (17 September 2026): menu Collection Results beserta daftar/detail/PDF-nya DISELARASKAN — hanya Admin atau login yang di-assign campaign Collection (non-sales).

`/auth/me` (`MeResponse`) mendapat field baru `stats_views: list[str]`.

## API

### Endpoint baru `GET /stats/collection`

Router baru `api/routers/stats_collection.py`, didaftarkan di `api/main.py`.

Query: `date_start`, `date_end` (YYYY-MM-DD, basis tanggal transkrip WIB — sama dengan filter daftar Collection), `campaign` (opsional, harus termasuk campaign Collection dalam cakupan; di luar cakupan ⇒ hasil kosong).

Gerbang:
- 403 bila `"collection"` tidak ada di `stats_views_for(db, user)`.
- Cakupan tiket: `api.qc_scope.collection_view_scope(db, user)` — helper yang sama dengan daftar Collection Results, sehingga angka Stats selalu sepakat dengan daftar. `None` ⇒ 403; `campaigns` kosong ⇒ payload nol.

Respons: payload dari `aggregate_collection_stats` (lihat di bawah) ditambah `{"campaigns": [...], "date_start", "date_end"}`.

### Gerbang endpoint Stats Cashline

Seluruh endpoint Stats Cashline yang ada (`/stats`, `/stats/daily`, `/stats/overview`, `/stats/campaigns_monthly`, `/stats/hierarchy`, `/stats/role_counts`, `/stats/my_overview`, `/stats/failure_reasons`, `/stats/failure_reasons_hierarchy`, `/stats/ai_status_timeseries`, `/stats/qc_performance`) menolak 403 bila `"cashline"` tidak ada di `stats_views_for`. Isi/perhitungannya tidak berubah. Endpoint non-Stats di `api/routers/stats.py` (mis. `/list_results`, `/results/hierarchy_options`, ekspor) tidak tersentuh.

### Query crud

`crud.collection_stats_rows(db, *, campaigns, uploaded_by_role=None, exclude_uploaded_by_role=None, date_start=None, date_end=None) -> list[tuple[Result, dict | None]]`

Filter identik dengan `list_collection_results` (campaign casefold, isolasi qc_support, `hidden_ticket_filter`, basis tanggal transkrip WIB, join hanya `result_data` terbaru per result), tanpa paginasi dan tanpa filter status/ai_status. Semua status diambil karena KPI menghitung pending/processing/failed juga. Bila memungkinkan, bagian filter dibagi dengan `list_collection_results` lewat satu fungsi pembangun query, bukan disalin.

## Core: `compliance/collection_stats.py`

Fungsi murni, tanpa DB:

```
aggregate_collection_stats(rows) -> dict
```

`rows`: iterable `(result, result_json)` — `result` punya `status`, `source_files`, `uploaded_at`, `generated_at`. Laporan dibaca lewat `normalize_stored_report(result_json["evaluation"])` hanya bila `result.status == "done"` dan `is_collection_result_json(result_json)`; tiket done tanpa laporan berbobot dihitung di `kpi.without_report`.

Tanggal tiket untuk tren: `generated_at` bila ada, selain itu `uploaded_at` dikonversi ke WIB (naive UTC + 7 jam), diambil tanggalnya — sama dengan basis filter daftar.

Payload:

```
{
  "kpi": {
    "total": int,                 # semua tiket dalam cakupan
    "done": int, "in_progress": int, "failed": int,   # in_progress = pending + processing
    "with_report": int,           # done + laporan berbobot valid
    "without_report": int,        # done tetapi bukan laporan berbobot
    "pass": int, "fail": int,
    "pass_rate": float | None,    # pass / with_report * 100, 1 desimal; None bila with_report 0
    "avg_score_percent": float | None,   # rata-rata ai_score_phase_2 / maximum_score * 100 (hanya maximum > 0)
  },
  "daily": [ {"date": "YYYY-MM-DD", "pass": int, "fail": int} ],   # hanya laporan valid, urut tanggal naik
  "categories": [
    {"category": str, "reports": int, "avg_percent": float | None,
     "fail": int, "fail_rate": float | None, "unavailable": int}
  ],                              # urut sesuai urutan pertama muncul
  "top_failed_indicators": [
    {"item_code": str, "requirement": str, "category": str,
     "belum_sesuai": int, "rate": float}
  ],                              # maks 10, urut belum_sesuai turun lalu item_code
  "critical": {
    "pass": int, "fail": int, "unavailable": int,
    "items": [ {"item_code": str, "requirement": str, "fail": int} ]   # hanya item dengan fail > 0, urut fail turun
  },
  "error_codes": [ {"error_code": str, "count": int, "example": str} ],  # urut count turun lalu kode
  "agents": [
    {"agent": str, "tickets": int, "pass": int, "fail": int,
     "pass_rate": float | None, "avg_score_percent": float | None}
  ],                              # urut tickets turun lalu nama
  "commitment": {"COMMITTED_TO_PAY": int, "PARTIAL_COMMITMENT": int, "DISPUTE": int,
                 "REFUSED": int, "NOT_STATED": int}
}
```

Aturan detail:
- **Kategori:** `avg_percent` = rata-rata `earned_score / total_weight * 100` atas laporan yang kategori tersebut punya `total_weight > 0`; `fail` = jumlah `category_result == "FAIL"`; `unavailable` = jumlah `TIDAK_TERSEDIA`; `fail_rate` = `fail / reports * 100`.
- **Indikator:** dihitung dari `scorecard_result` status `BELUM_SESUAI`, dikelompokkan per `item_code` (abaikan `"-"`); `requirement`/`category` diambil dari kemunculan pertama; `rate` = `belum_sesuai / with_report * 100`.
- **Critical:** status laporan `PASS`/`FAIL`/`TIDAK_TERSEDIA`; `items` dari `checked_items` berstatus `FAIL`, dikelompokkan per `item_code`.
- **Error code:** dikelompokkan per `error_code` (trim, abaikan kosong/`"-"`); `example` = `details_error` tidak kosong pertama.
- **Agent:** kunci = `agent_name` di-trim, spasi ganda dirapatkan, casefold; nama tampil = bentuk asli (setelah trim & rapat spasi) yang paling sering muncul, seri ⇒ urutan abjad pertama; `agent_name` kosong/None ⇒ kunci khusus dengan nama tampil `"Tidak disebut"`.
- **Komitmen:** hitung `commitment_status.status` dari laporan valid.
- Semua persentase dibulatkan 1 desimal; pembagi nol ⇒ `None`, bukan 0.

Salinan vendored: api `core/compliance/`, worker `core/compliance/`, core `src/qc_core/compliance/` — identik.

## Dashboard

- `src/stores/auth.js` menyimpan `stats_views` dari `/auth/me`.
- `src/views/dashboard/StatsView.vue`: di atas konten, toggle **Cashline | Collection** tampil hanya bila `stats_views.length === 2`. Pilihan disimpan di `localStorage` (`stats.view`) dengan try/catch; nilai tersimpan yang tidak ada di `stats_views` diabaikan. Satu nilai ⇒ langsung tampil tanpa toggle. Mode Cashline = tampilan yang ada, tidak berubah, dan request Cashline-nya hanya dijalankan bila mode Cashline aktif (supaya login Collection-only tidak memanggil endpoint yang kini 403).
- Komponen baru `src/components/collection/CollectionStatsPanel.vue`:
  - Filter tanggal transkrip (dari/sampai) + Reset.
  - Kartu KPI (total, selesai, diproses, gagal proses, PASS, FAIL, PASS rate, rata-rata skor).
  - Grafik harian batang bertumpuk PASS/FAIL (chart.js / vue-chartjs, sama dengan Stats yang ada).
  - Dua kolom: tabel kategori | top 10 indikator Belum Sesuai.
  - Dua kolom: Critical (ringkasan + item FAIL) | frekuensi Error Code.
  - Tabel agent | distribusi komitmen.
  - Label memakai `verdictLabel`/`commitmentBadge` dari `src/utils/collectionReport.js`; persentase `None` tampil "—".
  - Gaya mengikuti kartu/tabel Stats yang ada (token CSS App.vue); sempit ⇒ satu kolom.
  - Kosong ⇒ "Belum ada data Collection pada rentang ini."; gagal ⇒ kotak error; request dijaga AbortController + requestId.

## Pengujian

- **Unit (`tests/test_collection_stats.py`)**: laporan valid campuran PASS/FAIL; laporan tanpa verdict (`TIDAK_TERSEDIA` tidak dihitung sebagai PASS/FAIL); tiket belum selesai & done tanpa laporan berbobot; agent dengan variasi huruf/spasi dan tanpa nama; basis tanggal `generated_at` vs `uploaded_at` di batas hari WIB; input kosong ⇒ pembagi nol `None`; indikator top-10 terpotong dan urutan stabil.
- **Unit (`tests/test_rbac_collection_permissions.py`)**: `stats_views_for` untuk admin & demo (env hidup ⇒ keduanya; env kosong ⇒ cashline), non-admin tanpa batas campaign (cashline saja), Collection-only (collection), Cashline-only (cashline), campuran (keduanya), sales campuran (cashline), sales Collection-only (kosong), daftar campaign kosong (kosong), tanpa `menu.stats` (kosong).
- **DB (Postgres sementara, tidak pernah DB bersama)**: `GET /stats/collection` untuk QC Collection-only sepakat dengan `list_collection_results` (total & PASS); login sales ⇒ 403; tiket Cashline tidak ikut; isolasi qc_support; `result_data` ganda tidak menggandakan hitungan; endpoint Stats Cashline menolak Collection-only dan tetap melayani admin; env kosong ⇒ `/stats/collection` 403 dan Stats Cashline tidak berubah.
- **Dashboard**: `npm test` (helper murni bila ada), `npm run build`. Pengecekan visual di browser dilakukan user (tidak ada kredensial).

## Risiko & catatan

- Nama agent dari LLM tidak dijamin konsisten ejaannya; pengelompokan hanya merapikan huruf/spasi, bukan mencocokkan ejaan berbeda.
- Tanpa cache, waktu respons naik linear terhadap jumlah tiket Collection dalam rentang; bila kelak lambat, pendekatan snapshot bisa ditambahkan tanpa mengubah payload.
- `COLLECTION_CAMPAIGNS` harus sama di API dan worker (sudah jadi syarat fitur Collection Results).
- SPQ Head / TL QC tanpa batas campaign kini hanya melihat Stats Cashline, sementara menu Collection Results tetap terlihat bagi mereka — pertanyaan terbuka apakah menu itu juga dipersempit ke Admin + login yang di-assign Collection.
