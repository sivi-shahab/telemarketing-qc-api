# Hierarki Role & Akses — Telemarketing QC System

Struktur jabatan (role), fungsi tiap role, dan pembagian akses. Sejak migrasi
`0031_roles_permissions`, **role bukan lagi string yang di-hardcode**: role tersimpan di
tabel `roles` dan bisa dibuat/diubah lewat menu **Manage Role**. Yang menentukan akses
adalah **permission**, bukan nama role.

Sumber otoritatif: `api/permissions.py` (kosakata + role bawaan `DEFAULT_ROLES`),
`api/rbac.py` (resolusi permission/campaign), `api/qc_scope.py` (cakupan data).
Menu **Hierarki Role & Menu** (`RoleHierarchyView.vue`) adalah tampilannya, bukan sumbernya.

> ⚠️ **`DEFAULT_ROLES` bukan yang berlaku di sistem berjalan.** Ia hanya jaring pengaman
> saat tabel `roles` belum ter-seed. Yang dibaca setiap request adalah kolom
> `roles.permissions` di DB, dan itu hanya berubah lewat **migrasi** atau menu Manage Role.
> Mengubah `api/permissions.py` saja tidak mengubah hak siapa pun. Matriks di §4 di bawah
> dibaca langsung dari DB per 14 Agustus 2026 — untuk memastikan ulang:
>
> ```sql
> SELECT key, jsonb_array_length(permissions) FROM roles ORDER BY key;
> ```

---

## 1. Tiga Dimensi Akses

| Dimensi | Menjawab | Disimpan di |
|---|---|---|
| **permission** | boleh melakukan/melihat APA | `roles.permissions` (50 permission tersedia) |
| **data_scope** | boleh melihat tiket SIAPA | `roles.data_scope` |
| **campaign** | boleh melihat campaign MANA | `role_campaigns` (per role) + `user_campaigns` (per user, menang atas role) |

Ketiganya independen. Role bisa punya `data_scope: all` tetapi tetap terbatas pada satu
campaign — dan sejak 12 Agustus 2026 pembatasan campaign itu berlaku **di seluruh** menu
(Results, Transcripts, Statistics, export), bukan hanya di Results.

### Nilai `data_scope`

| Nilai | Cakupan |
|---|---|
| `all` | semua tiket (tetap diiris pembatasan campaign) |
| `qc_assigned` | **hanya** tiket yang di-assign kepadanya. Tanpa assignment = kosong, bukan "tanpa batas" |
| `qc_support_own` | hanya tiket complaint yang di-upload QC Support |
| `sales_am` | tiket seluruh TL & agent di bawah Area Manager tsb |
| `sales_tl` | tiket agent di bawah Team Leader tsb |
| `sales_agent` | tiket miliknya sendiri |

Cakupan sales diresolusi **runtime dari roster Sales Database** (`api/sales_lookup.py`),
bukan dari FK di DB.

---

## 2. Diagram Hierarki

```
                    ┌───────────────┐   ┌───────────────┐
                    │   SPQ Head    │   │     Admin     │   ← Puncak (BERBEDA, lihat §3)
                    │  otoritas QC  │   │ otoritas sistem│
                    └───────────────┘   └───────────────┘
                            │                    │
              ┌─────────────┘                    └─────────────┐
              ▼                                                ▼
      DIVISI SALES                                DIVISI QUALITY CONTROL
      ────────────                                ──────────────────────
      Telesales Head                                   Team Leader QC
            ↓                                                ↓
       Area Manager                                         QC
            ↓
     Team Leader Sales                                  QC Support
            ↓                                (standalone · data complaint
       Sales Agent                            terisolasi · tanpa Statistics)
```

---

## 3. SPQ Head ≠ Admin

Ini kebijakan yang disengaja, bukan bug. Dokumentasi lama menyebut keduanya identik —
**itu sudah tidak berlaku.**

| | SPQ Head | Admin |
|---|---|---|
| Manage User (`admin.user.write`, `menu.manage_user`) | ❌ | ✅ |
| Manage Role (`admin.role.write`, `menu.manage_role`) | ❌ | ✅ |
| Putusan QC: `results.manual_status.set/direct/review_spq` | ✅ | ❌ |
| Banding: `results.error_code.direct_edit`, `review_spq` | ✅ | ❌ |
| Tabel verifikasi dokumen (`results.document.verification`) | ✅ | ❌ |
| Upload dokumen pendukung (`results.document.upload`) | ❌ | ✅ |
| Campaign, database Sales/QC, Upload Data, hapus tiket | ❌ | ✅ |
| Export agregat verifikasi (`results.export.verification`) | ❌ | ✅ |
| Export seluruh tiket satu periode (`results.export.tickets`) | ✅ | ✅ |

