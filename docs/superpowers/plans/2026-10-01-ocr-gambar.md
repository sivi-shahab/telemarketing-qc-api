# OCR Gambar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menu "OCR Gambar" untuk Admin dan user campaign Complaint Handling: upload beberapa JPG/PNG, worker menyalin teksnya lewat LLM vision, riwayat tersimpan dan bisa disalin/diunduh.

**Architecture:** API menyimpan gambar di bucket MinIO dokumen (`ocr-images/`) + baris `dashboard.ocr_images`, lalu mengirim satu task Celery per gambar. Worker memanggil deployment Azure `LLM_MODEL` dengan prompt OCR verbatim dan menyimpan teks. Akses: `menu.ocr_image` di role Admin/Demo, plus dihitung saat request untuk user yang campaign efektifnya ada di env `OCR_IMAGE_CAMPAIGNS`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (api), Celery + AzureOpenAI SDK (worker), Vue 3 + axios (dashboard), Pillow, MinIO, Postgres schema `dashboard`.

**Spec:** `telemarketing-qc-api/docs/superpowers/specs/2026-10-01-ocr-gambar-design.md`

## Global Constraints

- Repo yang disentuh: `telemarketing-qc-api`, `telemarketing-qc-worker`, `telemarketing-qc-core`, `telemarketing-qc-dashboard`. JANGAN sentuh `telemarketing-qc-system` (monolit beku).
- Semua kerja di branch `feat/ocr-gambar` di tiap repo (api sudah ada; buat di tiga repo lain dari `main`).
- Permission key persis: `menu.ocr_image`. Env persis: `OCR_IMAGE_CAMPAIGNS` (dipisah koma, trim + casefold, dibaca tiap panggilan).
- Task Celery persis: `worker.tasks.process_ocr_image.process_ocr_image`, argumen tunggal `image_id` (str UUID).
- Format diterima: `.jpg`, `.jpeg`, `.png` saja; 1–10 file per upload; ≤ 10 MB (10 * 1024 * 1024 byte) per file.
- Prefix objek MinIO: `ocr-images/{id}{ext}` di `MINIO_BUCKET_DOCUMENTS`. Tidak ada bucket/env MinIO baru.
- Kolom waktu `DateTime` naive (UTC), mengikuti tabel lain di codebase — BUKAN timestamptz.
- Status hanya: `pending`, `processing`, `done`, `failed`.
- Model `OcrImage` harus identik di tiga salinan: `telemarketing-qc-api/core/db/models.py`, `telemarketing-qc-worker/core/db/models.py`, `telemarketing-qc-core/src/qc_core/db/models.py`.
- Pemanggilan LLM untuk OCR TANPA `reasoning_effort`.
- Pesan galat ke user berbahasa Indonesia; teks pesan validasi di dashboard SAMA dengan teks di API.
- Test Python dijalankan di image (host tidak punya pytest) dengan `PYTHONPATH=/tmp/w/core:/tmp/w` dan cwd `/tmp` (bukan `/app`), lihat perintah di tiap task.
- Jangan deploy ke prod, jangan push. Task 7 hanya menyiapkan langkah deploy; eksekusinya menunggu konfirmasi user.

## Review Focus

1. **Batch campuran valid + tidak valid** (mis. 3 PNG + 1 PDF) → user mengharapkan tidak ada yang tersimpan sama sekali dan pesan yang menyebut file salahnya. Dipin di Task 3 (`test_satu_file_salah_tidak_ada_yang_tersimpan`).
2. **File berekstensi `.png` yang isinya bukan gambar** (rename dari PDF/teks) → 422, bukan task yang gagal di worker. Dipin di Task 3 (`test_png_palsu_ditolak`).
3. **Pesan Celery basi** (redelivery setelah row `done`/`failed`, atau row sudah dihapus) → worker tidak boleh menimpa hasil atau meledak. Dipin di Task 4 (`test_row_done_dilewati`, `test_row_failed_dilewati`, `test_row_hilang_dilewati`).
4. **User non-admin menebak id milik orang lain** pada detail/gambar/retry/hapus → 404, data tidak bocor. Dipin di Task 2 (`test_get_for_menolak_milik_orang_lain`) dan Task 3 (`test_detail_milik_orang_lain_404`).
5. **Gambar tanpa teks / model membalas kosong** → status `done` dengan `(tidak ada teks)`, bukan teks kosong yang tampak seperti error. Dipin di Task 4 (`test_balasan_kosong_jadi_penanda`).

---

## File Structure

| File | Tanggung jawab |
|---|---|
| api `api/permissions.py` | konstanta `MENU_OCR_IMAGE`, masuk `ALL_PERMISSIONS`, `ADMIN_ONLY_PERMISSIONS`, `_ADMIN_PERMISSIONS` |
| api `api/rbac.py` | `ocr_image_campaigns_from_env()`, `ocr_image_granted()`, hook di `permissions_for` |
| 3× `core/db/models.py` | ORM `OcrImage` |
| api `db/migrations/versions/0064_ocr_images.py` | tabel + index + grant admin/demo |
| api `api/ocr_image_store.py` (baru) | query ORM tabel `ocr_images` (create/list/get/reset/delete) |
| api `api/routers/ocr_image.py` (baru) | 6 endpoint, validasi upload |
| api `api/main.py` | daftarkan router |
| worker `worker/tasks/process_ocr_image.py` (baru) | `transcribe_image()` + task Celery |
| worker `worker/celery_app.py` | `include` task baru |
| dashboard `src/utils/ocrImage.js` (+ `.test.mjs`) | validasi file, nama .txt, status aktif |
| dashboard `src/views/upload/OcrImageView.vue` (baru) | halaman |
| dashboard `src/permissions.js`, `src/router/index.js`, `src/components/SidebarMenu.vue` | permission, route, menu |
| api `e2e/stub_llm/app.py`, `e2e/.env.e2e`, `e2e/tests/test_09_ocr_gambar.py` | e2e |

---

### Task 1: Permission `menu.ocr_image` dan gate campaign

**Files:**
- Modify: `telemarketing-qc-api/api/permissions.py` (konstanta di dekat `MENU_COLLECTION_RESULTS` baris ~68; `ALL_PERMISSIONS` ~166; `ADMIN_ONLY_PERMISSIONS` ~222; `_ADMIN_PERMISSIONS` ~401)
- Modify: `telemarketing-qc-api/api/rbac.py` (`collection_campaigns_from_env` ~103; `permissions_for` ~141)
- Test: `telemarketing-qc-api/tests/test_ocr_image_rbac.py`

**Interfaces:**
- Produces: `api.permissions.MENU_OCR_IMAGE = "menu.ocr_image"`; `api.rbac.ocr_image_campaigns_from_env() -> frozenset`; `api.rbac.ocr_image_granted(campaigns: list | None, ocr_campaigns: frozenset) -> bool`. `permissions_for` mengembalikan `set` yang memuat `MENU_OCR_IMAGE` bila berhak.

- [ ] **Step 1: Write the failing test**

`tests/test_ocr_image_rbac.py`:

```python
"""Siapa yang mendapat menu OCR Gambar (``menu.ocr_image``).

Admin/Demo memegangnya lewat role. User lain hanya bila campaign efektifnya
tercantum di env ``OCR_IMAGE_CAMPAIGNS`` — dihitung saat request, sama seperti
menu Collection Results, supaya menu DAN endpoint tertutup bersamaan.
"""
from types import SimpleNamespace

from api import permissions as P
from api import rbac


OCR = frozenset({"complaint handling"})


def test_campaign_tercantum_diberi():
    assert rbac.ocr_image_granted(["Complaint Handling"], OCR)


def test_nama_dicocokkan_tanpa_peduli_spasi_dan_kapital():
    assert rbac.ocr_image_granted(["  COMPLAINT handling "], OCR)


def test_campaign_lain_tidak_diberi():
    assert not rbac.ocr_image_granted(["Telemarketing", "Cashline", "Collection"], OCR)


def test_tanpa_batas_campaign_tidak_diberi():
    """``None`` = tidak dibatasi (mis. SPQ Head pusat) — bukan berarti memegang
    Complaint Handling secara eksplisit."""
    assert not rbac.ocr_image_granted(None, OCR)


def test_env_kosong_tidak_diberi():
    assert not rbac.ocr_image_granted(["Complaint Handling"], frozenset())


def test_env_dibaca_tiap_panggilan(monkeypatch):
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", " Complaint Handling , ,X ")
    assert rbac.ocr_image_campaigns_from_env() == frozenset({"complaint handling", "x"})
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "")
    assert rbac.ocr_image_campaigns_from_env() == frozenset()


def test_admin_memegang_lewat_role_dan_admin_only():
    assert P.MENU_OCR_IMAGE == "menu.ocr_image"
    assert P.MENU_OCR_IMAGE in P.ALL_PERMISSIONS
    assert P.MENU_OCR_IMAGE in P.ADMIN_ONLY_PERMISSIONS
    assert P.MENU_OCR_IMAGE in P.DEFAULT_ROLES["admin"]["permissions"]


def _patch_role(monkeypatch, perms, campaigns):
    monkeypatch.setattr(rbac, "_role_def", lambda db, key: {
        "permissions": list(perms), "data_scope": "qc_assigned", "campaigns": [],
    })
    monkeypatch.setattr(rbac, "effective_campaigns_for", lambda db, user: campaigns)
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection,Complaint Handling")


def test_permissions_for_menambahkan_untuk_user_complaint_handling(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE in out


def test_permissions_for_tidak_menambahkan_untuk_user_cashline(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Telemarketing", "Cashline"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE not in out


def test_permissions_for_env_ocr_kosong(monkeypatch):
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE not in out


def test_permissions_for_saat_collection_mati(monkeypatch):
    """Cabang ``COLLECTION_CAMPAIGNS`` kosong punya return lebih awal — gate OCR
    tetap harus berlaku di sana."""
    _patch_role(monkeypatch, [P.MENU_RESULTS], ["Complaint Handling"])
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    monkeypatch.setenv("OCR_IMAGE_CAMPAIGNS", "Complaint Handling")
    out = rbac.permissions_for(None, SimpleNamespace(role="qc", id=1))
    assert P.MENU_OCR_IMAGE in out
```

- [ ] **Step 2: Run test to verify it fails**

