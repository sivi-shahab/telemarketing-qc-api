# Merge `4-service-telemarketing-qc-system` branch `cashline_mus` → repo production (29 September 2026)

Status: **branch `merge/4service-29092026` di keempat repo, BELUM di-push/merge dan BELUM di-deploy.**
Deploy mengikuti alur kandidat seperti `MERGE_4SERVICE_28092026.md` §7.

## 1. Ruang lingkup

| | Nilai |
|---|---|
| Repo sumber (A) | `4-service-telemarketing-qc-system`, branch `origin/cashline_mus` @ `b7e1ee5` (28 Sep 2026 22:49) |
| Port sebelumnya | A@`f91aeac` (28 Sep 2026, `MERGE_4SERVICE_28092026.md`) |
| Delta | A `f91aeac..b7e1ee5` — 2 commit, 16 file |
| HEAD production saat merge | api `a2c61b1`, core `636326f`, worker `4444370`, dashboard `4272005` |
| DB production | schema `dashboard`, alembic `0063` — **tidak berubah** (tidak ada migrasi) |

```
b7e1ee5 feat(manage-user): tombol nonaktifkan QC supaya pembagian tiket cuma ke QC aktif
153599f style(ppt-error-rate): pakai raster template asli + hapus kolom/section tanpa data
```

A `origin/main` @ `619de75` adalah cherry-pick dari `f91aeac` (fitur yang sama, sudah ter-port
28 Sep) — tidak diambil lagi.

## 2. Yang masuk

| Fitur | Berkas | Catatan |
|---|---|---|
| Nonaktifkan/Aktifkan QC | api `api/routers/auth.py` (`PATCH /auth/users/{id}/active?is_active=`), dashboard `src/views/spq-head/ManageUserView.vue` | Izin `ADMIN_USER_WRITE`; akun sendiri → 400, tidak ada → 404. Memakai kolom `User.is_active` yang sudah difilter `qc_assignment.py` (manual & auto) dan `get_current_user`, jadi tanpa migrasi. Tombol hanya di baris role `qc` |
| PPT Error Rate: raster template asli | `compliance/ppt_error_rate.py` + 11 `assets/*.jpg` (±4,9 MB) di api/core, worker/core, qc_core | Kolom Sampling (%), %KPI, kolom Evaluated Top 10 TLO, section Complaint, dan campaign tanpa data error reason dihapus dari deck |
| Hapus placeholder Credit Shield/Personal Loan | api `api/routers/stats.py` (`_MISSING_CAMPAIGNS` dibuang) | Hunk komentar diterapkan manual (import path `compliance.` di production) |
| Packaging qc-core | `pyproject.toml` package-data `assets/*.jpg` | Tanpa ini wheel `qc_core` tidak membawa gambar dan deck gagal dibuat |

Tiga salinan `ppt_error_rate.py` identik dengan A@`b7e1ee5`.

## 3. Verifikasi

- core: `pytest` di image `local/qc-api:latest` — 338 passed, 5 skipped; tes baru
  `test_raster_template_ppt_error_rate_ikut_ke_paket` (aset .jpg ada di wheel yang ter-install).
- api: 338 passed, 178 skipped (DB tidak terjangkau); tes baru `tests/test_user_active_toggle.py` (4 kasus).
  `PATCH /auth/users/5/active` tanpa token → 401 (route terdaftar).
- worker: 18 passed.
- Smoke deck dari working tree api & worker: 14 slide, tidak ada teks Sampling/KPI/Complaint/
  Credit Shield/Personal Loan; campaign tanpa data (contoh Activation) tidak muncul.
- dashboard: `vite build` sukses.

## 4. Deploy

Tidak ada migrasi, `_stats_signature` tidak perlu dinaikkan (tidak ada perubahan skor/snapshot).
Image api & worker bertambah ±5 MB karena aset .jpg.
