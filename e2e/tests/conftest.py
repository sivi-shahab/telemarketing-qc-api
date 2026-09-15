"""Fixture bersama untuk e2e telemarketing QC.

Seluruh test berjalan terhadap stack TERISOLASI (`docker-compose.e2e.yml`) — bukan
produksi. Tidak ada satu pun nilai di `.env.e2e` yang menunjuk 10.155.32.28.
"""
import io
import os
import time

import psycopg2
import pytest
import requests

API = os.getenv("E2E_API", "http://e2e-api:4000")
STUB = os.getenv("E2E_STUB", "http://e2e-stub-llm:9099")
PDF_DIR = os.getenv("E2E_PDF_DIR", "/transkrip")
DB = dict(host="e2e-pg", port=5432, dbname="qce2e", user="qce2e", password="qce2e-pass")


@pytest.fixture(scope="session")
def api():
    return API


@pytest.fixture(scope="session")
def db():
    """Koneksi baca-saja ke Postgres e2e; search_path disamakan dengan aplikasi."""
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute('SET search_path TO "dashboard", public')
    yield conn
    conn.close()


def _q(conn, sql, *args):
    with conn.cursor() as c:
        c.execute('SET search_path TO "dashboard", public')
        c.execute(sql, args or None)
        return c.fetchall()


@pytest.fixture(scope="session")
def q(db):
    return lambda sql, *a: _q(db, sql, *a)


@pytest.fixture(scope="session")
def user_admin(db):
    """Sediakan user ber-role `admin` untuk e2e.

    Migrasi 0001 sengaja menyemai user bawaan dengan role **spq_head**, bukan `admin` —
    dan `spq_head` TIDAK punya `admin.campaign.write` maupun izin Manage User (lihat
    `api/permissions.py`). Jadi di instalasi baru tidak ada satu pun akun yang bisa
    membuat campaign lewat API; akun `admin` memang harus dibuat sengaja.

    E2E tidak boleh memakai jalan pintas yang mengubah kode yang diuji, jadi usernya
    disisipkan langsung ke database uji dengan hash yang dibuat memakai passlib versi
    yang sama dengan aplikasi.
    """
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    with db.cursor() as c:
        c.execute('SET search_path TO "dashboard", public')
        c.execute("select id from users where username = %s", ("e2e-admin",))
        if not c.fetchone():
            c.execute(
                "insert into users (username, email, hashed_password, role, is_active)"
                " values (%s, %s, %s, 'admin', true)",
                ("e2e-admin", "e2e-admin@e2e.local", pwd.hash("e2e-admin-pass")),
            )
    return ("e2e-admin", "e2e-admin-pass")


@pytest.fixture(scope="session")
def token(api, user_admin):
    u, p = user_admin
    r = requests.post(f"{api}/auth/login", data={"username": u, "password": p}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def campaign(api, auth):
    """Campaign minimal: prompt, KB, scorecard. Dipakai seluruh upload."""
    nama = "E2E-Cashline"
    ada = requests.get(f"{api}/list_campaigns", headers=auth, timeout=30).json()
    daftar = ada.get("items") if isinstance(ada, dict) else ada
    if any((c.get("campaign") or c.get("name")) == nama for c in (daftar or [])):
        return nama
    berkas = {
        "prompt": ("prompt.txt", io.BytesIO(b"Anda penilai QC telemarketing Bank Mega."), "text/plain"),
        "knowledge_base": ("kb.txt", io.BytesIO(b"KB: aturan penilaian Bank Mega."), "text/plain"),
        "scorecard": ("scorecard.txt", io.BytesIO(
            b"SC_CL_1 Greeting bobot 5\nSC_CL_2 Nama agent bobot 5\n"
            b"SC_CL_24 Verifikasi dinamis bobot 10\n"), "text/plain"),
    }
    r = requests.post(f"{api}/upload_detail_campaign", headers=auth,
                      data={"campaign": nama}, files=berkas, timeout=120)
    assert r.status_code < 300, f"gagal membuat campaign: {r.status_code} {r.text[:300]}"
    return nama


@pytest.fixture(scope="session")
def tiket(api, auth, campaign):
    """Unggah SATU tiket (4 PDF nyata) lalu tunggu worker menyelesaikannya.

    Mengembalikan ``(result_id, ticket_id)``. Sengaja session-scope: pipeline ini
    yang mahal, dan seluruh test hasil membaca tiket yang sama.
    """
    requests.post(f"{STUB}/_reset", timeout=30)
    pdfs = sorted(f for f in os.listdir(PDF_DIR) if f.endswith(".pdf"))
    assert pdfs, f"tidak ada PDF di {PDF_DIR}"
    files = [("files", (f, open(os.path.join(PDF_DIR, f), "rb"), "application/pdf")) for f in pdfs]
    r = requests.post(f"{api}/upload_transcript", headers=auth,
                      data={"campaign": campaign}, files=files, timeout=180)
    assert r.status_code < 300, f"upload gagal: {r.status_code} {r.text[:400]}"
    rid = r.json()["result_id"]

    batas = time.time() + 240
    status, terakhir = None, {}
    while time.time() < batas:
        res = requests.get(f"{api}/result/{rid}", headers=auth, timeout=30)
        terakhir = res.json()
        status = terakhir.get("status")
        if status in ("done", "failed"):
            break
        time.sleep(3)
    assert status == "done", f"tiket tidak selesai (status={status}): {str(terakhir)[:400]}"
    return rid, pdfs[0].split("_", 1)[0]