Run (dari `/data/scorecard_v2`):
```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-api:/src:ro -w /tmp local/qc-api:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests/test_ocr_image_rbac.py'
```
Expected: FAIL — `AttributeError: module 'api.rbac' has no attribute 'ocr_image_granted'`.

- [ ] **Step 3: Implement**

`api/permissions.py` — di bawah `MENU_COLLECTION_RESULTS = "menu.collection_results"` tambahkan:

```python
# Menu OCR Gambar (1 Oktober 2026): alat OCR mandiri. Admin/Demo memegangnya lewat
# role; user lain mendapatkannya saat request bila campaign efektifnya tercantum di
# env ``OCR_IMAGE_CAMPAIGNS`` (lihat ``api.rbac.permissions_for``). Admin-only di
# level role, jadi tidak muncul di checkbox Manage Role.
MENU_OCR_IMAGE = "menu.ocr_image"
```

Tambahkan `MENU_OCR_IMAGE,` ke `ALL_PERMISSIONS` tepat setelah `MENU_COLLECTION_RESULTS,`; ke `ADMIN_ONLY_PERMISSIONS` tepat setelah `MENU_COLLECTION_RESULTS,`; dan ke `_ADMIN_PERMISSIONS` tepat setelah baris `MENU_ROLE_HIERARCHY,`.

`api/rbac.py` — di bawah `collection_campaigns_from_env()` tambahkan:

```python
def ocr_image_campaigns_from_env() -> frozenset:
    """Campaign yang membuka menu OCR Gambar, dari env ``OCR_IMAGE_CAMPAIGNS``.

    Dibaca tiap kali seperti ``collection_campaigns_from_env``. Kosong = hanya
    Admin/Demo (lewat role) yang memegang menu itu — itu pula bentuk rollback-nya.
    """
    return parse_collection_campaigns(os.getenv("OCR_IMAGE_CAMPAIGNS", ""))


def ocr_image_granted(campaigns, ocr_campaigns) -> bool:
    """Apakah campaign efektif user memuat salah satu campaign OCR Gambar.

    ``None`` (tidak dibatasi) TIDAK dihitung: menu ini untuk orang yang memegang
    campaign itu secara eksplisit, bukan untuk setiap login tanpa batas campaign.
    """
    if not ocr_campaigns or not campaigns:
        return False
    return any(str(c or "").strip().casefold() in ocr_campaigns for c in campaigns)
```

Ganti nama fungsi `permissions_for` yang ada menjadi `_base_permissions_for` (isi tidak diubah), lalu tambahkan di bawahnya:

```python
def permissions_for(db: Session, user) -> set:
    """Capability efektif user — sumber tunggal untuk menu (``/auth/me``) MAUPUN
    gate endpoint (``require``). Lihat ``_base_permissions_for`` untuk penyesuaian
    collection; di sini ditambahkan menu OCR Gambar (``OCR_IMAGE_CAMPAIGNS``).
    """
    out = set(_base_permissions_for(db, user))
    if perms.MENU_OCR_IMAGE not in out:
        ocr = ocr_image_campaigns_from_env()
        if ocr and ocr_image_granted(effective_campaigns_for(db, user), ocr):
            out.add(perms.MENU_OCR_IMAGE)
    return out
```

Pindahkan docstring lama `permissions_for` ke `_base_permissions_for` apa adanya.

- [ ] **Step 4: Run test to verify it passes**

Run: perintah Step 2 → Expected: `11 passed`.
Lalu jalankan test rbac yang sudah ada untuk regresi:
```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-api:/src:ro -w /tmp local/qc-api:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests/test_rbac_collection_permissions.py /tmp/w/tests/test_telemarketing_campaign_group.py'
```
Expected: semua PASS (test yang butuh DB boleh `skipped`).

- [ ] **Step 5: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add api/permissions.py api/rbac.py tests/test_ocr_image_rbac.py
git commit -m "feat(rbac): menu.ocr_image untuk Admin + campaign OCR_IMAGE_CAMPAIGNS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Tabel `ocr_images`, model ORM, dan store

**Files:**
- Modify: `telemarketing-qc-api/core/db/models.py`, `telemarketing-qc-worker/core/db/models.py`, `telemarketing-qc-core/src/qc_core/db/models.py` (tambah kelas setelah `class Document`)
- Create: `telemarketing-qc-api/db/migrations/versions/0064_ocr_images.py`
- Create: `telemarketing-qc-api/api/ocr_image_store.py`
- Test: `telemarketing-qc-api/tests/test_ocr_image_store.py`

**Interfaces:**
- Consumes: `MENU_OCR_IMAGE` (Task 1) — hanya sebagai string `"menu.ocr_image"` di migrasi.
- Produces:
  - `db.models.OcrImage` (kolom: `id` UUID, `user_id` int, `batch_id` UUID, `filename`, `object_path`, `mime_type`, `size_bytes` int, `status`, `text`, `error_message`, `token_usage` JSONB, `created_at`, `started_at`, `finished_at`).
  - `api.ocr_image_store.create(db, *, image_id: uuid.UUID, user_id: int, batch_id: uuid.UUID, filename: str, object_path: str, mime_type: str, size_bytes: int) -> OcrImage`
  - `api.ocr_image_store.list_for(db, *, owner_id: int | None, page: int, page_size: int) -> tuple[list[tuple[OcrImage, str | None]], int]` — tuple kedua = nama pengunggah (`users.name` atau `username`).
  - `api.ocr_image_store.get_for(db, image_id: str, *, owner_id: int | None) -> OcrImage | None`
  - `api.ocr_image_store.reset_pending(db, row: OcrImage) -> None`
  - `api.ocr_image_store.delete(db, row: OcrImage) -> None`
  - `owner_id=None` berarti tanpa filter pemilik (Admin).

- [ ] **Step 1: Create branches in the other repos**

```bash
cd /data/scorecard_v2
for r in telemarketing-qc-worker telemarketing-qc-core telemarketing-qc-dashboard; do
  git -C $r status --short | head -3; git -C $r checkout -b feat/ocr-gambar main
done
```
Expected: tiap repo bersih, `Switched to a new branch 'feat/ocr-gambar'`.

- [ ] **Step 2: Write the failing test**

`tests/test_ocr_image_store.py`:

```python
"""Query tabel ``ocr_images`` — terutama isolasi riwayat per pengunggah.

Memakai fixture ``db`` (transaksi yang selalu di-rollback). Dijalankan terhadap
Postgres e2e (``e2e-pg``) yang sudah dimigrasi sampai 0064; di luar jaringan itu
test dilewati.
"""
import uuid

import pytest

from api import ocr_image_store as store
from db.models import OcrImage, User


def _user(db, nama):
    u = User(username=f"zz-ocr-{nama}-{uuid.uuid4().hex[:6]}", name=f"ZZ {nama}",
             email=f"{uuid.uuid4().hex[:10]}@zz.local", hashed_password="x", role="qc")
    db.add(u)
    db.flush()
    return u


def _img(db, user, filename="a.png"):
    image_id = uuid.uuid4()
    return store.create(db, image_id=image_id, user_id=user.id, batch_id=uuid.uuid4(),
                        filename=filename, object_path=f"ocr-images/{image_id}.png",
                        mime_type="image/png", size_bytes=10)


def test_create_menyimpan_pending(db):
    row = _img(db, _user(db, "a"))
    assert row.status == "pending"
    assert db.get(OcrImage, row.id) is not None


def test_list_for_hanya_milik_sendiri(db):
    a, b = _user(db, "a"), _user(db, "b")
    mine = _img(db, a)
    _img(db, b)
    rows, total = store.list_for(db, owner_id=a.id, page=1, page_size=50)
    assert total == 1
    assert [r.id for r, _ in rows] == [mine.id]


def test_list_for_admin_melihat_semua_dengan_nama(db):
    a, b = _user(db, "a"), _user(db, "b")
    ids = {_img(db, a).id, _img(db, b).id}
    rows, _ = store.list_for(db, owner_id=None, page=1, page_size=1000)
    seen = {r.id: nama for r, nama in rows if r.id in ids}
    assert set(seen) == ids
    assert set(seen.values()) == {"ZZ a", "ZZ b"}


def test_list_for_paginasi(db):
    a = _user(db, "a")
    for i in range(3):
        _img(db, a, filename=f"{i}.png")
    rows, total = store.list_for(db, owner_id=a.id, page=2, page_size=2)
    assert total == 3
    assert len(rows) == 1


def test_get_for_menolak_milik_orang_lain(db):
    a, b = _user(db, "a"), _user(db, "b")
    row = _img(db, b)
    assert store.get_for(db, str(row.id), owner_id=a.id) is None
    assert store.get_for(db, str(row.id), owner_id=b.id).id == row.id
    assert store.get_for(db, str(row.id), owner_id=None).id == row.id


def test_get_for_id_bukan_uuid(db):
    assert store.get_for(db, "bukan-uuid", owner_id=None) is None


def test_reset_pending_membersihkan_hasil(db):
    row = _img(db, _user(db, "a"))
    row.status, row.error_message, row.text = "failed", "boom", "x"
    db.flush()
    store.reset_pending(db, row)
    assert (row.status, row.error_message, row.text, row.started_at, row.finished_at) == (
        "pending", None, None, None, None)


def test_delete_menghapus_baris(db):
    row = _img(db, _user(db, "a"))
    store.delete(db, row)
    assert db.get(OcrImage, row.id) is None
```

- [ ] **Step 3: Add the model to all three core copies**

Tambahkan tepat setelah kelas `Document` di KETIGA file `core/db/models.py` (isi identik; semua import yang dipakai sudah ada di kepala file):

```python
class OcrImage(Base):
    """Gambar yang di-upload ke menu OCR Gambar, beserta teks hasil OCR-nya.

    Alat mandiri (1 Oktober 2026): tidak terikat tiket/result. Satu baris per
    gambar; ``batch_id`` mengelompokkan gambar dari satu kali upload. Gambarnya
    ada di bucket dokumen dengan prefix ``ocr-images/``.
    """
    __tablename__ = "ocr_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), nullable=False)
    filename = Column(String(255), nullable=False)
    object_path = Column(String(512), nullable=False)
    mime_type = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="pending")  # pending|processing|done|failed
    text = Column(Text)
    error_message = Column(Text)
    token_usage = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
```

