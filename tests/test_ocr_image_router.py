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


def test_file_teks_ditolak(env):
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[_upload("catatan.txt", b"halo")], db=None, current_user=QC)
    assert _status(e) == 422 and e.value.detail == "File 'catatan.txt' bukan gambar yang bisa dibaca"


def test_png_palsu_ditolak(env):
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=[_upload("a.png", b"%PDF-1.4 bukan gambar")], db=None, current_user=QC)
    assert _status(e) == 422 and "bukan gambar yang bisa dibaca" in e.value.detail


def _encode(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def test_gif_dan_bmp_diterima_disimpan_jpeg(env):
    files = [_upload("a.gif", _encode(Image.new("P", (4, 4)), "GIF")),
             _upload("b.bmp", _encode(Image.new("RGB", (4, 4)), "BMP"))]
    out = mod.upload_ocr_images(files=files, db=None, current_user=QC)
    assert [i["filename"] for i in out["items"]] == ["a.gif", "b.bmp"]
    assert {ct for _, _, ct in env.put} == {"image/jpeg"}
    assert all(name.endswith(".jpg") for _, name, _ in env.put)


def _tiff(pages):
    imgs = [Image.new("L", (4, 4)) for _ in range(pages)]
    return _encode(imgs[0], "TIFF", save_all=True, append_images=imgs[1:])


def test_tiff_multi_halaman_dipecah(env):
    out = mod.upload_ocr_images(files=[_upload("fax.tif", _tiff(3))], db=None, current_user=QC)
    assert [i["filename"] for i in out["items"]] == [
        "fax.tif (hal. 1/3)", "fax.tif (hal. 2/3)", "fax.tif (hal. 3/3)"]
    assert len(env.sent) == 3
    assert len({i["batch_id"] for i in out["items"]}) == 1


def test_total_halaman_melebihi_batas(env):
    files = [_upload("a.png", _png()), _upload("fax.tif", _tiff(10))]
    with pytest.raises(HTTPException) as e:
        mod.upload_ocr_images(files=files, db=None, current_user=QC)
    assert _status(e) == 422
    assert e.value.detail == "Maksimal 10 gambar per upload (termasuk tiap halaman TIFF; total 11)"
    assert env.put == [] and env.store.rows == {}


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