Alasannya: **Admin mengurus sistem** (user, role, campaign, database), **SPQ Head memutus
perkara QC**. Dikonfirmasi sebagai kebijakan 6 Agustus 2026; pemisahan menu Administration
ditambahkan 10 Agustus 2026, lalu **seluruh pengurusan data** menyusul 14 Agustus 2026
(§4.1). Baris terakhir tabel di atas dulu berbunyi "✅ | ✅" — itu sudah tidak berlaku.

> ⚠️ **Konsekuensi operasional:** hanya `admin` yang bisa membuat/memulihkan user & role.
> Pastikan selalu ada satu akun Admin aktif — SPQ Head tidak bisa menggantikannya.
> Kehilangan semua akun Admin = harus intervensi DB langsung.

Pengecualian lain yang mungkin terlihat janggal: **SPQ Head tidak punya
`results.document.upload`**. Pengunggah dokumen pendukung hanya **Team Leader Sales**
(+ Admin sebagai superuser teknis).

---

## 4. Matriks Permission per Role Bawaan

10 role bawaan (`DEFAULT_ROLES`). ✅ = dimiliki. Role buatan sendiri lewat Manage Role
bisa mengombinasikan permission mana pun.

Singkatan kolom: **SPQ** SPQ Head · **ADM** Admin · **TSH** Telesales Head · **AM** Area
Manager · **TLS** Team Leader Sales · **SA** Sales Agent · **TLQ** Team Leader QC ·
**QC** QC · **QCS** QC Support · **DMO** Demo.