Verifikasi ketiganya identik:
```bash
cd /data/scorecard_v2
diff telemarketing-qc-api/core/db/models.py telemarketing-qc-worker/core/db/models.py && \
diff <(sed 's/qc_core\.//g' telemarketing-qc-core/src/qc_core/db/models.py) telemarketing-qc-api/core/db/models.py && echo IDENTIK
```
Expected: `IDENTIK`.

- [ ] **Step 4: Write the migration**

`db/migrations/versions/0064_ocr_images.py`:

```python
"""Tabel ocr_images + menu OCR Gambar untuk Admin/Demo

Alat OCR mandiri (1 Oktober 2026): gambar yang di-upload disalin teksnya oleh
worker (``worker.tasks.process_ocr_image``) dan disimpan sebagai riwayat.

``menu.ocr_image`` ditambahkan ke role ``admin`` dan ``demo`` lewat pembaruan
JSONB (pola 0063) agar role yang sudah disesuaikan operator tidak tertimpa. User
non-admin mendapatkannya saat request lewat ``OCR_IMAGE_CAMPAIGNS``, bukan di sini.

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERM = "menu.ocr_image"
_ROLES = ("admin", "demo")


def upgrade() -> None:
    op.create_table(
        "ocr_images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("text", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("token_usage", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("idx_ocr_images_user_created", "ocr_images", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_ocr_images_batch", "ocr_images", ["batch_id"])
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || to_jsonb(CAST(:perm AS text)) "
            "WHERE key = ANY(:keys) AND NOT jsonb_exists(permissions, :perm)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "(SELECT COALESCE(jsonb_agg(v), '[]'::jsonb) "
            " FROM jsonb_array_elements(permissions) v "
            " WHERE v <> to_jsonb(CAST(:perm AS text))) "
            "WHERE key = ANY(:keys)"
        ),
        {"perm": _PERM, "keys": list(_ROLES)},
    )
    op.drop_index("idx_ocr_images_batch")
    op.drop_index("idx_ocr_images_user_created")
    op.drop_table("ocr_images")
```

- [ ] **Step 5: Write the store**

`api/ocr_image_store.py`:

```python
"""Akses data tabel ``ocr_images`` (menu OCR Gambar).

``owner_id=None`` berarti tanpa filter pemilik — hanya untuk Admin/Demo. Router
yang menentukan nilainya; modul ini tidak mengenal role.
"""
import uuid

from sqlalchemy.orm import Session

from db.models import OcrImage, User


def create(db: Session, *, image_id, user_id, batch_id, filename, object_path,
           mime_type, size_bytes) -> OcrImage:
    row = OcrImage(id=image_id, user_id=user_id, batch_id=batch_id, filename=filename,
                   object_path=object_path, mime_type=mime_type, size_bytes=size_bytes,
                   status="pending")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_for(db: Session, *, owner_id, page: int, page_size: int):
    """``([(OcrImage, nama_pengunggah), ...], total)``, terbaru dulu."""
    q = db.query(OcrImage, User.name, User.username).outerjoin(User, User.id == OcrImage.user_id)
    if owner_id is not None:
        q = q.filter(OcrImage.user_id == owner_id)
    total = q.count()
    rows = (
        q.order_by(OcrImage.created_at.desc(), OcrImage.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [(row, name or username) for row, name, username in rows], total


def get_for(db: Session, image_id, *, owner_id):
    try:
        uid = uuid.UUID(str(image_id))
    except ValueError:
        return None
    q = db.query(OcrImage).filter(OcrImage.id == uid)
    if owner_id is not None:
        q = q.filter(OcrImage.user_id == owner_id)
    return q.first()


def reset_pending(db: Session, row: OcrImage) -> None:
    row.status = "pending"
    row.text = None
    row.error_message = None
    row.started_at = None
    row.finished_at = None
    db.commit()


def delete(db: Session, row: OcrImage) -> None:
    db.delete(row)
    db.commit()
```

- [ ] **Step 6: Migrate the e2e Postgres and run the test**

Stack e2e menjalankan `alembic upgrade head` saat `e2e-api` start:
```bash
cd /data/scorecard_v2/telemarketing-qc-api/e2e
docker compose -f docker-compose.e2e.yml up -d --build e2e-api
until [ "$(docker inspect -f '{{.State.Health.Status}}' e2e-api 2>/dev/null)" = "healthy" ]; do sleep 2; done
docker exec e2e-pg psql -U qce2e -d qce2e -c "select version_num from dashboard.alembic_version" -c "\d dashboard.ocr_images"
```
Expected: `0064` dan definisi tabel tampil.

```bash
docker run --rm --network qc-e2e-net \
  -e POSTGRES_HOST=e2e-pg -e POSTGRES_PORT=5432 -e POSTGRES_DB=qce2e -e POSTGRES_USER=qce2e \
  -e POSTGRES_PASSWORD=qce2e-pass -e POSTGRES_SCHEMA=dashboard \
  -v /data/scorecard_v2/telemarketing-qc-api:/src:ro -w /tmp local/qc-api:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests/test_ocr_image_store.py'
```
Expected: `8 passed` (BUKAN `skipped` — kalau skipped, DB tidak terjangkau; perbaiki dulu).

- [ ] **Step 7: Verify downgrade/upgrade round-trip**

```bash
docker exec e2e-api sh -c 'cd /app && alembic downgrade 0063 && alembic upgrade head'
docker exec e2e-pg psql -U qce2e -d qce2e -tAc "select permissions ? 'menu.ocr_image' from dashboard.roles where key='admin'"
```
Expected: tanpa error; `t`.

- [ ] **Step 8: Commit (three repos)**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add core/db/models.py db/migrations/versions/0064_ocr_images.py api/ocr_image_store.py tests/test_ocr_image_store.py
git commit -m "feat(db): tabel ocr_images (migrasi 0064) + store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
for r in ../telemarketing-qc-worker ../telemarketing-qc-core; do
  f=$( [ $r = ../telemarketing-qc-core ] && echo src/qc_core/db/models.py || echo core/db/models.py )
  git -C $r add $f && git -C $r commit -m "feat(db): model OcrImage (sinkron dengan qc-api 0064)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
done
```

---

### Task 3: Router API OCR Gambar

**Files:**
- Create: `telemarketing-qc-api/api/routers/ocr_image.py`
- Modify: `telemarketing-qc-api/api/main.py:9` (import) dan setelah `app.include_router(collection.router)` (baris ~61)
- Test: `telemarketing-qc-api/tests/test_ocr_image_router.py`

**Interfaces:**
- Consumes: `api.ocr_image_store.*` (Task 2), `api.permissions.MENU_OCR_IMAGE`, `api.permissions.ADMIN_LIKE_ROLES`, `api.rbac.require` (Task 1).
- Produces (HTTP, semua di belakang `require(MENU_OCR_IMAGE)`):
  - `POST /ocr_images` multipart field `files` (berulang) → `{"batch_id": str, "items": [Summary]}`
  - `GET /ocr_images?page=1&page_size=20` → `{"items": [Summary], "total": int, "page": int, "page_size": int}`
  - `GET /ocr_images/{id}` → `Summary + {"mime_type", "text", "error_message"}`
  - `GET /ocr_images/{id}/image` → bytes gambar
  - `POST /ocr_images/{id}/retry` → `Summary`
  - `DELETE /ocr_images/{id}` → `{"deleted": id}`
  - `Summary = {"id","batch_id","filename","status","size_bytes","created_at","finished_at"}` + `"uploader_name"` hanya untuk Admin/Demo. Waktu ISO-8601 UTC berakhiran `Z`, atau `null`.
  - Konstanta modul: `MAX_FILES = 10`, `MAX_BYTES = 10 * 1024 * 1024`, `OBJECT_PREFIX = "ocr-images/"`, `TASK_NAME = "worker.tasks.process_ocr_image.process_ocr_image"`.

- [ ] **Step 1: Write the failing test**

`tests/test_ocr_image_router.py`:

```python
"""Router OCR Gambar — dipanggil sebagai fungsi Python, tanpa DB/MinIO/Celery.

Store, MinIO, dan Celery diganti tiruan lewat ``monkeypatch``. Isolasi riwayat di
level query diuji di ``test_ocr_image_store.py``; di sini yang diuji keputusan
router: validasi upload, owner filter per role, retry, dan hapus.
"""
import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from api.routers import ocr_image as mod


def _png(size=(4, 4)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def _upload(name, data):
    return UploadFile(filename=name, file=io.BytesIO(data))


class FakeStore:
    def __init__(self):
        self.rows = {}

    def create(self, db, *, image_id, user_id, batch_id, filename, object_path, mime_type, size_bytes):
        row = SimpleNamespace(id=image_id, user_id=user_id, batch_id=batch_id, filename=filename,
                              object_path=object_path, mime_type=mime_type, size_bytes=size_bytes,
                              status="pending", text=None, error_message=None,
                              created_at=None, finished_at=None)
        self.rows[str(image_id)] = row
        return row

    def get_for(self, db, image_id, *, owner_id):
        row = self.rows.get(str(image_id))
        if row is None or (owner_id is not None and row.user_id != owner_id):
            return None
        return row

    def list_for(self, db, *, owner_id, page, page_size):
        rows = [(r, "Nama") for r in self.rows.values() if owner_id is None or r.user_id == owner_id]
        return rows, len(rows)

    def reset_pending(self, db, row):
        row.status = "pending"

    def delete(self, db, row):
        self.rows.pop(str(row.id))


@pytest.fixture()
def env(monkeypatch):
    store, sent, put, removed = FakeStore(), [], [], []
    monkeypatch.setattr(mod, "store", store)
    monkeypatch.setattr(mod, "get_settings", lambda: SimpleNamespace(minio_bucket_documents="docs"))
    monkeypatch.setattr(mod, "get_minio", lambda: SimpleNamespace(
        put_object=lambda bucket, name, data, length, content_type: put.append((bucket, name, content_type)),
        remove_object=lambda bucket, name: removed.append((bucket, name)),
    ))
    import api.celery_client as cc
    monkeypatch.setattr(cc, "celery_app", SimpleNamespace(
        send_task=lambda name, args: sent.append((name, args))))
    return SimpleNamespace(store=store, sent=sent, put=put, removed=removed)


QC = SimpleNamespace(id=7, role="qc")
QC_LAIN = SimpleNamespace(id=8, role="qc")
ADMIN = SimpleNamespace(id=1, role="admin")


def _status(exc_info):
    return exc_info.value.status_code


def test_upload_valid_menyimpan_dan_mengirim_task(env):
    out = mod.upload_ocr_images(files=[_upload("a.png", _png()), _upload("b.JPG", _jpg())],
                                db=None, current_user=QC)
    assert len(out["items"]) == 2
    assert all(i["status"] == "pending" for i in out["items"])
    assert [n for n, _ in env.sent] == [mod.TASK_NAME, mod.TASK_NAME]
    assert {a[0] for _, a in env.sent} == {i["id"] for i in out["items"]}
    assert all(name.startswith("ocr-images/") for _, name, _ in env.put)
    assert {ct for _, _, ct in env.put} == {"image/png", "image/jpeg"}
    assert "uploader_name" not in out["items"][0]


def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_tanpa_file_ditolak(env):
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[], db=None, current_user=QC)
    assert _status(e) == 422


