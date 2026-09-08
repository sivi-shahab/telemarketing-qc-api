"""Unit tests untuk ``/agent_error_summary/{result_id}``: ``agent_id`` & ``Tanggal``
harus SNAPSHOT-FIRST.

Regression guard: kedua kolom itu dulu HANYA dibaca dari baris cashline DWH live
(``crud.get_tms_cashline_by_result_id`` -> services/data_dwh.fetch_bundle), jadi
Agent ID / Agent Name / Tanggal tampil "—" tiap kali App A tidak menjawab atau
field-nya tidak ikut di endpoint cache — padahal hierarki Statistics, scope Team
Leader dan timer SLA H+2 sudah membaca nilai yang sama dari snapshot
``reference_data.cashline`` di ``result_data.result_json``
(``crud.cashline_agent_index`` / ``crud.tms_submit_time_map``).

Sekarang urutannya: snapshot dulu, DWH live hanya fallback saat snapshot belum
lengkap — dan pasangan agent_id/submit_time itu juga yang menyuapi tenure.

CATATAN: pytest tidak terpasang di container ini; asersi yang sama sudah
dijalankan lewat driver python biasa saat perubahan dibuat.
"""
from datetime import date

import pytest

from api.routers import agent_error as ae

SNAPSHOT_TIME = "2026-06-17 15:24:53"
LIVE_TIME = "2026-06-18 09:00:00"
FULL_SNAPSHOT = {"agent_id": "rizqi801", "submit_time": SNAPSHOT_TIME}
LIVE_ROW = {"agent_id": "budi902", "submit_time": LIVE_TIME}


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def summary(monkeypatch):
    """Panggil endpoint dengan snapshot & baris DWH yang bisa diatur per test.

    Mengembalikan ``(response, dwh_calls)`` supaya test bisa menegaskan kapan DWH
    live boleh disentuh.
    """
    def _call(snapshot=None, dwh_row=None, join_date=None):
        result_json = {"evaluation": {}}
        if snapshot is not None:
            result_json["reference_data"] = {"cashline": snapshot}
        calls = {"dwh": 0}

        def _dwh(db, cid):
            calls["dwh"] += 1
            return dwh_row

        monkeypatch.setattr(
            ae.crud, "get_result", lambda db, rid: _Obj(source_files=["CID123_call1.mp3"])
        )
        monkeypatch.setattr(ae.crud, "get_tms_cashline_by_result_id", _dwh)
        monkeypatch.setattr(
            ae.crud, "get_result_data", lambda db, rid: _Obj(result_json=result_json)
        )
        monkeypatch.setattr(ae.crud, "error_code_appeals_for_result", lambda db, rid: [])
        sales = {"rizqi801": {"name": "Rizqi", "join_date": join_date}} if join_date else {}
        monkeypatch.setattr(ae, "active_sales_map", lambda db: sales)
        monkeypatch.setattr("qc_core.sales_lookup.active_sales_map", lambda db: sales)
        out = ae.agent_error_summary("11111111-1111-1111-1111-111111111111", db=None)
        return out, calls["dwh"]

    return _call


def test_snapshot_lengkap_saat_dwh_mati(summary):
    """DWH tidak menjawab (row None) -> kedua kolom tetap terisi dari snapshot,
    dan endpoint tidak menembak App A sama sekali."""
    out, dwh_calls = summary(snapshot=FULL_SNAPSHOT)
    assert out["agent_id"] == "rizqi801"
    assert out["tanggal"] == SNAPSHOT_TIME
    assert dwh_calls == 0


def test_snapshot_menang_atas_dwh_live(summary):
    """Sumbernya harus sama dengan cashline_agent_index / timer SLA H+2."""
    out, _ = summary(snapshot=FULL_SNAPSHOT, dwh_row=LIVE_ROW)
    assert out["agent_id"] == "rizqi801"
    assert out["tanggal"] == SNAPSHOT_TIME


@pytest.mark.parametrize(
    "snapshot", [None, {"agent_id": "  ", "submit_time": "  "}], ids=["absen", "blank"]
)
def test_fallback_ke_dwh_saat_snapshot_kosong(summary, snapshot):
    """Result lama (dievaluasi sebelum snapshot disimpan) tetap dapat isinya."""
    out, dwh_calls = summary(snapshot=snapshot, dwh_row=LIVE_ROW)
    assert out["agent_id"] == "budi902"
    assert out["tanggal"] == LIVE_TIME
    assert dwh_calls == 1


def test_snapshot_separuh_dilengkapi_dwh(summary):
    """Snapshot lama bisa punya agent_id tanpa submit_time — sisanya dari DWH."""
    out, dwh_calls = summary(snapshot={"agent_id": "rizqi801"}, dwh_row=LIVE_ROW)
    assert out["agent_id"] == "rizqi801"
    assert out["tanggal"] == LIVE_TIME
    assert dwh_calls == 1


def test_kosong_saat_dua_sumber_kosong(summary):
    out, _ = summary()
    assert out["agent_id"] is None
    assert out["agent_name"] is None
    assert out["tanggal"] is None


def test_nama_dan_tenure_ikut_pasangan_yang_sama(summary):
    """"Agent ID", "Tanggal", "selisih_hari" dan "durasi_bergabung" tidak boleh
    beda sumber: DWH mati, jadi semuanya harus jalan dari snapshot."""
    out, dwh_calls = summary(snapshot=FULL_SNAPSHOT, join_date=date(2026, 6, 10))
    assert out["agent_name"] == "Rizqi"          # NAME dari active sales database
    assert out["tanggal"] == SNAPSHOT_TIME
    assert out["selisih_hari"] == 7              # 17 Juni - 10 Juni
    assert out["durasi_bergabung"] == "0 bulan"  # format_tenure: < 1 bulan
    assert dwh_calls == 0


def test_agent_name_fallback_ke_huruf_agent_id(summary):
    """Agent tidak ada di sales database -> pakai karakter alfabet agent_id."""
    out, _ = summary(snapshot=FULL_SNAPSHOT)
    assert out["agent_name"] == "rizqi"
