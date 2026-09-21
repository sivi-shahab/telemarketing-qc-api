"""``crud.latest_result_date`` — tanggal data terakhir yang ada dalam cakupan.

Dipakai menu Results untuk mengisi filter tanggal saat halaman dibuka, supaya
sekali buka tidak lagi menarik SELURUH riwayat (dulu: loop ``limit=100`` sampai
20.000 baris, diulang tiap 7 detik selama ada tiket pending).

Tanggal yang dikembalikan WAJIB memakai ekspresi yang sama persis dengan filter
``date_start``/``date_end`` di ``crud.list_results`` — kalau tidak, tanggal yang
diisikan dashboard bisa menunjuk hari yang justru kosong menurut filternya.
"""
import uuid
from datetime import date, datetime

import pytest

from db import crud
from db.models import Result

CAMPAIGN = "ZZ-TEST-LATEST-DATE"


def _mk(db, ticket: str, generated_at: datetime) -> Result:
    r = Result(
        id=uuid.uuid4(),
        campaign=CAMPAIGN,
        source_files=[f"{ticket}_20260101120000.pdf"],
        status="done",
        generated_at=generated_at,
        # Sengaja jauh dari generated_at: yang dibaca harus tanggal seri
        # (submit_time -> generated_at -> uploaded_at), bukan waktu upload.
        uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
    )
    db.add(r)
    db.flush()
    return r


def test_mengembalikan_tanggal_terbaru_dalam_cakupan(db):
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    _mk(db, "ZZTESTB", datetime(2026, 9, 17, 8, 0))
    assert crud.latest_result_date(db, campaigns=[CAMPAIGN]) == date(2026, 9, 17)


def test_none_ketika_tidak_ada_baris_dalam_cakupan(db):
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    assert crud.latest_result_date(db, campaigns=["ZZ-CAMPAIGN-TANPA-BARIS"]) is None


def test_cakupan_campaign_kosong_berarti_tidak_ada_apa_apa(db):
    """List KOSONG = dibatasi ke himpunan kosong, sama seperti ``list_results``."""
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    assert crud.latest_result_date(db, campaigns=[]) is None


def test_campaign_yang_dikecualikan_tidak_ikut_dihitung(db):
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    assert crud.latest_result_date(db, exclude_campaigns=[CAMPAIGN]) != date(2026, 9, 10)


def test_dibatasi_ke_customer_ids(db):
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    _mk(db, "ZZTESTB", datetime(2026, 9, 17, 8, 0))
    got = crud.latest_result_date(db, campaigns=[CAMPAIGN], customer_ids=["ZZTESTA"])
    assert got == date(2026, 9, 10)


def test_customer_ids_kosong_berarti_tidak_ada_apa_apa(db):
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    assert crud.latest_result_date(db, campaigns=[CAMPAIGN], customer_ids=[]) is None


def test_sejalan_dengan_filter_tanggal_list_results(db):
    """Tanggal yang dikembalikan harus benar-benar memuat baris di ``list_results``.

    Ini pengikat kedua fungsi: kalau salah satu berganti basis tanggal
    (submit_time / generated_at / uploaded_at), test ini yang jatuh.
    """
    _mk(db, "ZZTESTA", datetime(2026, 9, 10, 8, 0))
    _mk(db, "ZZTESTB", datetime(2026, 9, 17, 8, 0))
    latest = crud.latest_result_date(db, campaigns=[CAMPAIGN])
    rows, total = crud.list_results(
        db, campaigns=[CAMPAIGN], date_start=latest, date_end=latest, page=1, limit=50
    )
    assert total >= 1