def test_lebih_dari_10_file_ditolak(env):
    files = [_upload(f"{i}.png", _png()) for i in range(11)]
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=files, db=None, current_user=QC)
    assert _status(e) == 422 and "Maksimal 10" in e.value.detail


def test_file_lebih_dari_10mb_ditolak(env, monkeypatch):
    monkeypatch.setattr(mod, "MAX_BYTES", 50)
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[_upload("a.png", _png((64, 64)))], db=None, current_user=QC)
    assert _status(e) == 422 and "melebihi 10 MB" in e.value.detail


def test_ekstensi_lain_ditolak(env):
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[_upload("a.gif", _png())], db=None, current_user=QC)
    assert _status(e) == 422 and "bukan JPG/PNG" in e.value.detail


def test_png_palsu_ditolak(env):
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[_upload("a.png", b"%PDF-1.4 bukan gambar")], db=None, current_user=QC)
    assert _status(e) == 422 and "tidak valid" in e.value.detail


def test_satu_file_salah_tidak_ada_yang_tersimpan(env):
    files = [_upload("a.png", _png()), _upload("b.png", _png()), _upload("c.pdf", b"%PDF")]
    with pytest.raises(HTTPException):
        mod.upload_ocr_images(files=files, db=None, current_user=QC)
    assert env.put == [] and env.sent == [] and env.store.rows == {}


def _seed(env, user, status="done"):
    out = mod.upload_ocr_images(files=[_upload("a.png", _png())], db=None, current_user=user)
    row = env.store.rows[out["items"][0]["id"]]
    row.status, row.text = status, "TEKS"
    env.sent.clear()
    return row


def test_list_non_admin_tanpa_nama_pengunggah(env):
    _seed(env, QC)
    _seed(env, QC_LAIN)
    out = mod.list_ocr_images(page=1, page_size=20, db=None, current_user=QC)
    assert out["total"] == 1 and "uploader_name" not in out["items"][0]


def test_list_admin_melihat_semua_dengan_nama(env):
    _seed(env, QC)
    _seed(env, QC_LAIN)
    out = mod.list_ocr_images(page=1, page_size=20, db=None, current_user=ADMIN)
    assert out["total"] == 2 and out["items"][0]["uploader_name"] == "Nama"


def test_detail_berisi_teks(env):
    row = _seed(env, QC)
    out = mod.get_ocr_image(image_id=str(row.id), db=None, current_user=QC)
    assert out["text"] == "TEKS"


def test_detail_milik_orang_lain_404(env):
    row = _seed(env, QC_LAIN)
    for fn in (mod.get_ocr_image, mod.retry_ocr_image, mod.delete_ocr_image, mod.ocr_image_file):
        with pytest.raises(HTTPException) as e:
            fn(image_id=str(row.id), db=None, current_user=QC)
        assert _status(e) == 404


def test_retry_hanya_untuk_failed(env):
    row = _seed(env, QC, status="done")
    with pytest.raises(HTTPException) as e:
        mod.retry_ocr_image(image_id=str(row.id), db=None, current_user=QC)
    assert _status(e) == 409
    row.status = "failed"
    out = mod.retry_ocr_image(image_id=str(row.id), db=None, current_user=QC)
    assert out["status"] == "pending"
    assert env.sent == [(mod.TASK_NAME, [str(row.id)])]


def test_delete_menghapus_objek_dan_baris(env):
    row = _seed(env, QC)
    mod.delete_ocr_image(image_id=str(row.id), db=None, current_user=ADMIN)
    assert env.removed == [("docs", row.object_path)]
    assert str(row.id) not in env.store.rows


def test_delete_tetap_jalan_bila_objek_hilang(env, monkeypatch):
    row = _seed(env, QC)

    def boom(bucket, name):
        raise RuntimeError("NoSuchKey")
    monkeypatch.setattr(mod, "get_minio", lambda: SimpleNamespace(remove_object=boom))
    mod.delete_ocr_image(image_id=str(row.id), db=None, current_user=QC)
    assert str(row.id) not in env.store.rows


def test_page_size_dibatasi(env):
    with pytest.raises(HTTPException) as e:
        mod.list_ocr_images(page=1, page_size=500, db=None, current_user=QC)
    assert _status(e) == 422
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-api:/src:ro -w /tmp local/qc-api:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests/test_ocr_image_router.py'
```
Expected: FAIL — `ImportError: cannot import name 'ocr_image' from 'api.routers'`.

- [ ] **Step 3: Implement the router**

`api/routers/ocr_image.py`:

```python
"""Menu OCR Gambar: upload JPG/PNG, worker menyalin teksnya, riwayat per pengunggah.

Alat mandiri (1 Oktober 2026) — tidak terikat tiket/result. Seluruh router di
belakang ``menu.ocr_image`` (Admin/Demo lewat role, user lain lewat
``OCR_IMAGE_CAMPAIGNS``, lihat ``api.rbac.permissions_for``). Non-admin hanya
melihat baris miliknya; milik orang lain dijawab 404 supaya keberadaannya tidak
bocor.
"""
import io
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy.orm import Session

from api import ocr_image_store as store
from api.dependencies import get_current_user, get_db, get_minio, get_settings
from api.permissions import ADMIN_LIKE_ROLES, MENU_OCR_IMAGE
from api.rbac import require

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require(MENU_OCR_IMAGE))])

MAX_FILES = 10
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGE_SIZE = 100
OBJECT_PREFIX = "ocr-images/"
TASK_NAME = "worker.tasks.process_ocr_image.process_ocr_image"
_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_PIL_FORMATS = {"JPEG", "PNG"}


def _owner_id(current_user):
    return None if getattr(current_user, "role", None) in ADMIN_LIKE_ROLES else current_user.id


def _is_admin(current_user) -> bool:
    return _owner_id(current_user) is None


