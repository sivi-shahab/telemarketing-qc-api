# Edit User di Manage User / Kelola QC — desain

Tanggal: 20 Oktober 2026 · Repo: api, worker, core, dashboard

## Maksud

Manage User sekarang hanya bisa membuat, menghapus, dan mengaktifkan/menonaktifkan
user. Data user yang salah ketik saat dibuat, atau yang memang berubah (NIP baru,
email baru, lupa password, pindah posisi), tidak bisa diperbaiki tanpa menghapus dan
membuat ulang user — yang memutus tiket dan riwayatnya. Fitur ini menambahkan **Edit**
per user, dengan riwayat perubahan yang tampil di dashboard.

## Tujuan

1. Tombol **Edit** per baris di Manage User (Admin) dan Kelola QC (Team Leader QC):
   ubah **username (NIP), nama, email, role, password**.
2. Cakupan:
   - **Admin** (`ADMIN_USER_WRITE`) mengedit **semua** user, termasuk TL QC dan Admin.
   - **TL QC** (Kelola QC) mengedit **hanya QC Telemarketing** (definisi yang sama
     dengan `_is_telemarketing_qc` di `api/routers/auth.py`). User lain dijawab 404,
     sama seperti `set_user_active`.
3. **Ganti NIP → semuanya ikut pindah ke NIP baru** (keputusan user): tiket yang
   di-assign, riwayat assign, Manual Status, banding error code, upload, audit — semua
   kolom teks yang menyimpan username. Satu transaksi bersama perubahan `users`.
4. **Ganti role QC → role lain**: tiket QC itu yang di-assign hari ini dan belum
   dikerjakan **dilepas dan dibagi ulang di slot auto assign berikutnya** (keputusan
   user), dengan aturan yang sama seperti QC yang dinonaktifkan
   (`qc_auto_assign.reassign_from_inactive` / `crud.qc_reassign_candidates`).
5. **Riwayat perubahan tampil di dashboard** (keputusan user): siapa, kapan, field
   apa, nilai lama → baru.
6. **User sisi sales** (role ber-`data_scope` sales: sales_agent, team_leader,
   area_manager, dan role bespoke ber-cakupan sales — `P.is_sales_scope`): ganti NIP
   **tetap boleh, dengan peringatan** (keputusan user). Bagi mereka NIP adalah kunci ke
   roster Sales Database (`NIP BARU`/`NIP TL`/`NIP AM`, `core/sales_lookup.py`) dan ke
   agent_id di Results/App C/DWH. `rename_username` hanya memindahkan kolom audit &
   assignment App B; roster, agent_id tiket, App C, dan DWH **tidak** diubah. Akibatnya
   user itu tidak melihat data apa pun sampai roster dengan NIP baru diupload — dashboard
   wajib menampilkan peringatan: "User sales: roster Sales Database harus diupload ulang
   dengan NIP baru; sebelum itu user ini tidak melihat data. Data tiket lama di App C/DWH
   tetap memakai NIP lama." Tidak ada blokir.

## Bukan tujuan

- Mengedit campaign/roster user (campaign efektif berasal dari role + roster).
- Edit profil sendiri oleh user biasa (ubah password sendiri) — bukan bagian ini.
- Logout paksa saat password/NIP diganti (lihat Keputusan builder).
- Mengubah 4-service repo (`4-service-telemarketing-qc-system`) — port ke sana menyusul
  terpisah bila diminta.

## Anti-tujuan (gagal walau "jalan")

- Ganti NIP membuat QC kehilangan tiket, atau riwayatnya tercecer di dua NIP.
- Perubahan setengah jadi (users sudah ganti, sebagian tabel belum).
- TL QC bisa menaikkan role QC, mengedit user di luar QC Telemarketing, atau menebak
  keberadaan akun di luar cakupannya.
- Password (atau hash-nya) tercatat di riwayat atau log.
- Admin bisa mengunci dirinya sendiri (mis. menurunkan role sendiri).

## Rancangan

### Hak akses

- Permission baru **`qc.user.edit`** (`QC_USER_EDIT` di `api/permissions.py`), diberikan
  ke `team_leader_qc` lewat migrasi — pola yang sama dengan `qc.user.active.write`
  (migrasi 0066). Terpisah dari `QC_USER_ACTIVE_WRITE` supaya bisa dicabut sendiri via
  Manage Role. Label: "Kelola QC — edit data QC Telemarketing (tanpa ubah role)".
- Endpoint edit: `require_any(ADMIN_USER_WRITE, QC_USER_EDIT)`.
- `GET /auth/users` dan gate menu/route Kelola QC (`/qc/users`, `src/permissions.js`,
  `src/router/index.js`, sidebar) **diperluas** ke `QC_USER_EDIT` juga, supaya pemegang
  izin edit saja tetap punya halaman. Tombol Aktifkan/Nonaktifkan tetap hanya tampil
  untuk `qc.user.active.write`; tombol Edit hanya untuk `qc.user.edit`.
- Tanpa `ADMIN_USER_WRITE`:
  - target harus QC Telemarketing, selain itu 404;
  - field `role` **ditolak** (403) bila dikirim berbeda dari role sekarang;
  - field yang boleh: username, nama, email, password.
