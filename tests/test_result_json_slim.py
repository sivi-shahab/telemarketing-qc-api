"""``crud.result_json_map`` per batch + ``slim`` (3 November 2026).

API di kube kena OOM: Pending Check, filter AI Status, dan Statistics memuat
evaluasi SEMUA tiket sekaligus (±570 MB per pemuatan, lama ±770 MB). Kini teks
mentahnya dibaca per ``RESULT_JSON_BATCH`` baris, dan ``slim=True`` membuang teks
item scorecard yang tidak dipakai menghitung angka (``SLIM_SCORECARD_DROP``).

Transaksi test selalu di-rollback; Redis diganti tiruan.
"""
import uuid
from datetime import datetime

import pytest

from tests.test_result_json_cache import FakeRedis


def _evaluation():
    return {
        "evaluation": {
            "scorecard_result": [
                {
                    "item_code": "SC_1",
                    "status": "BELUM_SESUAI",
                    "tolerable": "NO",
                    "item_score": 0,
                    "weight": 5,
                    "category": "Pembukaan",
                    "evidence": {"quote": "kutipan panjang", "timestamp": "00:01"},
                    "reason": "alasan panjang",
                    "requirement": "syarat panjang",
                    "point_of_improvement": "saran",
                    "dynamic_verification_detail": {"x": 1},
                },
                "bukan-dict",
            ],
            "card_holder_verification": [{"field": "nama", "evidence": "tetap"}],
        },
        "reference_data": {"cashline": {"agent_id": "A1"}},
    }


@pytest.fixture()
def banyak(db, monkeypatch):
    from db.models import Result, ResultData
    from services import redis_cache

    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "_client", lambda: fake)
    redis_cache.reset()
    ids = []
    for i in range(7):
        res = Result(id=uuid.uuid4(), campaign="Cashline", status="done")
        db.add(res)
        db.flush()
        db.add(ResultData(result_id=res.id, result_json={**_evaluation(), "i": i},
                          created_at=datetime(2000, 1, 1)))
        ids.append(str(res.id))
    db.flush()
    yield ids, fake
    redis_cache.reset()


def test_batch_kecil_tetap_mengembalikan_semua_tiket(db, banyak, monkeypatch):
    from db import crud

    ids, fake = banyak
    monkeypatch.setattr(crud, "RESULT_JSON_BATCH", 3)  # 7 tiket -> 3 batch
    out = crud.result_json_map(db, ids)
    assert sorted(out) == sorted(ids)
    assert sorted(v["i"] for v in out.values()) == list(range(7))
    # Semua baris tersimpan ke cache, juga saat diambil lintas batch.
    assert len(fake.store) == 7
    # Panggilan kedua dilayani cache seluruhnya, hasilnya sama.
    monkeypatch.setattr(crud, "_result_json_texts", lambda *a: pytest.fail("harus dari cache"))
    assert crud.result_json_map(db, ids) == out


def test_slim_membuang_teks_item_scorecard_saja(db, banyak):
    from db import crud

    ids, _ = banyak
    item = crud.result_json_map(db, ids[:1], slim=True)[ids[0]]["evaluation"]["scorecard_result"][0]
    for key in crud.SLIM_SCORECARD_DROP:
        assert key not in item
    # Field penentu vonis/angka tetap ada.
    assert {k: item[k] for k in ("item_code", "status", "tolerable", "item_score", "weight", "category")} == {
        "item_code": "SC_1", "status": "BELUM_SESUAI", "tolerable": "NO",
        "item_score": 0, "weight": 5, "category": "Pembukaan",
    }


def test_slim_tidak_menyentuh_blok_lain_dan_item_bukan_dict(db, banyak):
    from db import crud

    ids, _ = banyak
    rj = crud.result_json_map(db, ids[:1], slim=True)[ids[0]]
    assert rj["evaluation"]["scorecard_result"][1] == "bukan-dict"
    assert rj["evaluation"]["card_holder_verification"] == [{"field": "nama", "evidence": "tetap"}]
    assert rj["reference_data"] == {"cashline": {"agent_id": "A1"}}


def test_tanpa_slim_json_utuh_dan_cache_tidak_ikut_terpangkas(db, banyak):
    from db import crud

    ids, _ = banyak
    crud.result_json_map(db, ids[:1], slim=True)  # isi cache lewat jalur slim
    utuh = crud.result_json_map(db, ids[:1])[ids[0]]  # dari cache
    assert utuh["evaluation"]["scorecard_result"][0]["evidence"] == {
        "quote": "kutipan panjang", "timestamp": "00:01"}
    assert utuh["evaluation"]["scorecard_result"][0]["reason"] == "alasan panjang"


def test_slim_aman_untuk_json_tanpa_evaluasi():
    from db import crud

    assert crud._slim_result_json(None) is None
    assert crud._slim_result_json({"evaluation": None}) == {"evaluation": None}
    assert crud._slim_result_json({"evaluation": {"scorecard_result": None}}) == {
        "evaluation": {"scorecard_result": None}}
