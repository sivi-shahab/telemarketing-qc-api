"""``crud.result_json_map`` mengambil JSON hasil evaluasi lewat cache Redis.

28 September 2026: Pending Check (395 result) dan hitung ulang Statistics mengambil
18 MB JSON dari Postgres remote setiap kali (3,6–5,5 detik). Baris ``result_data``
tidak pernah diubah sesudah tersimpan (reproses menambah baris BARU), jadi JSON per
id baris aman di-cache 30 hari tanpa risiko basi. Postgres tetap dipakai untuk
memilih baris TERBARU per result dan untuk baris yang belum ada di cache.

Transaksi test selalu di-rollback; Redis diganti tiruan.
"""
import uuid
from datetime import datetime, timedelta

import pytest


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.ttl, self.fail = {}, {}, fail

    def mget(self, keys):
        if self.fail:
            raise ConnectionError("redis mati")
        return [self.store.get(k) for k in keys]

    def pipeline(self, transaction=False):
        r = self

        class P:
            ops = []

            def set(self, k, v, ex=None):
                self.ops.append((k, v, ex))

            def execute(self):
                if r.fail:
                    raise ConnectionError("redis mati")
                for k, v, ex in self.ops:
                    r.store[k], r.ttl[k] = (v.encode() if isinstance(v, str) else v), ex
        return P()


@pytest.fixture()
def rows(db, monkeypatch):
    from db.models import Result, ResultData
    from services import redis_cache

    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "_client", lambda: fake)
    redis_cache.reset()
    res = Result(id=uuid.uuid4(), campaign="Cashline", status="done")
    db.add(res)
    db.flush()
    t = datetime(2000, 1, 1)
    lama = ResultData(result_id=res.id, result_json={"versi": "lama"}, created_at=t)
    baru = ResultData(result_id=res.id, result_json={"versi": "baru", "n": [1, 2]},
                      created_at=t + timedelta(hours=1))
    db.add_all([lama, baru])
    db.flush()
    yield res, baru, fake
    redis_cache.reset()


def test_mengambil_baris_terbaru_dan_menyimpannya_30_hari(db, rows):
    from db import crud
    from services import redis_cache

    res, baru, fake = rows
    assert crud.result_json_map(db, [str(res.id)]) == {str(res.id): {"versi": "baru", "n": [1, 2]}}
    key = crud._result_json_key(baru.id)
    assert key in fake.store and fake.ttl[key] == redis_cache.DEFAULT_TTL_SEC


def test_panggilan_berikutnya_dilayani_cache_tanpa_mengambil_json_dari_db(db, rows, monkeypatch):
    from db import crud

    res, _, _ = rows
    crud.result_json_map(db, [str(res.id)])

    def _dilarang(*a, **k):
        raise AssertionError("JSON diambil lagi dari Postgres")
    monkeypatch.setattr(crud, "_result_json_texts", _dilarang)

    assert crud.result_json_map(db, [str(res.id)])[str(res.id)]["versi"] == "baru"


def test_hasil_bukan_objek_bersama_antar_panggilan(db, rows):
    from db import crud

    res, _, _ = rows
    a = crud.result_json_map(db, [str(res.id)])[str(res.id)]
    a["versi"] = "diubah pemanggil"
    assert crud.result_json_map(db, [str(res.id)])[str(res.id)]["versi"] == "baru"


def test_redis_mati_tetap_dari_postgres(db, rows, monkeypatch):
    from db import crud
    from services import redis_cache

    res, _, _ = rows
    monkeypatch.setattr(redis_cache, "_client", lambda: FakeRedis(fail=True))
    redis_cache.reset()
    assert crud.result_json_map(db, [str(res.id)])[str(res.id)]["versi"] == "baru"


def test_daftar_kosong_dan_result_tanpa_data(db, rows):
    from db import crud

    assert crud.result_json_map(db, []) == {}
    assert crud.result_json_map(db, [str(uuid.uuid4())]) == {}