- Admin tidak boleh mengubah **role dirinya sendiri** (400, seperti "Tidak dapat
  menonaktifkan akun sendiri"). Field lain milik sendiri boleh.

### API (`telemarketing-qc-api`)

`PATCH /auth/users/{user_id}` — body `UserUpdate` (semua opsional; hanya yang dikirim
yang diubah): `username`, `name`, `email`, `role`, `password`.

Validasi:
- username/email di-`strip()`, tidak boleh kosong bila dikirim; unik terhadap user lain
  (409 "Username atau email sudah digunakan", sama dengan create).
- role harus ada di tabel `roles` (422, sama dengan create); role di-lower.
- password kosong/tidak dikirim = tidak berubah; bila diisi → `hash_password`.
  Aturan panjang minimal: sama dengan create (create tidak punya aturan — jangan
  mengarang aturan baru; dashboard tetap minta konfirmasi password).
- Tidak ada perubahan nyata → 200 tanpa menulis riwayat.

Dalam **satu transaksi**:
1. Update baris `users`.
2. Bila username berubah → `crud.rename_username(db, old, new)` (lihat Core).
3. Bila role berubah dari `qc` ke non-`qc` → isi `users.left_qc_at = utcnow()`.
   Bila berubah ke `qc` → `left_qc_at = NULL`.
4. Tulis satu baris riwayat per field yang berubah (lihat Riwayat).
5. `commit`. Gagal di mana pun → rollback seluruhnya.

Setelah ganti role: panggil invalidasi cache yang relevan bila ada (cache definisi role
di `api/rbac.py` per-role, bukan per-user — cek apakah ada cache per-user/username yang
perlu dibuang, mis. cache campaign efektif).

Respons: `UserListItem` yang sama dengan `GET /auth/users` (role_label, campaigns),
supaya dashboard bisa mengganti baris tanpa reload.

`GET /auth/users/history?user_id=&limit=` — riwayat perubahan, terbaru dulu.
Admin: semua. Tanpa `ADMIN_USER_WRITE` (TL QC): hanya riwayat yang target-nya
(saat ini) QC Telemarketing. Gate: `require_any(ADMIN_USER_WRITE, QC_USER_EDIT)`.

### Core (`telemarketing-qc-core` + salinan vendored di api/worker)

Model & crud diubah di core lalu disalin manual ke `core/` di api dan worker (aturan
vendored, lihat memori "Core stays vendored").

**`crud.rename_username(db, old, new)`** — update semua kolom teks berisi username,
tanpa commit (pemanggil yang commit). Kolom yang saat ini diketahui (dari
`core/db/models.py`):

| Tabel | Kolom |
|---|---|
| results | uploaded_by_username |
| qc_status_requests | requested_by_username, tl_qc_username, reviewed_by_username |
| error_code_appeals | requested_by_username, tl_qc_username, reviewed_by_username |
| qc_assignments | qc_username, assigned_by_username |
| qc_assignment_events | qc_username, previous_qc_username, actor_username |
| qc_status_events | actor_username |
| qc_manual_checks | checked_by_username |
| qc_databases | uploaded_by_username |
| sales_databases | uploaded_by_username |
| reprocess_jobs | created_by_username |
| app_settings | updated_by_username |
| user_change_events (baru) | actor_username |

Pencocokan **sama persis** dengan nilai lama (`old`), ditambah varian
`lower(trim(col)) = lower(trim(old))` — beberapa query (mis. `qc_reassign_candidates`)
membandingkan case-insensitive, jadi data lama mungkin tidak seragam kapitalisasinya.
Builder wajib grep ulang seluruh model (dan kolom JSON/teks bebas) untuk kolom
username lain sebelum menutup daftar ini, dan menambah test yang gagal bila ada kolom
`*_username` baru yang tidak terdaftar di fungsi ini.

Riwayat `user_change_events.target_username` lama **tidak** ikut diganti — itu catatan
historis; baris riwayat juga menyimpan `user_id` sehingga tetap terhubung.

**Kolom baru `users.left_qc_at`** (DateTime, nullable, UTC naive): kapan user terakhir
berpindah dari role `qc` ke role lain.

**`crud.qc_reassign_candidates`** diperluas: nama QC yang tiketnya dibagi ulang =
(yang sekarang: `role='qc'`, nonaktif, `deactivated_at` hari ini & ≤ slot) **ATAU**
(`left_qc_at` hari ini (`>= since`) dan `<= slot_start`, role sekarang ≠ `qc`).
Aturan tiket tetap: hanya yang di-assign hari ini dan belum dikerjakan (tanpa Manual
Status / cek manual). Pencatatan `reassign` di `qc_assignment_events` memakai source
baru `qc_ganti_role` untuk yang berasal dari pergantian role (perlu memisahkan dua
sumber di `reassign_from_inactive`, atau cukup satu source bila builder menilai
pemisahan tidak sepadan — catat keputusannya).

**Tabel baru `user_change_events`** (riwayat):
`id, user_id (FK users, ON DELETE SET NULL), target_username (NIP saat perubahan,
sesudah perubahan), field (username|name|email|role|password), old_value, new_value,
actor_user_id, actor_username, actor_role, created_at`.
Untuk `password`: `old_value`/`new_value` = NULL — hanya fakta "password diubah".

### Migrasi

Satu migrasi **0070** (sesudah 0069 `ticket_load_dates` milik filter load_date yang
belum dideploy): `users.left_qc_at`, tabel `user_change_events`, seed permission
`qc.user.edit` ke role `team_leader_qc` (pola 0066). Downgrade membalik ketiganya.
Skema `dashboard` (bukan `public`).

### Worker (`telemarketing-qc-worker`)

- Sinkron salinan `core/` (model, crud).
- `qc_auto_assign.reassign_from_inactive` ikut menangkap QC yang ganti role (lewat
  `qc_reassign_candidates` yang diperluas). Docstring/log disesuaikan.
- `stats_aggregate.compute_qc_performance`: hapus hard-code `_REAL_TLQC = "21060814"`
  / nama "DHEA KUMARING TYAS". TL QC diambil dari tabel user (role `team_leader_qc`,
  aktif; akun uji `bella`/`doutzen` → `behati` boleh tetap). Kalau ada lebih dari satu
  TL QC aktif riil, builder menentukan aturan deterministik (mis. yang id terkecil) dan
  mencatatnya. Perubahan bentuk data stats → **bump versi snapshot** (aturan memori).
- Kube worker (10.158.3.13) memakai DB prod yang sama dan tidak ikut di-update: aturan
  reassign yang lama di sana tidak mengenal `left_qc_at` — tidak merusak, hanya tidak
  membagi ulang. Catat di catatan deploy.

### Dashboard (`telemarketing-qc-dashboard`)

`src/views/spq-head/ManageUserView.vue` (dipakai `/spq-head/users` dan `/qc/users`):
- Tombol **Edit** per baris (tampil bila punya `admin.user.write` atau `qc.user.edit`).
- Modal edit berisi nilai sekarang: Username (NIP), Nama, Email, Role (select;
  **disembunyikan/terkunci** tanpa `admin.user.write`), Password baru + konfirmasi
  (opsional, kosong = tidak diubah).
- Bila NIP diubah: peringatan sebelum simpan — "Tiket dan seluruh riwayat akan ikut
  pindah ke NIP baru." Bila role QC diubah ke non-QC: "Tiket hari ini yang belum
  dikerjakan akan dibagi ulang di slot auto assign berikutnya."
- Sukses → baris diganti dari respons; error 409/422/403 ditampilkan apa adanya.
- Bila user mengedit **dirinya sendiri** dan username/nama berubah, perbarui `user` di
  `localStorage` (atau panggil ulang `/auth/me`).
- Bagian **Riwayat Perubahan** di halaman yang sama: tabel waktu (WIB), user (NIP +
  nama), field, lama → baru, oleh siapa. Filter per user. Password tampil sebagai
  "diubah". Pola tampilan mengikuti riwayat Assign Ticket.

## Batasan

- **Urutan:** dibangun di atas `main` lokal yang sudah berisi filter load_date (0069,
  snapshot v31). load_date dideploy **lebih dulu**; Edit User menyusul sebagai deploy
  sendiri (0070, snapshot v32 bila Performa QC berubah bentuk/isi). Rollback Edit User
  = image `pre-edit-user` + downgrade ke 0069, tidak menyentuh load_date.

- Prod dibangun dari folder kerja; ikuti alur deploy: build kandidat → diff freeze →
  smoke → retag; tag rollback `pre-edit-user`; migrasi 0070 dijalankan sebelum image
  baru (0069 harus sudah ada).
- Test python dijalankan di container image qc-api (`pip install ".[test]"`).
- E2E: `./jalankan.sh` di `telemarketing-qc-api/e2e`; rebuild bundle dashboard dulu.
- `git push` dijalankan user sendiri.

## Keputusan builder (bukan diputuskan user)

- Permission terpisah `qc.user.edit` untuk TL QC (bukan memperluas
  `qc.user.active.write`).
- TL QC tidak bisa mengubah role; Admin tidak bisa mengubah role dirinya sendiri.
- Ganti password/NIP **tidak** memaksa logout (token memakai id user; sesi berakhir
  saat token habis). Bisa ditambah nanti dengan versi token.
- Tidak ada aturan panjang password baru (mengikuti create).
- Pembagian ulang karena ganti role mengikuti aturan nonaktif: hanya tiket yang
  di-assign hari ini dan belum dikerjakan; tiket hari sebelumnya tetap atas namanya.
- Riwayat disimpan per field; password hanya dicatat "diubah".
- Hard-code TL QC di Performa QC diganti pembacaan dari tabel user.
- Daftar & menu Kelola QC juga terbuka untuk `qc.user.edit`.
- Edit User dideploy sesudah load_date, di atas `main` yang sudah memuatnya.

## Diserahkan ke builder

Nama komponen/fungsi, tata letak modal, paginasi riwayat, pemisahan source
`qc_ganti_role`, cara invalidasi cache, susunan test.
