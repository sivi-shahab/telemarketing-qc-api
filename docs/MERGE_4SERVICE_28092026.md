# Merge `4-service-telemarketing-qc-system` branch `cashline_mus` → repo production (28 September 2026)

Status: **Merged (28 Sep 2026 18:08 WIB) dan deployed ke production 28 September 2026.**
PR api #31 (`ccc9fc0`), core #17 (`636326f`), worker #21 (`4444370`), dashboard #17 (`4272005`).
Alembic production **0062**. Rollback: image `local/qc-{api,worker,dashboard}:pre-cashline-mus` (lihat §7).

## 1. Ruang lingkup

| | Nilai |
|---|---|
| Repo sumber (A) | `4-service-telemarketing-qc-system`, branch `origin/cashline_mus` @ `f91aeac` (28 Sep 2026 11:13) |
| Port sebelumnya | A@`aec99ce` (21 Sep 2026, `MERGE_4SERVICE_21092026.md`) |
| Delta | A `aec99ce..f91aeac` — 11 commit, 31 file |
| HEAD production saat merge | api `a9fbfa6`, core `6734b34`, worker `1cb6b52`, dashboard `08fa71a` |
| DB production | schema `dashboard`, alembic `0060` |
| Branch di keempat repo | `merge/cashline-mus-28092026` |

```
f91aeac feat(perms): TL QC bisa Generate PPT Error Rate; skor akhir dipatok minimal 0
f4276b4 feat(cashline): pisahkan MUS CC dari scorecard/KB/prompt campaign Cashline
0ab67b4 style(ppt-error-rate): pakai palet, font & logo Bank Mega asli dari PPT acuan
a853b51 fix(ppt-error-rate): pisah slide Detail Error Reason & Top TLO Terburuk
1204a0e feat(stats): menu Generate PPT Error Rate Update
980b707 fix(db): paksa driver postgresql+psycopg2 di URL koneksi
b369f4e fix(assign-ticket): kosongkan pilihan QC setelah assign berhasil
d1b5db9 feat(qc-assignment): tombol "Lepas Semua" di menu Assign Ticket
8c48ce3 feat(stats): filter tanggal AI Status ikut berlaku di tab Failure Rate & Failure Reason
f6cb12a docs: SC_CL_43 di merge multi-rekaman, ... (tidak di-port, lihat §4)
503d146 test(parallel): SC_CL_43 tercakup merge multi-rekaman
```

## 2. Metode

Sama dengan 21 September: `git merge-file` per file, base = A@`aec99ce`, ours = production,
theirs = A@`f91aeac`, impor dinormalisasi (`core.x` → `x` / `qc_core.x`). Tiga salinan core
(api/core, worker/core, qc_core) tetap identik — diverifikasi dengan
`diff <(sed 's/qc_core\.//g' ...)`.

## 3. Yang masuk

| Fitur | Berkas | Catatan adaptasi production |
|---|---|---|
| Generate PPT Error Rate Update | `api/routers/stats.py` (`GET /stats/export_error_rate_pptx`), `core/compliance/ppt_error_rate.py` + `assets/bank-mega-logo.png`, `stats_aggregate.compute_top_tlo_by_aging`, dashboard `ErrorRatePptView.vue` + menu + route | A meng-`.gitignore` `dashboard/src/router/index.js`, jadi route `/dashboard/error-rate-ppt` ditambahkan manual. Endpoint diberi `reject_collection_only_stats` seperti endpoint Stats lain |
| Permission `stats.export.error_rate_ppt` | `api/permissions.py`, migrasi **0061** (spq_head/admin/demo) + **0062** (team_leader_qc) | A 0060/0061 dinomori ulang: prod 0060 = `timestamp_simpan_utc` |
| Filter tanggal tab Failure Rate & Failure Reason | `stats.py` (`_snapshot_for`, hierarchy, qc_performance, failure_reasons[_hierarchy]), `crud.qc_performance_rows`, `stats_aggregate` | Digabung dengan snapshot-latar production (`compute_fn(session)` + `session_factory=new_session`). `campaigns` TIDAK di-`or []` (None ≠ [] di production). Kunci cache tanpa tanggal tidak berubah. `ticket_chart_dates` membaca `crud.cashline_agent_index()` — versi A membaca tabel `tms_cashline` yang kosong di production |
| "Lepas Semua" (Assign Ticket) | `DELETE /qc_assignment`, `crud.bulk_unassign_tickets`, `AssignTicketView.vue` | View production memakai tickets-daily App C; tombolnya dipasang ulang gaya production — jumlahnya dari field `assigned` `GET /qc_assignment/unassigned` (se-cakupan, semua tanggal) |
| Pilihan QC dikosongkan setelah assign | `AssignTicketView.vue` | |
| MUS CC dipisah dari Cashline | `scoring.py` (MUS 36.75 → **50**, suku MUS CC 13.25 dihapus), `reference_data.py`, `EvaluationView.vue` | Lihat §5 — butuh upload campaign baru |
| Skor akhir minimal 0 | `scoring.phase3_score` | |
| Driver `postgresql+psycopg2` eksplisit | `api/dependencies.py`, `worker/config.py`, `db/migrations/env.py`, `alembic.ini` | Lapis kedua di atas `constraints.txt` |
| Dependensi | `core/requirements.txt` (api & worker), `pyproject.toml` qc-core | `python-pptx==1.0.2`, `lxml==6.1.3`, `XlsxWriter==3.2.9` dipin di kedua `constraints.txt` (hasil resolve di image `local/qc-api:latest`) |
| `_stats_signature` | `crud.py` | **v25 → v26** — skor dihitung saat baca, jadi snapshot lama basi |