def _invalid(detail: str):
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _is_image(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
        return fmt in _PIL_FORMATS
    except Exception:
        return False


def _read_validated(files):
    """Baca & periksa SEMUA file sebelum apa pun disimpan: satu salah = tolak semua."""
    if not files:
        raise _invalid("Pilih minimal satu gambar")
    if len(files) > MAX_FILES:
        raise _invalid(f"Maksimal {MAX_FILES} gambar per upload")
    out = []
    for f in files:
        name = f.filename or ""
        ext = os.path.splitext(name)[1].lower()
        if ext not in _EXT_MIME:
            raise _invalid(f"File '{name}' bukan JPG/PNG — hanya file JPG/PNG yang diterima")
        data = f.file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise _invalid(f"File '{name}' melebihi 10 MB")
        if not _is_image(data):
            raise _invalid(f"File '{name}' bukan gambar JPG/PNG yang valid")
        out.append((name, data, ext, _EXT_MIME[ext]))
    return out


def _iso(dt):
    return dt.isoformat() + "Z" if dt is not None else None


def _summary(row, uploader_name=None, admin=False) -> dict:
    out = {
        "id": str(row.id),
        "batch_id": str(row.batch_id),
        "filename": row.filename,
        "status": row.status,
        "size_bytes": row.size_bytes,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
    }
    if admin:
        out["uploader_name"] = uploader_name
    return out


def _get_or_404(db, image_id, current_user):
    row = store.get_for(db, image_id, owner_id=_owner_id(current_user))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gambar tidak ditemukan")
    return row


def _send(image_id) -> None:
    from api.celery_client import celery_app

    celery_app.send_task(TASK_NAME, args=[str(image_id)])


@router.post("/ocr_images")
def upload_ocr_images(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    checked = _read_validated(files)
    settings = get_settings()
    client = get_minio()
    batch_id = uuid.uuid4()
    rows = []
    for name, data, ext, mime in checked:
        image_id = uuid.uuid4()
        object_path = f"{OBJECT_PREFIX}{image_id}{ext}"
        client.put_object(settings.minio_bucket_documents, object_path, io.BytesIO(data),
                          length=len(data), content_type=mime)
        rows.append(store.create(db, image_id=image_id, user_id=current_user.id, batch_id=batch_id,
                                 filename=name, object_path=object_path, mime_type=mime,
                                 size_bytes=len(data)))
    for row in rows:
        _send(row.id)
    return {"batch_id": str(batch_id), "items": [_summary(r) for r in rows]}


@router.get("/ocr_images")
def list_ocr_images(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise _invalid(f"page minimal 1 dan page_size 1–{MAX_PAGE_SIZE}")
    admin = _is_admin(current_user)
    rows, total = store.list_for(db, owner_id=_owner_id(current_user), page=page, page_size=page_size)
    return {
        "items": [_summary(r, name, admin) for r, name in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/ocr_images/{image_id}")
def get_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    out = _summary(row)
    out.update(mime_type=row.mime_type, text=row.text, error_message=row.error_message)
    return out


@router.get("/ocr_images/{image_id}/image")
def ocr_image_file(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    settings = get_settings()
    response = None
    try:
        response = get_minio().get_object(settings.minio_bucket_documents, row.object_path)
        data = response.read()
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="File gambar tidak ditemukan di storage")
    finally:
        if response is not None:
            try:
                response.close()
                response.release_conn()
            except Exception:
                pass
    return StreamingResponse(io.BytesIO(data), media_type=row.mime_type,
                             headers={"Content-Disposition": f'inline; filename="{row.filename}"'})


@router.post("/ocr_images/{image_id}/retry")
def retry_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    if row.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Hanya gambar berstatus gagal yang bisa diproses ulang")
    store.reset_pending(db, row)
    _send(row.id)
    return _summary(row)


@router.delete("/ocr_images/{image_id}")
def delete_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    settings = get_settings()
    try:
        get_minio().remove_object(settings.minio_bucket_documents, row.object_path)
    except Exception:
        # Objek yang tertinggal lebih murah daripada baris yang tak bisa dihapus.
        logger.warning("gagal menghapus objek %s; baris tetap dihapus", row.object_path, exc_info=True)
    store.delete(db, row)
    return {"deleted": str(image_id)}
```

Catatan: test `test_detail_milik_orang_lain_404` memanggil `ocr_image_file` — 404 terjadi di `_get_or_404` sebelum MinIO disentuh.

`api/main.py`: tambahkan `ocr_image` ke daftar import `from api.routers import ...` (urut abjad, setelah `error_code_appeal`), dan `app.include_router(ocr_image.router)` setelah `app.include_router(collection.router)`.

- [ ] **Step 4: Run tests to verify they pass**

Run perintah Step 2 → Expected: `15 passed`.
Lalu pastikan app masih bisa di-import dan rutenya terdaftar:
```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-api:/src:ro -w /tmp local/qc-api:latest \
  sh -c 'cp -r /src /tmp/w && cd /tmp && PYTHONPATH=/tmp/w/core:/tmp/w python -c "from api.main import app; print(sorted({r.path for r in app.routes if \"ocr\" in r.path}))"'
```
Expected: `['/ocr_images', '/ocr_images/{image_id}', '/ocr_images/{image_id}/image', '/ocr_images/{image_id}/retry']`.

- [ ] **Step 5: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add api/routers/ocr_image.py api/main.py tests/test_ocr_image_router.py
git commit -m "feat(api): endpoint OCR Gambar (upload, riwayat, gambar, retry, hapus)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Task worker `process_ocr_image`

**Files:**
- Create: `telemarketing-qc-worker/worker/tasks/process_ocr_image.py`
- Modify: `telemarketing-qc-worker/worker/celery_app.py:23-28` (`include`)
- Test: `telemarketing-qc-worker/tests/test_process_ocr_image.py`

**Interfaces:**
- Consumes: `db.models.OcrImage` (Task 2); `worker.tasks.process_document._session_factory`, `worker.tasks.process_document._download_object(object_name) -> bytes`; `worker.tasks.process_transcript._llm_client() -> AzureOpenAI`; `compliance.evaluator._extract_usage(response) -> dict`.
- Produces: task `worker.tasks.process_ocr_image.process_ocr_image(image_id: str)`; `transcribe_image(client, model: str, image_bytes: bytes, mime_type: str) -> tuple[str, dict]`; konstanta `OCR_SYSTEM_PROMPT`, `NO_TEXT = "(tidak ada teks)"`.

- [ ] **Step 1: Write the failing test**

`tests/test_process_ocr_image.py`:

```python
"""Task OCR Gambar — tanpa DB/MinIO/LLM sungguhan (sesi, unduhan, dan klien palsu)."""
import uuid
from types import SimpleNamespace

import pytest

from worker.tasks import process_ocr_image as mod


class FakeClient:
    def __init__(self, content="BARIS 1\nBARIS 2", exc=None):
        self.calls, self.content, self.exc = [], content, exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=265, completion_tokens=60, total_tokens=325,
                                  prompt_tokens_details=None, completion_tokens_details=None),
        )


class FakeSession:
    def __init__(self, row):
        self.row, self.commits, self.closed = row, 0, False

    def get(self, model, key):
        return self.row if self.row is not None and self.row.id == key else None

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _row(status="pending"):
    return SimpleNamespace(id=uuid.uuid4(), status=status, object_path="ocr-images/x.png",
                           mime_type="image/png", text=None, error_message=None,
                           token_usage=None, started_at=None, finished_at=None)


@pytest.fixture()
def run(monkeypatch):
    def _run(row, client=None, download=lambda path: b"PNGDATA", image_id=None):
        session = FakeSession(row)
        client = client or FakeClient()
        monkeypatch.setattr(mod, "_session_factory", lambda: (lambda: session))
        monkeypatch.setattr(mod, "_download_object", download)
        monkeypatch.setattr(mod, "_llm_client", lambda: client)
        monkeypatch.setattr(mod, "get_worker_settings", lambda: SimpleNamespace(llm_model="gpt-test"))
        mod.process_ocr_image.run(image_id or str(row.id))
        return session, client
    return _run


def test_sukses_menyimpan_teks_dan_token(run):
    row = _row()
    session, client = run(row)
    assert row.status == "done"
    assert row.text == "BARIS 1\nBARIS 2"
    assert row.token_usage == {"input_token": 265, "output_token": 60,
                               "cached_token": None, "reasoning_token": None}
    assert row.started_at is not None and row.finished_at is not None
    assert session.closed


def test_permintaan_berbentuk_vision_tanpa_reasoning(run):
    _, client = run(_row())
    kw = client.calls[0]
    assert kw["model"] == "gpt-test"
    assert "reasoning_effort" not in kw and "extra_body" not in kw
    assert kw["messages"][0] == {"role": "system", "content": mod.OCR_SYSTEM_PROMPT}
    part = kw["messages"][1]["content"][0]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")


def test_balasan_kosong_jadi_penanda(run):
    row = _row()
    run(row, client=FakeClient(content="   "))
    assert row.status == "done" and row.text == mod.NO_TEXT


def test_llm_gagal_jadi_failed(run):
    row = _row()
    run(row, client=FakeClient(exc=RuntimeError("429 Too Many Requests")))
    assert row.status == "failed"
    assert "429" in row.error_message
    assert row.finished_at is not None


def test_pesan_error_dipotong_1000(run):
    row = _row()
    run(row, client=FakeClient(exc=RuntimeError("x" * 5000)))
    assert len(row.error_message) == 1000


def test_unduhan_gagal_jadi_failed(run):
    row = _row()

    def boom(path):
        raise RuntimeError("NoSuchKey")
    run(row, download=boom)
    assert row.status == "failed" and "NoSuchKey" in row.error_message


def test_row_done_dilewati(run):
    row = _row(status="done")
    row.text = "LAMA"
    _, client = run(row)
    assert client.calls == [] and row.text == "LAMA"


def test_row_failed_dilewati(run):
    """``failed`` hanya kembali ke antrean lewat endpoint retry (yang me-reset ke
    ``pending``); pesan untuk row ``failed`` berarti pesan basi."""
    row = _row(status="failed")
    _, client = run(row)
    assert client.calls == [] and row.status == "failed"


def test_row_hilang_dilewati(run):
    _, client = run(_row(), image_id=str(uuid.uuid4()))
    assert client.calls == []


def test_id_bukan_uuid_dilewati(run):
    _, client = run(_row(), image_id="bukan-uuid")
    assert client.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-worker:/src:ro -w /tmp local/qc-worker:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests/test_process_ocr_image.py'
```
Expected: FAIL — `ImportError: cannot import name 'process_ocr_image'`.

- [ ] **Step 3: Implement**

`worker/tasks/process_ocr_image.py`:

```python
"""Celery task: salin teks dari satu gambar menu OCR Gambar.

Alur per ``ocr_images.id``:
  1. lewati bila baris tidak ada atau sudah ``done``/``failed`` (pesan basi —
     ``failed`` hanya kembali ke antrean lewat endpoint retry yang me-reset ke
     ``pending``)
  2. status -> processing
  3. unduh gambar dari bucket dokumen
  4. model vision (deployment ``LLM_MODEL``) diminta menyalin teks apa adanya
  5. simpan teks + token -> done, atau failed + error_message

Mesin OCR-nya LLM, bukan ``compliance.ocr`` (Mistral Document AI): endpoint OCR
belum dikonfigurasi di server ini, sedangkan deployment LLM sudah dipakai dan
terbukti menerima gambar (spike 1 Oktober 2026). Sengaja TANPA
``reasoning_effort``: menyalin teks tidak butuh penalaran.
"""
import base64
import logging
import uuid
from datetime import datetime, timezone

from compliance.evaluator import _extract_usage
from db.models import OcrImage
from worker.celery_app import celery_app
from worker.config import get_worker_settings
from worker.tasks.process_document import _download_object, _session_factory
from worker.tasks.process_transcript import _llm_client

logger = logging.getLogger(__name__)

NO_TEXT = "(tidak ada teks)"
OCR_SYSTEM_PROMPT = (
    "You are an OCR engine. Transcribe ALL text in the image verbatim, preserving "
    "line breaks and reading order; render tables as markdown tables. Do not "
    "translate, summarize, correct, or add commentary. If the image has no text, "
    f"output exactly: {NO_TEXT}"
)
_SKIP = {"done", "failed"}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def transcribe_image(client, model, image_bytes, mime_type):
    """``(teks, token_usage)`` untuk satu gambar."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
            ]},
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    return (text or NO_TEXT), _extract_usage(response)


@celery_app.task(name="worker.tasks.process_ocr_image.process_ocr_image")
def process_ocr_image(image_id: str):
    try:
        key = uuid.UUID(str(image_id))
    except ValueError:
        logger.warning("ocr image id tidak valid: %r", image_id)
        return
    db = _session_factory()()
    try:
        row = db.get(OcrImage, key)
        if row is None or row.status in _SKIP:
            logger.info("ocr image %s dilewati (status=%s)", image_id, getattr(row, "status", None))
            return
        row.status = "processing"
        row.started_at = _utcnow()
        db.commit()
        try:
            data = _download_object(row.object_path)
            text, usage = transcribe_image(_llm_client(), get_worker_settings().llm_model,
                                           data, row.mime_type)
            row.text, row.token_usage = text, usage
            row.status, row.error_message = "done", None
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR gambar gagal untuk %s", image_id)
            db.rollback()
            row.status = "failed"
            row.error_message = str(exc)[:1000]
        row.finished_at = _utcnow()
        db.commit()
    finally:
        db.close()
```

`worker/celery_app.py` — tambahkan `"worker.tasks.process_ocr_image",` ke list `include` setelah `"worker.tasks.process_document",`.

- [ ] **Step 4: Run test to verify it passes**

Run perintah Step 2 → Expected: `10 passed`.

Lalu suite worker penuh untuk regresi:
```bash
docker run --rm -v /data/scorecard_v2/telemarketing-qc-worker:/src:ro -w /tmp local/qc-worker:latest \
  sh -c 'cp -r /src /tmp/w && pip install -q pytest && PYTHONPATH=/tmp/w/core:/tmp/w python -m pytest -q -p no:cacheprovider /tmp/w/tests'
```
Expected: semua PASS/skipped, tidak ada FAIL.

- [ ] **Step 5: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
git add worker/tasks/process_ocr_image.py worker/celery_app.py tests/test_process_ocr_image.py
git commit -m "feat(worker): task process_ocr_image (OCR Gambar via LLM vision)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Halaman dashboard "OCR Gambar"

**Files:**
- Create: `telemarketing-qc-dashboard/src/utils/ocrImage.js`, `src/utils/ocrImage.test.mjs`
- Create: `telemarketing-qc-dashboard/src/views/upload/OcrImageView.vue`
- Modify: `src/permissions.js` (konstanta `P`, `ROUTE_PERMISSIONS`, `LANDING_ORDER`), `src/router/index.js` (route setelah `/upload/reprocess`), `src/components/SidebarMenu.vue` (link setelah Reprocess All Ticket ~baris 93-95, dan `showUploadGroup` ~baris 139), `package.json` (`test` script)

**Interfaces:**
- Consumes: endpoint Task 3 (bentuk respons di Interfaces Task 3).
- Produces: `validateOcrFiles(files) -> string` (`''` = valid), `txtFilename(filename) -> string`, `hasActive(items) -> boolean`, `STATUS_LABEL`, `OCR_MAX_FILES`, `OCR_MAX_BYTES`; `P.MENU_OCR_IMAGE = 'menu.ocr_image'`; route `/upload/ocr-image`.

- [ ] **Step 1: Write the failing test**

`src/utils/ocrImage.test.mjs`:

```js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { validateOcrFiles, txtFilename, hasActive, OCR_MAX_BYTES } from './ocrImage.js'

const f = (name, size = 100) => ({ name, size })

test('kosong ditolak', () => {
  assert.equal(validateOcrFiles([]), 'Pilih minimal satu gambar')
})

test('lebih dari 10 ditolak', () => {
  const files = Array.from({ length: 11 }, (_, i) => f(`${i}.png`))
  assert.equal(validateOcrFiles(files), 'Maksimal 10 gambar per upload')
})

test('ekstensi selain jpg/jpeg/png ditolak, kapital diterima', () => {
  assert.equal(validateOcrFiles([f('a.gif')]), "File 'a.gif' bukan JPG/PNG — hanya file JPG/PNG yang diterima")
  assert.equal(validateOcrFiles([f('A.JPG'), f('b.jpeg'), f('c.png')]), '')
})

test('lebih dari 10 MB ditolak', () => {
  assert.equal(validateOcrFiles([f('a.png', OCR_MAX_BYTES + 1)]), "File 'a.png' melebihi 10 MB")
  assert.equal(validateOcrFiles([f('a.png', OCR_MAX_BYTES)]), '')
})

test('nama .txt mengikuti nama gambar', () => {
  assert.equal(txtFilename('screenshot chat.PNG'), 'screenshot chat.txt')
  assert.equal(txtFilename('a.b.jpg'), 'a.b.txt')
  assert.equal(txtFilename(''), 'ocr.txt')
})

test('masih ada yang berjalan', () => {
  assert.equal(hasActive([{ status: 'done' }, { status: 'failed' }]), false)
  assert.equal(hasActive([{ status: 'done' }, { status: 'processing' }]), true)
  assert.equal(hasActive([{ status: 'pending' }]), true)
  assert.equal(hasActive(undefined), false)
})
```

Di `package.json`, tambahkan ` src/utils/ocrImage.test.mjs` di akhir script `test`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/scorecard_v2/telemarketing-qc-dashboard && npm test`
Expected: FAIL — `Cannot find module '.../src/utils/ocrImage.js'`.

- [ ] **Step 3: Implement util**

`src/utils/ocrImage.js`:

```js
// Aturan upload menu OCR Gambar. Teks pesannya SAMA dengan yang dikirim API
// (`api/routers/ocr_image.py`) supaya user melihat kalimat yang sama di mana pun
// penolakannya terjadi.
export const OCR_MAX_FILES = 10
export const OCR_MAX_BYTES = 10 * 1024 * 1024
const EXTENSIONS = ['.jpg', '.jpeg', '.png']

export const STATUS_LABEL = {
  pending: 'Menunggu',
  processing: 'Diproses',
  done: 'Selesai',
  failed: 'Gagal',
}

export function validateOcrFiles(files) {
  const list = Array.from(files || [])
  if (!list.length) return 'Pilih minimal satu gambar'
  if (list.length > OCR_MAX_FILES) return `Maksimal ${OCR_MAX_FILES} gambar per upload`
  for (const f of list) {
    const name = (f.name || '').toLowerCase()
    if (!EXTENSIONS.some((e) => name.endsWith(e))) {
      return `File '${f.name}' bukan JPG/PNG — hanya file JPG/PNG yang diterima`
    }
    if (f.size > OCR_MAX_BYTES) return `File '${f.name}' melebihi 10 MB`
  }
  return ''
}

export function txtFilename(filename) {
  const base = (filename || '').replace(/\.[^.]+$/, '')
  return `${base || 'ocr'}.txt`
}

export function hasActive(items) {
  return (items || []).some((i) => i.status === 'pending' || i.status === 'processing')
}
```

Run: `npm test` → Expected: semua PASS (termasuk 6 test baru).

- [ ] **Step 4: Wire permission, route, sidebar**

`src/permissions.js`:
- Di objek `P`, setelah `MENU_COLLECTION_RESULTS: 'menu.collection_results',` tambahkan `MENU_OCR_IMAGE: 'menu.ocr_image',`
- Di `ROUTE_PERMISSIONS`, setelah `'/upload/reprocess': P.MENU_REPROCESS_TICKETS,` tambahkan `'/upload/ocr-image': P.MENU_OCR_IMAGE,`
- Di `LANDING_ORDER`, tambahkan elemen terakhir `['/upload/ocr-image', P.MENU_OCR_IMAGE],` (user yang hanya memegang menu ini tidak terlempar ke `/login`).

`src/router/index.js` — setelah objek route `/upload/reprocess`:

```js
  {
    path: '/upload/ocr-image',
    component: () => import('../views/upload/OcrImageView.vue'),
  },
```

`src/components/SidebarMenu.vue` — setelah `</RouterLink>` milik Reprocess All Ticket (di dalam grup Upload Data):

```html
        <RouterLink v-if="can(P.MENU_OCR_IMAGE)" to="/upload/ocr-image" class="menu-item" active-class="active" :title="collapsed ? 'OCR Gambar' : ''">
          <span class="icon">OG</span> <span class="label">OCR Gambar</span>
        </RouterLink>
```

dan tambahkan `P.MENU_OCR_IMAGE,` ke argumen `auth.canAny(...)` di `showUploadGroup` (setelah `P.MENU_REPROCESS_TICKETS,`).

- [ ] **Step 5: Implement the view**

`src/views/upload/OcrImageView.vue`:

```vue
<template>
  <SidebarLayout title="OCR Gambar">
    <div class="ocr-page">
      <div class="upload-card">
        <h2 class="card-title">OCR Gambar</h2>
        <p class="card-subtitle">Upload gambar <strong>JPG/PNG</strong> (maks {{ OCR_MAX_FILES }} file, 10 MB per file). Teks di dalam gambar disalin apa adanya.</p>

        <div
          class="drop-zone"
          :class="{ dragging: isDragging, 'has-file': files.length }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
          @click="fileInput.click()"
        >
          <input ref="fileInput" type="file" accept=".jpg,.jpeg,.png" multiple class="hidden-input" @change="onSelect" />
          <div v-if="!files.length" class="drop-placeholder">
            <p>Drag & drop gambar di sini</p>
            <p class="drop-hint">atau klik untuk browse (multi-file)</p>
          </div>
          <div v-else class="file-list">
            <div v-for="(f, i) in files" :key="i" class="file-row">
              <span class="file-name">{{ f.name }}</span>
              <span class="file-size">{{ formatSize(f.size) }}</span>
              <button class="remove-btn" @click.stop="files.splice(i, 1); formatError = validateOcrFiles(files)">✕</button>
            </div>
          </div>
        </div>

        <div v-if="formatError" class="error-msg">{{ formatError }}</div>
        <div v-if="uploadError" class="error-msg">{{ uploadError }}</div>

        <button class="btn-upload" :disabled="uploading || !files.length || !!formatError" @click="upload">
          {{ uploading ? 'Mengunggah…' : 'Proses OCR' }}
        </button>
      </div>

      <div class="history-card">
        <h2 class="card-title">Riwayat</h2>
        <div v-if="listError" class="error-msg">{{ listError }}</div>
        <table v-if="items.length" class="history-table">
          <thead>
            <tr>
              <th>File</th><th>Waktu</th><th>Status</th><th v-if="showUploader">Pengunggah</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" :class="{ selected: detail && detail.id === it.id }">
              <td class="file-name">{{ it.filename }}</td>
              <td>{{ formatTime(it.created_at) }}</td>
              <td><span class="badge" :class="it.status">{{ STATUS_LABEL[it.status] || it.status }}</span></td>
              <td v-if="showUploader">{{ it.uploader_name || '-' }}</td>
              <td class="actions">
                <button class="link-btn" @click="openDetail(it.id)">Lihat</button>
                <button v-if="it.status === 'failed'" class="link-btn" @click="retry(it.id)">Proses ulang</button>
                <button class="link-btn danger" @click="remove(it)">Hapus</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="!loading" class="field-hint">Belum ada riwayat.</p>
        <div v-if="total > pageSize" class="pager">
          <button class="link-btn" :disabled="page <= 1" @click="page--; load()">‹ Sebelumnya</button>
          <span>Halaman {{ page }} / {{ Math.ceil(total / pageSize) }}</span>
          <button class="link-btn" :disabled="page * pageSize >= total" @click="page++; load()">Berikutnya ›</button>
        </div>
      </div>

      <div v-if="detail" class="detail-card">
        <div class="detail-head">
          <h2 class="card-title">{{ detail.filename }}</h2>
          <button class="link-btn" @click="closeDetail">Tutup ✕</button>
        </div>
        <div class="detail-body">
          <div class="detail-image">
            <img v-if="imageUrl" :src="imageUrl" :alt="detail.filename" />
          </div>
          <div class="detail-text">
            <div class="text-actions">
              <button class="btn-small" :disabled="detail.status !== 'done'" @click="copyText">{{ copied ? 'Tersalin ✓' : 'Salin' }}</button>
              <button class="btn-small" :disabled="detail.status !== 'done'" @click="downloadText">Unduh .txt</button>
            </div>
            <pre v-if="detail.status === 'done'" class="ocr-text">{{ detail.text }}</pre>
            <p v-else-if="detail.status === 'failed'" class="error-msg">Gagal: {{ detail.error_message }}</p>
            <p v-else class="field-hint">{{ STATUS_LABEL[detail.status] }}…</p>
          </div>
        </div>
      </div>
    </div>
  </SidebarLayout>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import SidebarLayout from '../../components/SidebarLayout.vue'
import apiClient from '../../api/client.js'
import { OCR_MAX_FILES, STATUS_LABEL, hasActive, txtFilename, validateOcrFiles } from '../../utils/ocrImage.js'

const POLL_MS = 3000

const fileInput = ref(null)
const files = ref([])
const isDragging = ref(false)
const formatError = ref('')
const uploadError = ref('')
const uploading = ref(false)

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const listError = ref('')

const detail = ref(null)
const imageUrl = ref('')
const copied = ref(false)
let pollTimer = null

const showUploader = computed(() => items.value.some((i) => 'uploader_name' in i))

function addFiles(list) {
  files.value = [...files.value, ...Array.from(list || [])]
  formatError.value = validateOcrFiles(files.value)
}
function onSelect(e) { addFiles(e.target.files); e.target.value = '' }
function onDrop(e) { isDragging.value = false; addFiles(e.dataTransfer.files) }

function formatSize(n) {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`
}
function formatTime(s) {
  return s ? new Date(s).toLocaleString('id-ID') : '-'
}
function errorText(err, fallback) {
  const d = err?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

async function upload() {
  formatError.value = validateOcrFiles(files.value)
  if (formatError.value) return
  uploading.value = true
  uploadError.value = ''
  try {
    const form = new FormData()
    files.value.forEach((f) => form.append('files', f))
    await apiClient.post('/ocr_images', form, { timeout: 120000 })
    files.value = []
    page.value = 1
    await load()
  } catch (err) {
    uploadError.value = errorText(err, 'Upload gagal, coba lagi')
  } finally {
    uploading.value = false
  }
}

async function load() {
  loading.value = true
  listError.value = ''
  try {
    const { data } = await apiClient.get('/ocr_images', { params: { page: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
    if (detail.value) {
      const fresh = data.items.find((i) => i.id === detail.value.id)
      if (fresh && fresh.status !== detail.value.status) await openDetail(fresh.id)
    }
  } catch (err) {
    listError.value = errorText(err, 'Gagal memuat riwayat')
  } finally {
    loading.value = false
    schedulePoll()
  }
}

function schedulePoll() {
  clearTimeout(pollTimer)
  pollTimer = hasActive(items.value) ? setTimeout(load, POLL_MS) : null
}

async function openDetail(id) {
  const { data } = await apiClient.get(`/ocr_images/${id}`)
  const sameImage = detail.value && detail.value.id === id
  detail.value = data
  copied.value = false
  if (!sameImage) {
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = ''
    const res = await apiClient.get(`/ocr_images/${id}/image`, { responseType: 'blob' })
    imageUrl.value = URL.createObjectURL(res.data)
  }
}

function closeDetail() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
  detail.value = null
}

async function retry(id) {
  try {
    await apiClient.post(`/ocr_images/${id}/retry`)
    await load()
  } catch (err) {
    listError.value = errorText(err, 'Gagal memproses ulang')
  }
}

async function remove(it) {
  if (!window.confirm(`Hapus "${it.filename}" beserta teks hasil OCR-nya?`)) return
  try {
    await apiClient.delete(`/ocr_images/${it.id}`)
    if (detail.value && detail.value.id === it.id) closeDetail()
    await load()
  } catch (err) {
    listError.value = errorText(err, 'Gagal menghapus')
  }
}

async function copyText() {
  await navigator.clipboard.writeText(detail.value.text || '')
  copied.value = true
}

function downloadText() {
  const blob = new Blob([detail.value.text || ''], { type: 'text/plain;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = txtFilename(detail.value.filename)
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(load)
onBeforeUnmount(() => {
  clearTimeout(pollTimer)
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})
</script>

<style scoped>
.ocr-page { display: flex; flex-direction: column; gap: 20px; max-width: 1100px; margin: 0 auto; }
.upload-card, .history-card, .detail-card {
  background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 24px;
  display: flex; flex-direction: column; gap: 16px;
}
.card-title { font-size: 17px; font-weight: 700; }
.card-subtitle { font-size: 13px; color: var(--text-muted); margin-top: -10px; }
.drop-zone { border: 2px dashed var(--border); border-radius: 10px; padding: 28px; cursor: pointer; display: flex; justify-content: center; }
.drop-zone:hover, .drop-zone.dragging { border-color: var(--blue); background: var(--blue-bg); }
.drop-zone.has-file { border-color: var(--green); background: var(--green-bg); }
.hidden-input { display: none; }
.drop-placeholder { display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center; }
.drop-placeholder p { font-size: 14px; font-weight: 500; color: var(--text); }
.drop-hint { font-size: 12px; color: var(--text-muted) !important; }
.file-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.file-row { display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; }
.file-name { flex: 1; font-weight: 600; font-size: 13px; word-break: break-all; }
.file-size { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.remove-btn { border: none; background: #fee2e2; color: var(--red); border-radius: 6px; width: 26px; height: 26px; cursor: pointer; }
.remove-btn:hover { background: #fecaca; }
.btn-upload { align-self: flex-start; background: var(--blue); color: #fff; border: none; border-radius: 8px; padding: 10px 20px; font-weight: 600; cursor: pointer; }
.btn-upload:hover:not(:disabled) { background: #2563eb; }
.btn-upload:disabled { opacity: 0.5; cursor: not-allowed; }
.error-msg { color: var(--red); font-size: 13px; }
.field-hint { font-size: 12px; color: var(--text-muted); }
.history-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.history-table th, .history-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
.history-table tr.selected { background: var(--blue-bg); }
.actions { white-space: nowrap; display: flex; gap: 10px; }
.link-btn { background: none; border: none; color: var(--blue); font-weight: 600; cursor: pointer; padding: 0; }
.link-btn.danger { color: var(--red); }
.link-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; background: #f1f5f9; }
.badge.done { background: var(--green-bg); color: var(--green); }
.badge.failed { background: #fee2e2; color: var(--red); }
.badge.processing, .badge.pending { background: var(--blue-bg); color: var(--blue); }
.pager { display: flex; gap: 12px; align-items: center; font-size: 13px; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 800px) { .detail-body { grid-template-columns: 1fr; } }
.detail-image img { max-width: 100%; border: 1px solid var(--border); border-radius: 8px; }
.text-actions { display: flex; gap: 8px; margin-bottom: 8px; }
.btn-small { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-small:disabled { opacity: 0.4; cursor: not-allowed; }
.ocr-text { white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, monospace; font-size: 13px; background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px; max-height: 70vh; overflow: auto; }
</style>
```

- [ ] **Step 6: Build**

Run: `cd /data/scorecard_v2/telemarketing-qc-dashboard && npm test && npm run build`
Expected: test PASS; build sukses tanpa error, ada chunk `OcrImageView-*.js` di `dist/assets`.

- [ ] **Step 7: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-dashboard
git add src/utils/ocrImage.js src/utils/ocrImage.test.mjs src/views/upload/OcrImageView.vue \
  src/permissions.js src/router/index.js src/components/SidebarMenu.vue package.json
git commit -m "feat(dashboard): halaman OCR Gambar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: E2E OCR Gambar

**Files:**
- Modify: `telemarketing-qc-api/e2e/stub_llm/app.py` (cabang OCR di `chat()`)
- Modify: `telemarketing-qc-api/e2e/.env.e2e` (tambah `OCR_IMAGE_CAMPAIGNS=E2E-Complaint`)
- Create: `telemarketing-qc-api/e2e/tests/test_09_ocr_gambar.py`

**Interfaces:**
- Consumes: semua endpoint Task 3, task Task 4, fixture e2e `api`, `auth`, `q`, `db`, `STUB`.
- Produces: stub mengembalikan teks tetap `STUB_OCR_TEKS = "TEKS OCR STUB\n| a | b |"` untuk system prompt yang memuat `"You are an OCR engine"`, dan mencatat `jenis: "ocr"` di `/_jejak`.

- [ ] **Step 1: Add the stub branch**

Di `e2e/stub_llm/app.py`, tambahkan konstanta di bawah `PANGGILAN = []`:

```python
# Balasan tetap untuk menu OCR Gambar (``worker.tasks.process_ocr_image``) — dikenali
# dari system prompt "You are an OCR engine".
STUB_OCR_TEKS = "TEKS OCR STUB\n| a | b |"
```

Di `chat()`, ganti blok `if riplay: ... else: ...` dan nilai `"jenis"` menjadi:

```python
    ocr = "You are an OCR engine" in system
    if ocr:
        isi = STUB_OCR_TEKS
    elif riplay:
        isi = json.dumps(_riplay(), ensure_ascii=False)
    elif klasifikasi:
        berkas = re.findall(r"^\s*-\s*([^\s|]+\.pdf)", user, re.M) or re.findall(r"([\w.-]+\.pdf)", user)
        isi = json.dumps(_klasifikasi(list(dict.fromkeys(berkas))), ensure_ascii=False)
    else:
        isi = json.dumps(_evaluasi(), ensure_ascii=False)
```

dan di `PANGGILAN.append({...})`:

```python
        "jenis": "ocr" if ocr else ("riplay" if riplay else ("klasifikasi" if klasifikasi else "penilaian")),
```

Tambahkan `OCR_IMAGE_CAMPAIGNS=E2E-Complaint` ke `e2e/.env.e2e` (di bawah baris `COLLECTION_CAMPAIGNS` bila ada, kalau tidak di akhir file).

- [ ] **Step 2: Write the e2e test**

`e2e/tests/test_09_ocr_gambar.py`:

```python
"""Menu OCR Gambar ujung ke ujung: upload -> worker -> stub LLM -> teks tersimpan.

User non-admin dibuat langsung di DB uji dengan campaign ``E2E-Complaint`` (yang
tercantum di ``OCR_IMAGE_CAMPAIGNS`` .env.e2e) dan satu user lain tanpa campaign
itu. Admin memakai fixture ``auth``.
"""
import io
import time
import uuid

import allure
import pytest
import requests
from passlib.context import CryptContext

from conftest import API, STUB

STUB_OCR_TEKS = "TEKS OCR STUB\n| a | b |"


def _png():
    # PNG 1x1 yang valid (diverifikasi Pillow 1 Oktober 2026) — image test tidak memuat Pillow.
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC")


def _buat_user(db, username, campaign):
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    with db.cursor() as c:
        c.execute('SET search_path TO "dashboard", public')
        c.execute("select id from users where username = %s", (username,))
        row = c.fetchone()
        if not row:
            c.execute(
                "insert into users (username, name, email, hashed_password, role, is_active)"
                " values (%s, %s, %s, %s, 'qc', true) returning id",
                (username, username, f"{username}@e2e.local", pwd.hash("e2e-pass")),
            )
            row = c.fetchone()
        c.execute("delete from user_campaigns where user_id = %s", (row[0],))
        c.execute("insert into user_campaigns (user_id, campaign) values (%s, %s)", (row[0], campaign))
    r = requests.post(f"{API}/auth/login", data={"username": username, "password": "e2e-pass"}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def complaint(db):
    return _buat_user(db, "e2e-complaint", "E2E-Complaint")


@pytest.fixture(scope="module")
def cashline(db):
    return _buat_user(db, "e2e-cashline", "Cashline")


def _tunggu_selesai(auth, ids, batas=60):
    akhir = time.time() + batas
    while time.time() < akhir:
        rows = [requests.get(f"{API}/ocr_images/{i}", headers=auth, timeout=30).json() for i in ids]
        if all(r["status"] in ("done", "failed") for r in rows):
            return rows
        time.sleep(1)
    pytest.fail(f"OCR tidak selesai dalam {batas} detik: {[r['status'] for r in rows]}")


@allure.title("User Complaint Handling melihat menu OCR Gambar; user Cashline tidak")
def test_menu_mengikuti_campaign(complaint, cashline):
    me_c = requests.get(f"{API}/auth/me", headers=complaint, timeout=30).json()
    me_x = requests.get(f"{API}/auth/me", headers=cashline, timeout=30).json()
    assert "menu.ocr_image" in me_c["permissions"]
    assert "menu.ocr_image" not in me_x["permissions"]
    r = requests.post(f"{API}/ocr_images", headers=cashline,
                      files=[("files", ("a.png", io.BytesIO(_png()), "image/png"))], timeout=30)
    assert r.status_code == 403


@allure.title("Upload dua gambar -> keduanya done dengan teks dari model")
def test_upload_dua_gambar_selesai(complaint):
    requests.post(f"{STUB}/_reset", timeout=10)
    files = [("files", (f"{n}.png", io.BytesIO(_png()), "image/png")) for n in ("satu", "dua")]
    r = requests.post(f"{API}/ocr_images", headers=complaint, files=files, timeout=60)
    assert r.status_code == 200, r.text
    ids = [i["id"] for i in r.json()["items"]]
    rows = _tunggu_selesai(complaint, ids)
    assert [x["status"] for x in rows] == ["done", "done"]
    assert all(x["text"] == STUB_OCR_TEKS for x in rows)
    jejak = requests.get(f"{STUB}/_jejak", timeout=10).json()["panggilan"]
    ocr = [p for p in jejak if p["jenis"] == "ocr"]
    assert len(ocr) == 2 and all(p["jumlah_gambar"] == 1 for p in ocr)


@allure.title("Gambar asli bisa diunduh kembali")
def test_gambar_asli_kembali(complaint):
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("x.png", io.BytesIO(_png()), "image/png"))], timeout=60)
    image_id = r.json()["items"][0]["id"]
    g = requests.get(f"{API}/ocr_images/{image_id}/image", headers=complaint, timeout=30)
    assert g.status_code == 200 and g.content == _png()
    assert g.headers["content-type"] == "image/png"


@allure.title("Riwayat terisolasi: user lain 404, Admin melihat dengan nama pengunggah")
def test_riwayat_terisolasi(complaint, db, auth):
    lain = _buat_user(db, "e2e-complaint-2", "E2E-Complaint")
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("p.png", io.BytesIO(_png()), "image/png"))], timeout=60)
    image_id = r.json()["items"][0]["id"]
    assert requests.get(f"{API}/ocr_images/{image_id}", headers=lain, timeout=30).status_code == 404
    ids_lain = {i["id"] for i in requests.get(f"{API}/ocr_images", headers=lain, timeout=30).json()["items"]}
    assert image_id not in ids_lain
    admin = requests.get(f"{API}/ocr_images", headers=auth, params={"page_size": 100}, timeout=30).json()
    mine = [i for i in admin["items"] if i["id"] == image_id]
    assert mine and mine[0]["uploader_name"] == "e2e-complaint"


@allure.title("File bukan gambar ditolak 422 dan tidak ada yang tersimpan")
def test_campuran_ditolak(complaint, q):
    sebelum = q("select count(*) from ocr_images")[0][0]
    files = [("files", ("ok.png", io.BytesIO(_png()), "image/png")),
             ("files", ("palsu.png", io.BytesIO(b"%PDF-1.4"), "image/png"))]
    r = requests.post(f"{API}/ocr_images", headers=complaint, files=files, timeout=60)
    assert r.status_code == 422 and "palsu.png" in r.json()["detail"]
    assert q("select count(*) from ocr_images")[0][0] == sebelum


@allure.title("Hapus menghilangkan baris dan gambar")
def test_hapus(complaint):
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("h.png", io.BytesIO(_png()), "image/png"))], timeout=60)
    image_id = r.json()["items"][0]["id"]
    _tunggu_selesai(complaint, [image_id])
    assert requests.delete(f"{API}/ocr_images/{image_id}", headers=complaint, timeout=30).status_code == 200
    assert requests.get(f"{API}/ocr_images/{image_id}", headers=complaint, timeout=30).status_code == 404
```

- [ ] **Step 3: Run the full e2e suite**

```bash
cd /data/scorecard_v2/telemarketing-qc-dashboard && npm run build
cd /data/scorecard_v2/telemarketing-qc-api/e2e && ./jalankan.sh
```
Expected: test `test_09_ocr_gambar.py` 6 passed, dan test 01–08 tetap PASS. Bila ada test lama yang gagal, ulangi run dengan keempat repo di `main` (`git -C <repo> checkout main`, `./jalankan.sh`, lalu kembali ke `feat/ocr-gambar`): gagal juga di `main` = bukan regresi fitur ini — catat dan laporkan; lulus di `main` = regresi, perbaiki sebelum lanjut.

- [ ] **Step 4: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add e2e/stub_llm/app.py e2e/.env.e2e e2e/tests/test_09_ocr_gambar.py
git commit -m "test(e2e): OCR Gambar ujung ke ujung

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Biarkan stack e2e menyala selama review; matikan dengan `./jalankan.sh bersih` setelah selesai.

---

### Task 7: Spec sinkron + catatan deploy

**Files:**
- Modify: `telemarketing-qc-api/docs/superpowers/specs/2026-10-01-ocr-gambar-design.md`
- Modify: `telemarketing-qc-api/docs/DEPLOYMENT.md` (bagian env) dan `telemarketing-qc-api/docs/API_REFERENCE.md` (endpoint baru)

- [ ] **Step 1: Align spec with decisions made in the plan**

Di spec:
- §4 tabel: ganti tipe `timestamptz` menjadi `DateTime (naive, UTC — sama dengan tabel lain)`.
- §3: tambahkan baris "`menu.ocr_image` masuk `ADMIN_ONLY_PERMISSIONS`, sehingga tidak bisa diberikan ke role lain lewat Manage Role."
- §6 langkah 1: ganti "status `done`" menjadi "status `done` atau `failed` (failed hanya kembali lewat endpoint retry yang me-reset ke `pending`)".

- [ ] **Step 2: Document env + endpoints**

`docs/DEPLOYMENT.md`, di bagian daftar env api, tambahkan:

```markdown
- `OCR_IMAGE_CAMPAIGNS` — campaign (dipisah koma, case-insensitive) yang membuka menu
  OCR Gambar untuk non-admin. Prod: `Complaint Handling`. Kosong = hanya Admin/Demo.
```

`docs/API_REFERENCE.md`, tambahkan bagian "OCR Gambar" berisi enam endpoint dan bentuk respons persis seperti blok **Interfaces** Task 3.

- [ ] **Step 3: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add docs/superpowers/specs/2026-10-01-ocr-gambar-design.md docs/DEPLOYMENT.md docs/API_REFERENCE.md
git commit -m "docs: OCR Gambar — spec disinkronkan, env & endpoint

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Prepare (do NOT execute) the deploy checklist for the user**

Tulis ringkasan ini ke user dan tunggu konfirmasi sebelum menyentuh prod:

1. Merge `feat/ocr-gambar` → `main` di keempat repo (push dilakukan user, lihat memori git push).
2. api `.env`: tambah `OCR_IMAGE_CAMPAIGNS=Complaint Handling` (backup `.env` dulu).
3. Build candidate api/worker/dashboard sesuai prosedur (constraints.txt), diff freeze, tag image lama untuk rollback.
4. Recreate api (CMD-nya menjalankan `alembic upgrade head` → 0064), lalu worker/beat, lalu dashboard.
5. Smoke: `select version_num from dashboard.alembic_version` = `0064`; login Admin → menu OCR Gambar tampil; upload satu screenshot uji tanpa data nasabah → `done`.
6. Kube worker (10.158.3.13) tidak perlu diubah: Redis-nya terpisah, task ini tidak sampai ke sana; tabel baru tidak mengganggu kode lamanya.
7. Rollback: kosongkan `OCR_IMAGE_CAMPAIGNS` + kembalikan image bertag; tabel `ocr_images` boleh tetap ada.
