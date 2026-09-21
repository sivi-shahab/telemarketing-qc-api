"""``GET /list_results/latest_date`` — tanggal default menu Results.

Kontraknya satu kalimat: tanggal yang dikembalikan, kalau dipakai sebagai
``date_start``/``date_end`` di ``/list_results``, HARUS memuat setidaknya satu
baris. Itu yang membuat dashboard boleh mengisikannya begitu saja saat halaman
dibuka tanpa risiko tabel kosong.

Menu Manual Check & Pending Check sengaja TIDAK memakai ini: keduanya antrean
kerja yang menumpuk lintas hari, dan mempersempitnya ke satu tanggal akan
menyembunyikan backlog.
"""
import uuid
from datetime import datetime

import pytest

from api.routers import stats as st
from db.models import Result

CAMPAIGN = "ZZ-TEST-LATEST-ROUTE"


@pytest.fixture()
def seeded(db):
    for ticket, gen in (("ZZROUTEA", datetime(2026, 9, 10, 8, 0)),
                        ("ZZROUTEB", datetime(2026, 9, 17, 8, 0))):
        db.add(Result(
            id=uuid.uuid4(), campaign=CAMPAIGN,
            source_files=[f"{ticket}_20260101120000.pdf"], status="done",
            generated_at=gen, uploaded_at=datetime(2020, 1, 1),
        ))
    db.flush()
    return db


def test_mengembalikan_tanggal_berformat_ymd(seeded, admin_user):
    out = st.results_latest_date(db=seeded, current_user=admin_user)
    assert out["date"] is None or len(out["date"]) == 10


def test_tanggalnya_benar_benar_memuat_baris(seeded, admin_user):
    """Pengikat utama: dashboard mengisikan tanggal ini apa adanya ke filter."""
    out = st.results_latest_date(db=seeded, current_user=admin_user)
    assert out["date"] is not None
    _, total = st._resolve_filtered_results(
        seeded, admin_user, date_start=out["date"], date_end=out["date"], page=1, limit=1
    )
    assert total >= 1
