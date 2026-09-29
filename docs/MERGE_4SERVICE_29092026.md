# Merge `4-service-telemarketing-qc-system` branch `cashline_mus` → repo production (29 September 2026)

Status: **Merged dan deployed ke production 29 September 2026 ~15:47 WIB.**
PR api #33 (`9b0046d`), core #18 (`35a320d`), worker #22 (`46c7d27`), dashboard #18 (`db085c6`).
Rollback: image `local/qc-{api,worker,dashboard}:pre-4service-29092026` (lihat §4).

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

## 4. Deploy (29 September 2026 ~15:47 WIB)

Tidak ada migrasi (alembic tetap `0063`), `_stats_signature` tidak perlu dinaikkan (tidak ada
perubahan skor/snapshot). Image api & worker bertambah ±5 MB karena aset .jpg.

Alur kandidat:

1. Image yang berjalan di-tag `local/qc-{api,worker,dashboard}:pre-4service-29092026`
   (api `7176118f5f45`, worker `577a0dff25f2`, dashboard `5889da1189b1`).
2. `TAG=cand docker compose build` dari `main` yang bersih → api `ae205e8cc5bf`,
   worker `ce19c8abc543`, dashboard `f3263af2eee5`.
3. `pip freeze` cand vs pre: **0 beda** (api 77 paket, worker 67).
4. Smoke cand di `qc-net` dengan `.env` production:
   - api: `alembic current` = `0063 (head)`, `/health` 200, `PATCH /auth/users/{id}/active` tanpa
     token 401, deck PPT 14 slide, `ppt_error_rate.py` md5 sama dengan repo, 11 `.jpg` ada.
   - worker: koneksi DB (`0063`), 5 task Celery terdaftar (sama dengan pre), aset PPT ada.
   - dashboard: `nginx -t` OK di `qc-net`, `baseURL:"/api-b"`, bundle = build lokal branch
     (bit-per-bit, selain `50x.html` bawaan nginx). Bundle pre = build `4272005` (beda hanya
     `VITE_API_URL` dari `.env`), jadi tidak ada perubahan tak ter-commit yang tertimpa.
   - Worker idle (tidak ada task aktif/reserved) sebelum restart.
5. `docker tag ...:cand ...:latest`, lalu `docker compose up -d --no-build` di api, worker,
   dashboard.

Verifikasi pasca-deploy: api healthy + `/health` 200; worker/beat/flower di image baru, Celery
`ping` OK; dashboard :4006 melayani `index-5j9xd-Cj.js` dan `PATCH /api-b/auth/users/5/active`
tanpa token → 401 (route terjangkau lewat proxy).

Belum diuji dengan login sungguhan: toggle Nonaktifkan QC di Manage User dan unduh deck PPT dari UI.
Kube worker (10.158.3.13) tidak di-update — perubahan worker hanya aset/berkas PPT.

Rollback:

```
for s in api worker dashboard; do docker tag local/qc-$s:pre-4service-29092026 local/qc-$s:latest; done
for r in api worker dashboard; do (cd telemarketing-qc-$r && docker compose up -d --no-build); done
```
