"""RIPLAY: dari PDF yang diunggah sampai blok TnC Product di prompt penilaian.

Celah yang ditutup berkas ini: sampai 18 September 2026 tidak satu pun test e2e
menyentuh jalur RIPLAY — fixture ``campaign`` mengunggah campaign TANPA PDF RIPLAY,
sehingga ``get_llm_client()`` sisi API tidak pernah terpanggil. Dua bug produksi
berturut-turut lolos dari suite ini:

1. Setting ``riplay_*`` tidak dideklarasikan -> ``AttributeError`` tertangkap
   ``except Exception`` -> 502 "Ekstraksi RIPLAY gagal dihubungi".
2. ``get_llm_client()`` memakai ``OpenAI`` biasa terhadap endpoint Azure -> permintaan
   jatuh ke ``<base_url>/chat/completions`` -> **404 "Resource not found"**, yang juga
   muncul sebagai 502 "gagal dihubungi".

Keduanya menyamar jadi gangguan penyedia LLM, padahal murni kesalahan sendiri.
``test_path_azure_bukan_path_openai`` adalah penjaga khusus untuk nomor 2.
"""
import io
import json

import allure
import pytest
import requests

from conftest import PDF_DIR, STUB


def _pdf_satu_halaman(teks: str = "RIPLAY Mega Cash Line") -> bytes:
    """PDF satu halaman berisi teks, disusun dari byte mentah.

    Sengaja tanpa reportlab/pypdf: image test tidak memuatnya, dan menambah dependensi
    hanya untuk sebuah PDF tiruan membuat harness ini lebih rapuh ketimbang berguna.
    Offset xref dihitung, tidak ditulis tangan, supaya berkasnya sah dibaca pypdfium2
    (renderer yang dipakai ``pdf_to_llm_images``).
    """
    aliran = f"BT /F1 24 Tf 72 700 Td ({teks}) Tj ET".encode()
    objek = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(aliran)).encode() + b" >>\nstream\n" + aliran + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, isi in enumerate(objek, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + isi + b"\nendobj\n"
    awal_xref = len(out)
    out += f"xref\n0 {len(objek) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objek) + 1} /Root 1 0 R >>\nstartxref\n{awal_xref}\n".encode()
        + b"%%EOF\n"
    )
    return bytes(out)


@pytest.fixture(scope="module")
def campaign_riplay(api, auth, q):
    """Campaign terpisah yang diunggah BESERTA PDF RIPLAY.

    Dipisah dari fixture ``campaign`` supaya test lain tetap menguji keadaan tanpa
    RIPLAY — keduanya sah dan keduanya harus jalan.
    """
    nama = "E2E-Cashline-RIPLAY"
    requests.post(f"{STUB}/_reset", timeout=30)
    berkas = {
        "prompt": ("prompt.txt", io.BytesIO(b"Anda penilai QC telemarketing Bank Mega."), "text/plain"),
        "knowledge_base": ("kb.txt", io.BytesIO(b"KB: aturan penilaian Bank Mega."), "text/plain"),
        "scorecard": ("scorecard.txt", io.BytesIO(b"SC_CL_1 Greeting bobot 5\n"), "text/plain"),
        "riplay": ("riplay.pdf", io.BytesIO(_pdf_satu_halaman()), "application/pdf"),
    }
    r = requests.post(f"{api}/upload_detail_campaign", headers=auth,
                      data={"campaign": nama}, files=berkas, timeout=180)
    assert r.status_code < 300, f"upload RIPLAY gagal: {r.status_code} {r.text[:400]}"
    return nama, r.json()


