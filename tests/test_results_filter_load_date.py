"""Filter tanggal Results memakai ``load_date`` App C (20 Oktober 2026).

Tanggal tiket = ``load_date`` TERAKHIR di ``ticket_load_dates``; tiket tanpa baris
di sana memakai aturan lama (Tanggal Agree -> generated_at -> WIB uploaded_at).
Result sengaja dibuat dengan ``generated_at`` jauh dari load_date supaya yang
terbaca jelas load_date-nya.
"""
import uuid
from datetime import date, datetime

from db import crud
from db.models import Result

CAMPAIGN = "ZZ-TEST-LOAD-DATE"


def _mk(db, ticket, generated_at=datetime(2026, 9, 1, 8, 0)):
    r = Result(
        id=uuid.uuid4(),
        campaign=CAMPAIGN,
        source_files=[f"{ticket}_20260101120000.pdf"],
        status="done",
        generated_at=generated_at,
        uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
    )
    db.add(r)
    db.flush()
    return r


def _loads(db, ticket, *days):
    crud.upsert_ticket_load_dates(
        db, [(ticket, date(2026, 10, d), "X") for d in days]
    )
    db.flush()


def _hit(db, start, end):
    _rows, total = crud.list_results(
        db, campaigns=[CAMPAIGN], date_start=start, date_end=end, page=1, limit=50
    )
    return total == 1


def test_satu_load_date_dalam_rentang(db, ticket_load_dates_table):
    _mk(db, "ZZLD1")
    _loads(db, "ZZLD1", 13)
    assert _hit(db, date(2026, 10, 12), date(2026, 10, 17))


def test_multi_load_terakhir_di_rentang_lolos(db, ticket_load_dates_table):
    _mk(db, "ZZLD2")
    _loads(db, "ZZLD2", 10, 15)
    assert _hit(db, date(2026, 10, 12), date(2026, 10, 17))


def test_multi_load_terakhir_di_luar_tidak_lolos(db, ticket_load_dates_table):
    _mk(db, "ZZLD3")
    _loads(db, "ZZLD3", 14, 16, 19)
    assert not _hit(db, date(2026, 10, 12), date(2026, 10, 17))
    assert _hit(db, date(2026, 10, 18), date(2026, 10, 19))


def test_tanpa_app_c_pakai_aturan_lama(db, ticket_load_dates_table):
    _mk(db, "ZZLD4", datetime(2026, 10, 14, 8, 0))
    assert _hit(db, date(2026, 10, 12), date(2026, 10, 17))
    _mk(db, "ZZLD5", datetime(2026, 10, 10, 8, 0))
    _rows, total = crud.list_results(
        db, campaigns=[CAMPAIGN], date_start=date(2026, 10, 12),
        date_end=date(2026, 10, 17), page=1, limit=50,
    )
    assert total == 1  # hanya ZZLD4


def test_batas_inklusif_dan_satu_sisi(db, ticket_load_dates_table):
    _mk(db, "ZZLD6")
    _loads(db, "ZZLD6", 12)
    assert _hit(db, date(2026, 10, 12), date(2026, 10, 17))
    assert _hit(db, date(2026, 10, 12), None)
    assert _hit(db, None, date(2026, 10, 12))


def test_latest_result_date_pakai_load_terakhir(db, ticket_load_dates_table):
    _mk(db, "ZZLD7", datetime(2026, 10, 5, 8, 0))
    _loads(db, "ZZLD7", 10, 18)
    assert crud.latest_result_date(db, campaigns=[CAMPAIGN]) == date(2026, 10, 18)
