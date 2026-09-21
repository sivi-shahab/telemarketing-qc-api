#!/usr/bin/env python3
"""Stub LLM: server OpenAI/Azure-compatible untuk e2e, TANPA memanggil model sungguhan.

Dipasang sebagai service terpisah dan ditunjuk lewat ``LLM_BASE_URL`` — **kode keempat
repo tidak diubah sama sekali**. Itu yang membuat e2e ini menguji kode yang sebenarnya,
bukan versi yang dilunakkan agar lolos.

Pipeline memanggil model DUA kali dengan bentuk keluaran yang berbeda:

1. **Klasifikasi jenis rekaman** (``compliance.recording_type``) — dikenali dari system
   prompt yang menyebut "TEPAT SATU label jenis". Balasannya ``{"recordings": [...]}``.
2. **Penilaian scorecard** (``compliance.evaluator``) — sisanya. Balasannya objek
   evaluasi lengkap.

Keluarannya DETERMINISTIK supaya test bisa meng-assert angka. Itu justru alasan stub
dipakai: vonis model sungguhan tidak deterministik dan tidak bisa di-assert.

``usage`` ikut dipalsukan, termasuk ``cached_tokens`` dan ``reasoning_tokens``, supaya
jalur pencatatan token (Batch 8) ikut teruji — bukan hanya jalur bahagia.
"""
import json
import os
import re

from fastapi import FastAPI, Request

app = FastAPI(title="stub-llm")

PANGGILAN = []  # jejak untuk di-assert test: bentuk prompt yang benar-benar dikirim


def _klasifikasi(berkas):
    """Rekaman pertama utama, sisanya perbaikan — cukup untuk menguji alurnya."""
    out = []
    for i, f in enumerate(berkas):
        out.append({
            "file": f,
            "tag": "recording_utama" if i == 0 else "recording_perbaikan",
            "reason": "stub: rekaman pertama dianggap utama" if i == 0
                      else "stub: rekaman berikutnya dianggap perbaikan",
        })
    return {"recordings": out}