@allure.feature("RIPLAY & TnC Product")
class TestRiplay:

    def test_upload_diterima(self, campaign_riplay):
        """Upload dengan RIPLAY harus 2xx — bukan 502 'gagal dihubungi'."""
        _nama, body = campaign_riplay
        assert body.get("riplay_filename") == "riplay.pdf"

    def test_gate_nama_produk_lolos(self, campaign_riplay):
        """Nama produk pada RIPLAY dicocokkan dengan nama campaign."""
        _nama, body = campaign_riplay
        assert body.get("riplay_product_name") == "Mega Cash Line"
        assert (body.get("riplay_similarity") or 0) >= 50.0

    def test_pdf_benar_benar_dirender(self, campaign_riplay):
        """Halaman PDF harus sampai ke model sebagai GAMBAR, bukan teks saja.

        Kalau perenderan diam-diam menghasilkan nol gambar, ekstraksi tetap 'berhasil'
        (stub menjawab apa pun) padahal model sungguhan tidak menerima apa-apa.
        """
        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        riplay = [p for p in jejak if p["jenis"] == "riplay"]
        assert riplay, "tidak ada panggilan RIPLAY ke stub"
        assert riplay[0]["jumlah_gambar"] >= 1, "PDF tidak terkirim sebagai gambar"

    def test_path_azure_bukan_path_openai(self, campaign_riplay):
        """Penjaga regresi 404: URL harus path deployment Azure.

        Klien ``OpenAI`` biasa menembak ``chat/completions``; Azure hanya melayani
        ``openai/deployments/{deployment}/chat/completions``. Stub memakai handler
        catch-all sehingga KEDUANYA dijawab 200 di sini — justru itu gunanya memeriksa
        path yang tercatat, sebab di produksi bentuk salah berarti 404.
        """
        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        riplay = [p for p in jejak if p["jenis"] == "riplay"]
        assert riplay, "tidak ada panggilan RIPLAY ke stub"
        path = riplay[0]["path"]
        assert path.startswith("openai/deployments/"), (
            f"path {path!r} bukan bentuk Azure — klien OpenAI biasa akan 404 di produksi"
        )
        assert path.endswith("chat/completions"), f"path tidak lengkap: {path!r}"

    def test_ekstraksi_tersimpan(self, campaign_riplay, q):
        """``riplay_extraction`` harus mendarat di kolom DB, bukan hanya di respons."""
        nama, _body = campaign_riplay
        baris = q("SELECT riplay_extraction FROM dashboard.campaigns WHERE name = %s", nama)
        assert baris, f"campaign {nama} tidak ada di DB"
        ekstraksi = baris[0][0]
        assert ekstraksi, "riplay_extraction masih NULL setelah upload dengan RIPLAY"
        if isinstance(ekstraksi, str):
            ekstraksi = json.loads(ekstraksi)
        assert ekstraksi.get("nama_produk") == "Mega Cash Line"

    def test_tnc_sampai_ke_prompt_penilaian(self, api, auth, campaign_riplay):
        """Pembuktian ujung-ke-ujung: nilai RIPLAY muncul di blok TNC PRODUCT.

        Inilah yang membedakan test ini dari unit test — ia membuktikan rantai penuh
        campaigns.riplay_extraction -> build_tnc_product_reference -> blok referensi ->
        permintaan HTTP yang benar-benar diterima model. Tanpa RIPLAY, blok itu tetap
        terkirim tetapi seluruh nilainya null, dan langkah "CEK ENVELOPE" di prompt
        batal tanpa jejak apa pun.
        """
        import os
        import time

        nama, _ = campaign_riplay
        pdfs = sorted(f for f in os.listdir(PDF_DIR) if f.endswith(".pdf"))[:1]
        files = [("files", (f, open(os.path.join(PDF_DIR, f), "rb"), "application/pdf")) for f in pdfs]
        r = requests.post(f"{api}/upload_transcript", headers=auth,
                          data={"campaign": nama, "reuse": "false"}, files=files, timeout=180)
        assert r.status_code < 300, f"upload transkrip gagal: {r.status_code} {r.text[:300]}"
        rid = r.json()["result_id"]

        batas = time.time() + 240
        status = None
        while time.time() < batas:
            status = requests.get(f"{api}/result/{rid}", headers=auth, timeout=30).json().get("status")
            if status in ("done", "failed"):
                break
            time.sleep(2)
        assert status == "done", f"tiket tidak selesai (status={status})"

        jejak = requests.get(f"{STUB}/_jejak", timeout=30).json()["panggilan"]
        penilaian = [p for p in jejak if p["jenis"] == "penilaian"]
        assert penilaian, "tidak ada panggilan penilaian ke stub"
        assert "TNC PRODUCT REFERENCE DATA" in penilaian[-1]["blok_mentah"], (
            "blok TNC PRODUCT tidak ada di prompt penilaian"
        )
        assert "Rp 2.000.000" in penilaian[-1]["blok_mentah"], (
            "nilai RIPLAY tidak sampai ke blok TNC PRODUCT — rantainya putus"
        )
