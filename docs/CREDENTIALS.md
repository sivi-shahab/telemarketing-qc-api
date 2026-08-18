# Pembuatan Akun (Username & Password) — Sales & QC

Dokumen ini **tidak** menyimpan kredensial apa pun. Isinya hanya **cara membuat akun**
(username & password) untuk pengguna. Dua divisi memakai **sumber file (CSV/XLSX) yang
berbeda**: **Sales** dari roster Sales, **QC** dari roster QC.

> Daftar akun & password asli tidak boleh disimpan di repo. Kelola lewat menu
> **Administration → Manage User** atau kanal aman terpisah.

> ⚠️ **Sejak 10 Agustus 2026, menu Manage User & Manage Role hanya milik role `admin`.**
> SPQ Head **tidak** lagi bisa membuat/menghapus user (`admin.user.write` dicabut). Semua
> instruksi di bawah yang menyebut pembuatan akun dijalankan sebagai **Admin**.

---

## 1. Konvensi Umum (berlaku untuk semua akun)

| Elemen | Aturan |
|---|---|
| **Username** | = **NIP** (nomor induk pegawai) |
| **Email** | otomatis `<NIP>@bank.local` (unik per NIP; login tetap pakai NIP) |
| **Password** | di-hash bcrypt (`api.auth.hash_password`); nilai awal ditentukan saat pembuatan |
| **Role** | sesuai divisi/jabatan (lihat [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md)) |
| **is_active** | `true` |

Role bawaan yang valid: `sales_agent`, `team_leader` (TL Sales), `area_manager`,
`telesales_head`, `qc`, `team_leader_qc`, `qc_support`, `spq_head`, `admin`, `demo`.

Sejak migrasi `0031`, role tersimpan di tabel `roles` dan **role baru bisa dibuat sendiri**
lewat **Administration → Manage Role** (permission + `data_scope` + campaign). Nilai
`users.role` harus cocok dengan `roles.key`; role yang tidak terdaftar = tanpa permission
sama sekali. Lihat [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md).

---

## 2. Divisi Sales — dari file **Sales Database**

**Sumber (CSV/XLSX):** file **Sales Database** aktif (mis. "Update Sales Telemarketing …"),
di-upload lewat dashboard **Upload Data → Sales Database** (`POST /upload_sales_database`,
tersimpan di tabel `sales_databases`, dibaca `api/sales_lookup.py::active_sales_map`).

**Kolom NIP → role** (dicocokkan by header, fallback posisi kolom):

| Role | Username diambil dari | Nama dari |
|---|---|---|
| Sales Agent (`sales_agent`) | **NIP BARU** — kolom C | NAME (kolom D) |
| Team Leader Sales (`team_leader`) | **NIP TL** — kolom H | NAMA TL (kolom I) |
| Area Manager (`area_manager`) | **NIP AM / "NIP TLM"** — kolom J | NAMA AM (kolom K) |

Filter kampanye: **DEDICATED = Cashline** (kolom F). Bila satu NIP muncul di beberapa tier,
role tertinggi menang (Area Manager > Team Leader > Sales Agent).

### Cara membuat (script otomatis)

`scripts/seed_cashline_users.py` membaca Sales Database aktif dan membuat semua akun Sales:

```bash
# 1) Pastikan Sales Database sudah di-upload & aktif via dashboard.
# 2) Dry-run (tidak menulis) untuk melihat berapa akun yang akan dibuat:
docker compose exec api python scripts/seed_cashline_users.py

# 3) Set password awal lalu commit (benar-benar membuat akun):
docker compose exec -e SEED_PASSWORD='<password-kuat>' api \
    python scripts/seed_cashline_users.py --commit
```

- Password awal diambil dari env **`SEED_PASSWORD`** (bila tak diset, script memakai nilai
  default yang tertulis di `scripts/seed_cashline_users.py` — **ganti untuk production**).
- **Idempotent:** NIP/email yang sudah ada dilewati (aman dijalankan berulang saat roster bertambah).
- Username hasil seed persis dengan yang dipakai scoping Statistics/Results, jadi langsung ter-scope benar.

> Menambah agent baru = upload Sales Database terbaru → jalankan ulang script (`--commit`).

---

## 3. Divisi QC — dari file **roster QC (berbeda)**

**Sumber (CSV/XLSX):** file roster QC tersendiri — `csv_bank/List Role AI - QC.xlsx`
(kolom: NIP, nama, role). Berisi akun divisi QC: `qc`, `qc_support`, `team_leader_qc`,
dan bila perlu `spq_head` / `admin`.

> ⚠️ **Berbeda dari Sales:** QC **tidak** memakai Sales Database dan **tidak** punya script
> seeding khusus. Akun QC dibuat dari roster QC di atas.

### Cara membuat (via Manage User / API)

Buat tiap akun QC dari roster, satu per satu, oleh role **Admin**:

- **Dashboard:** menu **Administration → Manage User → tambah user** — isi `username` = NIP,
  `name`, `email` (`<NIP>@bank.local`), `password` awal, dan `role` sesuai kolom role di roster.
- **API setara:** `POST /auth/create_user` (permission `admin.user.write`):
  ```json
  { "username": "<NIP>", "name": "<Nama>", "email": "<NIP>@bank.local",
    "password": "<password-awal>", "role": "qc" }
  ```
  Ganti `role` sesuai baris roster (`qc` / `qc_support` / `team_leader_qc` / `spq_head` / `admin`).

Setelah dibuat, **Team Leader QC** perlu **assign ticket** ke tiap QC agar mereka melihat
tiket (menu Assign Ticket). Lihat [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md).

---

## 4. Reset / Ganti Password & Nonaktifkan

- **Ganti password / nonaktifkan user:** lewat menu **Administration → Manage User** (Admin).
- **Admin pertama** di-seed migrasi `0001` dari `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`ADMIN_EMAIL`
  (hanya saat tabel `users` kosong). Reset admin = wipe DB — lihat [`RUNBOOK.md`](./RUNBOOK.md).
- ⚠️ **Jaga selalu ada satu akun `admin` aktif.** Karena hanya `admin` yang punya
  `admin.user.write`, kehilangan seluruh akun Admin berarti tidak ada satu pun role di UI yang
  bisa memulihkannya — perbaikannya harus lewat DB langsung.

---

## 5. Keamanan

- **Jangan** menyimpan password asli di repo/dokumen ini. Bagikan lewat kanal aman.
- Gunakan password awal yang kuat (via `SEED_PASSWORD` untuk Sales; per-user untuk QC), dan
  minta pengguna menggantinya.
- Ganti default `ADMIN_PASSWORD` dan secret lain (`JWT_SECRET_KEY`, `API_KEY`) sebelum production.

---

## Referensi terkait
- [`HIERARKI_ROLE.md`](./HIERARKI_ROLE.md) — daftar role & akses menu
- [`API_REFERENCE.md`](./API_REFERENCE.md) — `POST /auth/create_user`, auth
- [`DATA_MODEL.md`](./DATA_MODEL.md) — tabel `users` & `sales_databases`
- [`RUNBOOK.md`](./RUNBOOK.md) — reset admin, operasi
