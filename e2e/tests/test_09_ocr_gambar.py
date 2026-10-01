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
    # PNG 1x1 yang valid (diverifikasi Pillow 1 Oktober 2026).
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


def _encode(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


@allure.title("TIFF 3 halaman dipecah menjadi 3 entri dan semuanya di-OCR")
def test_tiff_multi_halaman(complaint):
    from PIL import Image
    pages = [Image.new("L", (40, 20), v) for v in (0, 128, 255)]
    raw = _encode(pages[0], "TIFF", save_all=True, append_images=pages[1:])
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("fax.tiff", io.BytesIO(raw), "image/tiff"))], timeout=60)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["filename"] for i in items] == ["fax.tiff (hal. 1/3)", "fax.tiff (hal. 2/3)", "fax.tiff (hal. 3/3)"]
    rows = _tunggu_selesai(complaint, [i["id"] for i in items])
    assert all(x["status"] == "done" and x["mime_type"] == "image/jpeg" for x in rows)


@allure.title("HEIC (foto iPhone) diterima, disimpan JPEG, dan di-OCR")
def test_heic(complaint):
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()
    raw = _encode(Image.new("RGB", (40, 20), "white"), "HEIF")
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("IMG_0001.HEIC", io.BytesIO(raw), "image/heic"))], timeout=60)
    assert r.status_code == 200, r.text
    image_id = r.json()["items"][0]["id"]
    [row] = _tunggu_selesai(complaint, [image_id])
    assert row["status"] == "done" and row["mime_type"] == "image/jpeg"
    g = requests.get(f"{API}/ocr_images/{image_id}/image", headers=complaint, timeout=30)
    assert g.headers["content-type"] == "image/jpeg" and g.content[:2] == b"\xff\xd8"


@allure.title("Hapus menghilangkan baris dan gambar")
def test_hapus(complaint):
    r = requests.post(f"{API}/ocr_images", headers=complaint,
                      files=[("files", ("h.png", io.BytesIO(_png()), "image/png"))], timeout=60)
    image_id = r.json()["items"][0]["id"]
    _tunggu_selesai(complaint, [image_id])
    assert requests.delete(f"{API}/ocr_images/{image_id}", headers=complaint, timeout=30).status_code == 200
    assert requests.get(f"{API}/ocr_images/{image_id}", headers=complaint, timeout=30).status_code == 404
