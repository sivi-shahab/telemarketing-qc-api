# Merge `4-service-telemarketing-qc-system` branch `cashline_mus` → repo production (6 Oktober 2026)

Status: **branch `merge/4service-06102026` di keempat repo — belum merge, belum deploy.**

## 1. Ruang lingkup

| | Nilai |
|---|---|
| Repo sumber (A) | `4-service-telemarketing-qc-system`, `origin/cashline_mus` @ `c21ff22` (5 Okt 2026 15:44) |
| Port sebelumnya | A@`b7e1ee5` (29 Sep 2026, `MERGE_4SERVICE_29092026.md`) |
| Delta | A `b7e1ee5..c21ff22`: 9 commit, 17 file (8 kode, 9 dokumen NTB) |
| HEAD production saat merge | api `c37bbba`, core `98002fb`, worker `bf1e76c`, dashboard `d399ca8` |
| DB production | schema `dashboard`, alembic **tidak berubah** (tidak ada migrasi) |

```
c21ff22 feat(ntb): Fase 1 — scorecard, KB, dan prompt campaign NTB v1
1e841ae docs(ntb): scorecard NTB 05102026 (aditif 100+25+50=175), sumber xlsx, update plan & state
c3a62f1 docs(ntb): plan & state onboarding campaign NTB (KB, scorecard, prompt)
e17ecca feat(assign-ticket): batch auto assign terjadwal 08/11/13/15/16.30 WIB + countdown
3d6a3de feat(ppt-error-rate): kolom Approved di Trend, legend warna dipindah ke bawah tabel
6296b02 feat(assign-ticket): auto assign merata per momen tombol ditekan, bukan total beban
dcc15d3 feat(ppt-error-rate): grouping Usage/Card/Retention, kolom Error Rate & % dipisah, aging + top 3 failure reason; Log QC per hari
75143af feat(ppt-error-rate): contoh alasan teratas pakai negasi requirement, tanpa truncate
2c1c01e feat(assign-ticket): tambah tab Log QC dengan ringkasan merata per bulan
```

Commit lokal A `735bdfe` ("add test file score") hanya menghapus newline di akhir
`core/tests/test_score_floor.py`, jadi tidak diambil. Saat merge, A sedang di tengah
`pull --rebase` dan state itu tidak disentuh.

## 2. Keputusan user (6 Oktober 2026)

1. **Aturan bagi Auto Assign ikut A, yaitu merata per momen.** Beban lama tidak dihitung
   dan selisih antar-QC paling banyak 1. Aturan ini menggantikan `split_by_load` (merata
   atas total beban, 4 September).
2. **Batch terjadwal diport tetapi default MATI.** Saklarnya `QC_AUTO_ASSIGN_ENABLED`.
   Default di kode adalah `false`, kebalikan dari A yang default hidup. Worker kube
   berbagi DB prod, jadi tanpa env eksplisit tidak boleh ada yang membagi tiket.
3. **Campaign Collection-kind (`COLLECTION_CAMPAIGNS`) dikeluarkan dari deck PPT,**
   sama seperti Activation. Tanpa ini campaign tersebut masuk grup "LAINNYA".

## 3. Yang masuk

| Fitur | Berkas | Catatan |
|---|---|---|
| Modul bersama auto assign | `core/qc_auto_assign.py` baru di api/core, worker/core, dan qc_core | Isinya pool, `distribute_evenly`, jadwal, dan `run_scheduled_batch`. **Beda dari A:** pool mengecualikan Collection (seperti tombol prod), default mati, dan `IntegrityError` (bentrok dengan tombol manual atau beat kedua) membatalkan batch utuh. Dockerfile api/worker kini meng-COPY modul ini |
| Tab Log QC | api `GET /qc_assignment/log`, dashboard `AssignTicketView.vue` | Cakupannya `_assignment_scope` (prod), bukan `scoped_customer_ids` seperti di A, supaya sama dengan `GET /qc_assignments` |
| Jadwal + countdown | api `GET /qc_assignment/schedule`, banner di Assign Ticket | Saat saklar mati, banner menulis "Auto assign terjadwal dimatikan" |
| Batch terjadwal | worker `worker/tasks/auto_assign.py`, `celery_app.py` (5 entri `beat_schedule` crontab WIB) | Jadwal pemeliharaan yang sudah ada tetap. Task langsung pulang tanpa membuka DB saat saklar mati |
| Aturan bagi per momen | api `qc_assignment.py` (`split_by_load` dan `current_assignment_load` dihapus, `_auto_assign_pool` didelegasikan ke core), dashboard `describeSplit` | Alur prod tetap: `ticket_ids` dari browser, 409 saat bentrok, `per_qc` berisi daftar id |
| PPT Error Rate | api `stats.py`, `compliance/ppt_error_rate.py` dan `stats_aggregate.py` (tiga salinan) | Grup USAGE/CARD/RETENTION, Activation dan Collection-kind dikeluarkan, kolom Error Rate dan % dipisah, Approved, Top 10 TLO per aging dengan top 3 failure reason, Detail Error Reason satu slide per campaign. `agent_requirements` hanya parameter keluaran, jadi snapshot Statistics **tidak berubah** dan versi snapshot tetap v27 |
| Dokumen NTB | `docs/NTB/` | Hanya artefak Fase 1. **Campaign NTB belum boleh di-upload**: backend belum mendukung (lihat `docs/NTB/state.md`). Gerbang TMS/Ascend akan membuat setiap tiket NTB PENDING, dan `max_score` masih terpaku ke Cashline |

Assign Ticket di prod sudah ditulis ulang (tiket dari App C tickets-daily H-1, 22 Sep).
Versi view dan router dari A **tidak** diambil utuh. Hanya fitur di atas yang dicangkokkan.

## 4. Verifikasi

- api: 443 passed, 190 skipped (DB tidak terjangkau). Ada dua file tes baru.
  `tests/test_qc_auto_assign_schedule.py` menguji jadwal, saklar, pool Collection, batch,
  dan Log QC. `tests/test_ppt_error_rate_groups.py` menguji grup, pengecualian Collection,
  total AM, dan smoke test deck dari bentuk data router.
  `tests/test_qc_assignment_auto.py` dipindah ke `distribute_evenly`.
- worker: 36 passed. Tes baru `tests/test_auto_assign_schedule.py` menguji lima slot,
  jadwal lama tetap ada, dan saklar mati tidak menyentuh DB.
- core: 342 passed, 5 skipped. `qc_core.qc_auto_assign` ter-install dari wheel.
- dashboard: `npm test` 65 pass, `vite build` OK.
- Ketiga salinan `qc_auto_assign.py`, `stats_aggregate.py`, dan `ppt_error_rate.py`
  identik setelah prefix `qc_core.` dibuang.

## 5. Deploy (belum, perlu persetujuan terpisah)

Ikuti `deployment_guidelines.md`: tag `pre-4service-06102026`, build `TAG=cand`, diff
`pip freeze`, smoke test, retag, lalu `up -d --no-build`. Yang perlu di-rebuild: api,
worker (termasuk `beat`, karena `beat_schedule` berubah), dan dashboard. Env tidak perlu
diubah, karena saklarnya default mati.

Untuk menyalakan batch terjadwal nanti, isi `QC_AUTO_ASSIGN_ENABLED=true` di env **api**
(banner) dan **worker** (yang membagi), lalu restart `api`, `worker`, dan `beat`. Pastikan
worker kube memakai nilai yang dimaksud. Batch berjalan atas nama user `scheduler`.