| Permission | SPQ | ADM | TSH | AM | TLS | SA | TLQ | QC | QCS | DMO |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `menu.stats` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| `menu.results` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `menu.transcripts` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | ✅ | — |
| `menu.assign_ticket` | ✅ | ✅ | — | — | — | — | ✅ | — | — | — |
| `menu.manual_check` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | — | — |
| `menu.pending_check` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | — | — |
| `menu.campaigns` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.sales_database` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.qc_database` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.upload_campaign` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.upload_audio` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.upload_transcript` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.get_result` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.upload_sales_database` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.upload_qc_database` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.delete_campaign` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.manage_user` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.manage_role` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `menu.role_hierarchy` | ✅ | ✅ | — | — | — | — | — | — | — | — |
| `results.evaluation_detail` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | ✅ | ✅ |
| `results.critical_failure` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | ✅ | ✅ |
| `results.category_score` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| `results.manual_status.column` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | ✅ | ✅ |
| `results.manual_status.set` | ✅ | — | — | — | — | — | ✅ | ✅ | — | — |
| `results.manual_status.direct` | ✅ | — | — | — | — | — | ✅ | — | — | — |
| `results.manual_status.review_tl` | — | — | — | — | — | — | ✅ | — | — | — |
| `results.manual_status.review_spq` | ✅ | — | — | — | — | — | — | — | — | — |
| `results.error_code.appeal` | — | — | — | — | — | — | — | ✅ | — | — |
| `results.error_code.direct_edit` | ✅ | — | — | — | — | — | ✅ | — | — | — |
| `results.error_code.review_tl` | — | — | — | — | — | — | ✅ | — | — | — |
| `results.error_code.review_spq` | ✅ | — | — | — | — | — | — | — | — | — |
| `results.document.upload` | — | ✅ | — | — | ✅ | — | — | — | — | — |
| `results.document.view` | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| `results.document.verification` | ✅ | — | — | — | — | — | ✅ | ✅ | — | — |
| `results.manual_check.approve` | — | — | — | — | — | — | — | ✅ | — | — |
| `results.filter.qc_side` | — | — | — | — | — | — | ✅ | — | — | — |
| `results.export.verification` | — | ✅ | — | — | — | — | — | — | — | — |
| `results.export.tickets` | ✅ | ✅ | — | — | — | — | — | — | — | — |
| `stats.failure_reason` | ✅ | ✅ | — | — | — | — | — | — | — | — |
| `stats.qc_performance` | ✅ | ✅ | — | — | — | — | ✅ | — | — | — |
| `stats.risk_base` | ✅ | ✅ | — | — | — | — | ✅ | ✅ | — | ✅ |
| `stats.risk_system_new` | ✅ | ✅ | — | — | — | — | ✅ | — | — | ✅ |
| `admin.user.write` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `admin.role.write` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `admin.campaign.write` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `admin.sales_database.write` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `admin.qc_database.write` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `admin.ticket.delete` | — | ✅ | — | — | — | — | — | — | — | — |
| `qc.assignment.write` | ✅ | ✅ | — | — | — | — | ✅ | — | — | — |
| `transcript.upload` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |
| `audio.upload` 🔒 | — | ✅ | — | — | — | — | — | — | — | — |

**Jumlah permission:** Admin 40 · SPQ Head 24 · Team Leader QC 22 · QC 14 · Demo 9 ·
QC Support 7 · Team Leader Sales 5 · Telesales Head / Area Manager 4 · Sales Agent 3.

🔒 = **admin-only** (`ADMIN_ONLY_PERMISSIONS`, 14 Agustus 2026). Permission bertanda ini
tidak muncul di daftar checkbox Manage Role dan **ditolak `422`** bila dipaksakan lewat
API ke role selain `admin` — lihat §4.1.

---

## 4.1 Pengurusan Data Hanya Admin (14 Agustus 2026)

Lanjutan kebijakan §3. Kalau 10 Agustus memindahkan menu **Administration** ke Admin,
14 Agustus memindahkan **seluruh pengurusan data**: Campaigns, Database Sales, Database QC,
semua menu Upload Data, dan Delete Campaign — beserta capability tulisnya. 19 permission
masuk `ADMIN_ONLY_PERMISSIONS` (`api/permissions.py`).

**Penegakannya dua lapis, bukan sekadar menyembunyikan menu:**

1. `GET /roles/catalog` membuang permission admin-only dari daftar checkbox Manage Role —
   operator tidak bisa memilih apa yang tidak ditawarkan.
2. `POST /roles` dan `PUT /roles/{id}` **menolak `422`** bila permission itu dikirim untuk
   role selain `admin`. Menyembunyikan checkbox saja tidak cukup: request langsung ke API
   tetap bisa menyelinapkannya.

> ⚠️ **Menyimpan role `admin` lewat Manage Role tetap aman.** Karena capability admin-only
> tidak ada di form, ia juga tidak ikut terkirim balik — `PUT /roles/{id}` membawanya serta
> apa adanya dari DB. Tanpa itu, sekali klik Simpan pada role Admin akan mencabut seluruh
> menu pengurusan data dari satu-satunya role yang memilikinya.

**Yang hilang dari tiap role:**

| Role | Kehilangan |
|---|---|
| SPQ Head | Campaigns, Database Sales & QC, seluruh Upload Data, Get Result, Delete Campaign, `admin.ticket.delete`, `results.export.verification` |
| Team Leader QC | Upload Audio, Upload Transcript (+ capability tulisnya) |
| QC Support | Upload Audio, Upload Transcript (+ capability tulisnya) |
| Demo | Campaigns, Upload Transcript |
| Sales Agent | `results.document.view` |

> ⚠️ **QC Support praktis lumpuh, dan itu disengaja.** Cakupan datanya `qc_support_own`
> ("hanya tiket yang di-upload sendiri"), jadi tanpa hak upload ia tidak akan pernah punya
> tiket baru untuk dilihat. Dikonfirmasi sebagai kebijakan. Untuk menghidupkannya kembali,
> yang dikembalikan adalah keempat capability upload-nya — bukan cakupan datanya.

**Sales Agent tidak lagi bisa membuka dokumen pendukung.** Penegakannya juga dua lapis:
`get_document_viewer_user` menolak `403` di `/documents/{id}` dan `/document_file/{id}`,
dan kolom **Document** di halaman Results hilang sama sekali untuk role tanpa
`results.document.view` maupun `results.document.upload`.

**Pengganti Export Agregat untuk SPQ Head.** `results.export.verification` (export per
kategori verifikasi) pindah ke Admin; SPQ Head mendapat `results.export.tickets` — export
SEMUA tiket pada rentang tanggal & filter yang sedang dipilih. Lihat
[`API_REFERENCE.md`](./API_REFERENCE.md) §5.3.

---

## 5. Fungsi & Cakupan Tiap Role

| Role | `data_scope` | Fungsi utama |
|---|---|---|
| **SPQ Head** | `all` | Otoritas tertinggi **QC**: statistik global, semua tiket, assign ticket, approval final banding & Manual Status, edit error code langsung, export seluruh tiket satu periode. **Tidak** mengelola user/role, dan sejak 14 Agustus 2026 **tidak** lagi mengurus campaign/database/upload/hapus tiket (§4.1). |
| **Admin** | `all` | Superuser **sistem**: user, role, campaign, database, seluruh Upload Data, hapus tiket, upload & lihat dokumen, export verifikasi. **Tidak** memutus perkara QC. |
| **Telesales Head** | `all` | Oversight seluruh divisi Sales. Stats global + Hierarki Error Rate, dan Results. Tanpa kolom Manual Status. |
| **Area Manager** | `sales_am` | Mengawasi satu area: semua TL Sales & agent di bawahnya. |
| **Team Leader Sales** | `sales_tl` | Memimpin satu tim. Satu-satunya pihak (selain Admin) yang **meng-upload dokumen pendukung** customer. |
| **Sales Agent** | `sales_agent` | Hanya tiket miliknya sendiri. Sejak 14 Agustus 2026 **tidak** bisa membuka dokumen pendukung — kolom Document hilang dari halaman Results. |
| **Team Leader QC** | `all` | Checker & pembagi tiket: assign tiket ke QC, Checker alur banding (Terima/Tolak final atau Teruskan), edit error code & Manual Status langsung. |
| **QC** | `qc_assigned` | Maker: menilai tiket yang di-assign kepadanya, mengajukan banding berjenjang, mencatat manual check. |
| **QC Support** | `qc_support_own` | Standalone: tiket complaint miliknya sendiri, terisolasi dari role lain; **tanpa menu Statistics**. Sejak 14 Agustus 2026 **kehilangan hak upload**, sehingga praktis tidak punya tiket baru — lihat peringatan di §4.1. |
| **Demo** | `all` | Read-only murni untuk peragaan: melihat Results & Stats saja. Sejak 14 Agustus 2026 tanpa Campaigns dan tanpa upload transkrip, jadi materi demo harus disiapkan lebih dulu dengan akun Admin. |

> Divisi Sales (Telesales Head, Area Manager, TL Sales, Sales Agent) **tidak** punya
> `results.manual_status.column` — bagi mereka cukup AI Status (permintaan 10 Agustus 2026).

---

## 6. Alur Aju Banding (berjenjang)

```
   QC · Maker  ──►  Team Leader QC · Checker  ──►  SPQ Head · Approval