## 4. Yang TIDAK di-port

* `docs/DEPLOYMENT.md` / `RUNBOOK.md` A: menyebut `CELERY_CONCURRENCY=4`; production memakai **8**
  (`docker exec telemarketing-qc-worker-worker-1 printenv CELERY_CONCURRENCY`, 28 Sep 2026).
* Catatan reproses massal 21 September di `CAMPAIGN_SCORING.md` A (lingkungan A, bukan production).

## 5. Dampak scoring pada tiket lama (diukur read-only di DB production)

`max_score` dihitung saat BACA, jadi tiket yang dinilai dengan scorecard lama (MUS 36.75 +
MUS CC) langsung memakai penyebut baru:

| | Jumlah |
|---|---|
| Result `done` yang dievaluasi | 530 |
| `max_score` berubah 136.75 → 150 | 325 |
| Status berubah | **1 tiket, `160759sRuF` FAIL → PASS** (122.2/136.75 → 135.45/150; 3 baris result) |
| Skor lama negatif (kini 0, status tetap FAIL) | 70 |

Item MUS tiket lama berbobot total 36.75, tetapi penyebutnya 50 — selisih 13.25 menjadi
"poin gratis" sampai tiket itu diproses ulang dengan campaign baru. Karena itu, sesudah deploy:

1. Upload campaign Cashline dari `docs/prompt_cashline_mus_v82_mus-cc-dipisah_25092026.txt`,
   `docs/cashline_kb_v38_mus-cc-dipisah_25092026.txt`,
   `docs/cashline_scorecard_v31_mus-cc-dipisah_25092026.txt` (nama versi di A tidak dinaikkan —
   isinya berbeda dari v82/v38 yang di-upload 21 September).
2. Pertimbangkan reproses tiket cashline yang punya `mus_interest` INTERESTED.

## 6. Verifikasi

* qc-core: **337 passed, 5 skipped** (+ tes baru `test_score_floor.py`, logo ikut ke paket).
* api: **316 passed, 178 skipped**. worker: **18 passed**.
* dashboard: `vite build` OK, `npm test` **58/58**.
* Smoke terhadap DB production dengan `default_transaction_read_only=on`, snapshot tidak
  disimpan: PPT Sep vs Agu 2026 → 18 slide, 110 KB, ±25 dtk; hierarki September 390 tiket;
  QC performance 78 (bertanggal) vs 79 (tanpa tanggal); failure reasons 247/390.

## 7. Deploy (28 September 2026)

Alur kandidat: tag `pre-cashline-mus`, `TAG=cand docker compose build`, bandingkan
`pip freeze` (yang boleh bertambah hanya `python-pptx`, `lxml`, `XlsxWriter`), smoke test,
retag `latest`, `up -d --no-build`. `alembic upgrade head` → **0062**. Rollback DB: `alembic
downgrade 0060` (keduanya hanya mengubah JSONB `roles.permissions`).

Image rollback: api `212f5638e9dd`, worker `7921940dcfbe`, dashboard `8bd37a6762b0`
(`local/qc-*:pre-cashline-mus`).

Catatan kejadian: rebuild pertama tanpa pin menarik SQLAlchemy 2.1.1 (driver bawaan
`postgresql://` jadi psycopg v3); api & worker crash-loop ±6 menit sampai di-rollback ke
`pre-*`. Diperbaiki dengan `constraints.txt` di api & worker (`326309c`) plus driver
`postgresql+psycopg2` eksplisit (§3). Sejak itu setiap deploy wajib lewat image kandidat.

### Pasca-deploy

- Campaign Cashline baru (MUS CC dipisah, scorecard 40 item, total 150, MUS 50) di-upload
  user 28 Sep 18:25 WIB dan diverifikasi identik dengan berkas `docs/`.
- Reproses seluruh tiket Cashline: job `fc086ac8-974f-4ca9-81d0-831257996122`, 18:37 → 22:23 WIB,
  **304/304 `done`** (dicek 29 Sep dari `dashboard.reprocess_job_items`). Tiket lama kini dinilai
  terhadap MUS 50 (lihat §5; 1 tiket, `160759sRuF`, berubah FAIL → PASS).