def _teks(content):
    """Ratakan isi pesan jadi teks.

    Penilaian mengirim ``content`` berupa string, sedangkan ekstraksi RIPLAY
    mengirim LIST bagian (teks + ``image_url``) karena ia panggilan vision. Tanpa
    perataan ini, regex di bawah kena ``TypeError`` begitu RIPLAY diuji.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _riplay():
    """Ekstraksi RIPLAY tetap — bentuknya mengikuti ``RIPLAY_SCHEMA``.

    Angkanya sengaja dibuat khas supaya test bisa membedakannya dari nilai bawaan
    apa pun: kalau "Rp 2.000.000" muncul di blok TNC PRODUCT pada prompt, ia hanya
    bisa berasal dari sini.
    """
    return {
        "nama_produk": "Mega Cash Line",
        "jenis_produk": "Personal Loan",
        "penerbit": "PT Bank Mega, Tbk.",
        "limit_pencairan": {"minimum": "Rp 2.000.000", "maksimum": "Rp 200.000.000"},
        "tenor_cicilan": {"pilihan_bulan": [12, 24, 36], "keterangan": None},
        "nominal_cicilan": {"rumus": "(Jumlah Pinjaman Pokok / Tenor) + (Jumlah pinjaman pokok x bunga)"},
        "suku_bunga": {"cicilan": "Mulai dari 1,75% (Flat per bulan)", "revolving": "0,1% / hari"},
        "biaya_provisi": "2% (dua persen) dari limit kredit",
        "pelunasan_dipercepat": "7% (tujuh persen) dari sisa pokok pinjaman",
        "biaya_admin": {
            "tiering": [
                {"rentang_pencairan": "<= 20.000.000", "biaya": "Rp 150.000"},
                {"rentang_pencairan": "> 20.000.000 - <= 50.000.000", "biaya": "Rp 300.000"},
                {"rentang_pencairan": "> 50.000.000", "biaya": "Rp 500.000"},
            ],
            "keterangan": None,
        },
    }


def _item(code, kategori, status, weight, tolerable="YES", skor=None):
    return {
        "item_code": code,
        "category": kategori,
        "status": status,
        "weight": weight,
        "item_score": weight if status == "SESUAI" else (skor if skor is not None else 0),
        "tolerable": tolerable,
        "reason": f"stub: {code} {status}",
        "evidence": {"quote": "stub", "ticket_id": ""},
    }


def _evaluasi():
    """Evaluasi tetap: cashline+MUS diminati, satu item gagal supaya skornya tidak bulat.

    Dua produk diminati -> max_score v4 = 100 + 36,75 = 136,75.
    Satu item bobot 10 BELUM_SESUAI -> skor 126,75. Angka itulah yang di-assert test.
    """
    return {
        "ai_summary": "stub evaluation",
        "call_id": "stub",
        "cashline_interest": {"status": "INTERESTED", "reason": "stub"},
        "mus_interest": {"status": "INTERESTED", "reason": "stub"},
        "mus_cc_interest": {"status": "NOT_STATED", "reason": "stub"},
        "campaign_interest": ["Mega Cashline", "Mega Ultima Shield"],
        "scorecard_result": [
            _item("SC_CL_1", "greeting", "SESUAI", 5),
            _item("SC_CL_2", "greeting", "SESUAI", 5),
            _item("SC_CL_24", "verifikasi dinamis", "BELUM_SESUAI", 10),
            _item("SC_CL_19", "penjelasan mega ultima shield", "SESUAI", 3),
            _item("SC_CL_33", "legal statement mega ultima shield", "SESUAI", 2.25),
        ],
        # Wajib ada sejak merge 4-service (required_keys, 31a3746): worker menuntut
        # keempat kunci Task B/C/D bila DWH mengembalikan baris acuan.
        "cashline_data_extraction": {},
        "card_holder_extraction": {},
        "card_holder_verification": [],
        "cashline_data_verification": [],
        "error_codes": [],
    }


@app.get("/health")
def health():
    return {"ok": True, "panggilan": len(PANGGILAN)}


@app.get("/_jejak")
def jejak():
    """Dibaca test untuk memeriksa BENTUK prompt yang benar-benar dikirim worker."""
    return {"panggilan": PANGGILAN}


@app.get("/campaign/{jalur}/{result_id}")
def dwh(jalur: str, result_id: str):
    """Stub DWH API Aplikasi A (``DWH_API_BASE_URL`` menunjuk ke sini).

    Sejak merge 4-service 21 September 2026 worker TIDAK menilai tiket tanpa baris
    TMS/Ascend (langsung PENDING), dan menggagalkan tiket bila DWH tidak menjawab.
    Tanpa route GET ini catch-all POST di bawah membalas 405, sehingga setiap tiket
    e2e berakhir ``failed``. Balasan minimal: dua baris tidak kosong.
    """
    return {
        "cashline": {"agent_id": "E2E01", "cust_name": "Budi Santoso",
                     "jenis-kartu-yang-dikehendaki": "Cashline Umum"},
        "customer": {"cust_name": "Budi Santoso", "no-ktpkitas": "3100000000000001"},
    }


@app.post("/_reset")
def reset():
    PANGGILAN.clear()
    return {"ok": True}


@app.post("/{path:path}")
async def chat(path: str, request: Request):
    body = await request.json()
    pesan = body.get("messages") or []
    system = _teks(next((m.get("content", "") for m in pesan if m.get("role") == "system"), ""))
    user_raw = next((m.get("content", "") for m in pesan if m.get("role") == "user"), "")
    user = _teks(user_raw)

    # Ekstraksi RIPLAY: panggilan vision TANPA system prompt, dikenali dari kalimat
    # pembuka RIPLAY_PROMPT. Harus dicek SEBELUM cabang penilaian, sebab cabang itu
    # `else` dan akan menelan RIPLAY — mengembalikan objek evaluasi yang lolos parse
    # JSON tetapi tidak punya "nama_produk", sehingga gate nama produk menolak 422
    # dan penyebabnya sulit ditebak.
    riplay = "ekstraktor dokumen RIPLAY" in user
    klasifikasi = "TEPAT SATU label jenis" in system
    if riplay:
        isi = json.dumps(_riplay(), ensure_ascii=False)
    elif klasifikasi:
        berkas = re.findall(r"^\s*-\s*([^\s|]+\.pdf)", user, re.M) or re.findall(r"([\w.-]+\.pdf)", user)
        isi = json.dumps(_klasifikasi(list(dict.fromkeys(berkas))), ensure_ascii=False)
    else:
        isi = json.dumps(_evaluasi(), ensure_ascii=False)

    PANGGILAN.append({
        "jenis": "riplay" if riplay else ("klasifikasi" if klasifikasi else "penilaian"),
        # Berapa gambar yang benar-benar terkirim — membuktikan PDF sungguh dirender,
        # bukan sekadar prompt teks yang lewat.
        "jumlah_gambar": sum(
            1 for b in (user_raw if isinstance(user_raw, list) else [])
            if isinstance(b, dict) and b.get("type") == "image_url"
        ),
        "path": path,
        "model": body.get("model"),
        # Urutan blok pada user message — inilah yang membuktikan penataan Batch 8
        # benar-benar sampai ke permintaan, bukan cuma ada di kode.
        "urutan_blok": re.findall(r"^([A-Z][A-Z ]+):$", user, re.M),
        "panjang_user": len(user),
        # Potongan awal user message apa adanya. ``urutan_blok`` hanya menyimpan NAMA
        # blok, sehingga isinya tak bisa diperiksa — padahal untuk TnC Product yang
        # penting justru nilainya sampai atau tidak, bukan judul bloknya ada.
        "blok_mentah": user[:20000],
    })

    return {
        "id": "stub", "object": "chat.completion", "model": body.get("model", "stub"),
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": isi}}],
        "usage": {
            "prompt_tokens": 18571, "completion_tokens": 1440, "total_tokens": 20011,
            "prompt_tokens_details": {"cached_tokens": 18176},
            "completion_tokens_details": {"reasoning_tokens": 1228},
        },
    }
