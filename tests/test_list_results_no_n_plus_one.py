"""Pengayaan ``/list_results`` dibaca sekali untuk seluruh halaman, bukan per baris.

Satu halaman berisi 100 baris menghabiskan ~6 detik di server, dan 3 detik di
antaranya habis di ``crud.get_result_data`` yang dipanggil DI DALAM loop
``for r in results`` — 100 query terpisah, masing-masing menarik seluruh blob
``result_json``. ``crud.result_json_map`` mengerjakan hal yang sama untuk seluruh
halaman dalam satu query.

Biayanya dulu tertutup oleh fakta bahwa halamannya ada tiga sekaligus, jadi tidak
ada satu pun bagian yang menonjol. Setelah menu Results dibuka dengan filter
tanggal (satu halaman), sisa waktunya justru di sini.
"""
import pytest

from api.routers import stats as st
from db import crud
from db.models import User

# Route dipanggil sebagai fungsi Python biasa, jadi default ``Query(...)``-nya
# tidak pernah diselesaikan FastAPI. SELURUH parameter wajib disebut — parameter
# yang dilewat akan terbaca sebagai objek FastAPI, dan ``ticket_ids`` yang begitu
# menyaring habis seluruh halaman sehingga test lulus tanpa menyentuh apa pun.
# Bentuk yang sama dipakai ``_call_list_results`` di test_reprocess_filtered.
_DEFAULTS = dict(
    status=None, campaign=None, ticket_id=None, ai_status=None, manual_status=None,
    am_nip=None, tl_nip=None, agent_nip=None, qc_username=None,
    qc_support_username=None, ticket_ids=None, date_start=None, date_end=None,
    banding_pending=False, manual_status_pending=False, page=1, limit=100,
)


@pytest.fixture()
def viewer(db):
    """User yang cakupannya benar-benar memuat hasil ``done``.

    Cakupan tiap akun berbeda-beda (RBAC campaign, data_scope, isolasi QC
    Support), dan sebagian akun melihat NOL baris — dipakai untuk test ini,
    assertion-nya akan lulus tanpa pernah menyentuh kode yang diuji.
    """
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        rows, total = st._resolve_filtered_results(db, u, page=1, limit=20)
        if total and any(r.status == "done" for r in rows):
            return u
    pytest.skip("tidak ada user yang cakupannya memuat hasil done")


def test_tidak_memanggil_get_result_data_per_baris(db, viewer, monkeypatch):
    calls = []
    asli = crud.get_result_data

    def _tercatat(*a, **k):
        calls.append(a[1] if len(a) > 1 else None)
        return asli(*a, **k)

    monkeypatch.setattr(st.crud, "get_result_data", _tercatat)
    out = st.list_results(db=db, current_user=viewer, **_DEFAULTS)
    assert out.total > 0, "prasyarat: halaman harus berisi baris"
    assert calls == [], (
        "pengayaan masih N+1: %d panggilan get_result_data untuk satu halaman"
        % len(calls)
    )


def test_field_dari_result_json_tetap_benar(db, viewer):
    """Pengikat kebenaran — batching tidak boleh mengubah isi kolomnya.

    Dibandingkan langsung dengan ``result_json_map``, yang memakai aturan "baris
    terbaru per result_id" yang sama dengan ``get_result_data``.
    """
    out = st.list_results(db=db, current_user=viewer, **_DEFAULTS)
    rjson = crud.result_json_map(db, [str(it.result_id) for it in out.items])
    diperiksa = 0
    for it in out.items:
        j = rjson.get(str(it.result_id))
        if not isinstance(j, dict):
            continue
        assert it.audio_duration == j.get("audio_duration")
        assert it.recording_types == j.get("recording_types")
        diperiksa += 1
    assert diperiksa > 0, "prasyarat: minimal satu baris punya result_json"


def test_result_json_map_dibaca_sekali_per_halaman(db, viewer, monkeypatch):
    """``_missing_docs_map`` memakai ``rjson_map`` milik route, bukan membacanya ulang.

    Tanpa ``eval_by_id``, ``_missing_docs_map`` memanggil ``result_json_map`` lagi
    untuk tiket yang kena band similarity — blob yang sama ditarik dua kali, ~1
    detik per halaman 100 baris (diukur 21 September 2026).
    """
    calls = []
    asli = crud.result_json_map

    def _tercatat(*a, **k):
        calls.append(len(a[1]) if len(a) > 1 else None)
        return asli(*a, **k)

    monkeypatch.setattr(crud, "result_json_map", _tercatat)
    out = st.list_results(db=db, current_user=viewer, **_DEFAULTS)
    assert out.total > 0, "prasyarat: halaman harus berisi baris"
    assert len(calls) == 1, "result_json_map dipanggil %d kali: %r" % (len(calls), calls)
