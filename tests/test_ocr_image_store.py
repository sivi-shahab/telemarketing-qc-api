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