```

- **QC** (`results.error_code.appeal`) mengajukan banding pada tiket yang di-assign kepadanya.
- **Team Leader QC** (`results.error_code.review_tl`): **Terima (final)**, **Tolak (final)**,
  atau **Teruskan ke SPQ Head**.
- **SPQ Head** (`results.error_code.review_spq`): putusan final atas yang diteruskan.
- Bila di-approve, **skor & error card menyesuaikan otomatis**.

Alur yang sama berlaku untuk **Manual Status** dengan trio permission
`results.manual_status.set` → `.review_tl` → `.review_spq`.

> **Pengecualian tanpa hierarki:** pemilik `results.error_code.direct_edit` /
> `results.manual_status.direct` (TL QC dan SPQ Head) mengubah langsung — berlaku seketika,
> tanpa approval. Hanya **QC** yang wajib melewati alur berjenjang.

---

## 7. Membuat & Mengubah Role

Menu **Administration → Manage Role** (khusus `admin`):

1. `GET /roles/catalog` menyediakan kosakata form: daftar permission berkelompok, pilihan
   `data_scope`, dan campaign yang tersedia.
2. `POST /roles` / `PUT /roles/{role_id}` menyimpan nama, permission, `data_scope`, dan
   daftar campaign role.
3. Campaign per **user** (menang atas setelan role) diatur lewat
   `PUT /roles/user_campaigns/{username}` — daftar kosong = hapus pembatasan.

Perubahan berlaku pada request berikutnya; tidak perlu restart.

---

## Referensi terkait
- [`API_REFERENCE.md`](./API_REFERENCE.md) — permission per endpoint
- [`CREDENTIALS.md`](./CREDENTIALS.md) — pembuatan akun Sales & QC
- [`DATA_MODEL.md`](./DATA_MODEL.md) — tabel `roles`, `role_campaigns`, `user_campaigns`
