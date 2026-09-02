"""Unit tests for the change-flag source used by ``_missing_docs_map``.

Regression guard for the Statistics timeout: ``_missing_docs_map`` resolved the
TMS change flags through ``crud.get_tms_cashline_change_flags``, which fires ONE
HTTP call to the DWH API per ticket, sequentially. With 342 tickets that alone
cost ~22 s, and ``/stats/ai_status_timeseries`` blew past the 30 s axios timeout
on the Statistics page.

The flags must now come from the snapshot already stored in
``result_data.result_json["reference_data"]["cashline"]`` — one SQL query, no
HTTP — with the DWH call kept only as a fallback for tickets evaluated before
that snapshot started being embedded.
"""
import pytest

from db import crud
from compliance import documents, reference_data, stats_aggregate


# --------------------------------------------------------------------------
# Fake SQLAlchemy query chain — returns canned (cid, cashline) rows
# --------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def join(self, *a, **k):
        return self

    def distinct(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def query(self, *a, **k):
        return _FakeQuery(self._rows)


class _FakeResult:
    """Minimal stand-in for the ``Result`` ORM row that ``_missing_docs_map`` reads."""

    def __init__(self, rid, cid, uploaded_at=None):
        self.id = rid
        self.source_files = [f"{cid}_transcript.txt"]
        self.uploaded_at = uploaded_at


def _cashline(**overrides):
    """A cashline snapshot with every ``*-new`` column empty (= no data change)."""
    row = {c: "" for c in crud._KANTOR_NEW_COLS + crud._RUMAH_NEW_COLS}
    row["no-npwp-new"] = ""
    row["nik-new"] = ""
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# crud.cashline_change_flags_index — the SQL-only fast path
# --------------------------------------------------------------------------

def test_flags_index_reads_change_flags_from_stored_snapshot():
    db = _FakeDb([
        ("010923HWcN", _cashline(**{"alamat-kantor-1-new": "Jl. Baru No. 1"})),
        ("271136Z1mY", _cashline(**{"no-npwp-new": "09.254.294.3-407.000"})),
        ("100804IsPN", _cashline()),
    ])
    assert crud.cashline_change_flags_index(db) == {
        "010923HWcN": {"kantor": True, "rumah": False, "npwp": False, "nik": False},
        "271136Z1mY": {"kantor": False, "rumah": False, "npwp": True, "nik": False},
        "100804IsPN": {"kantor": False, "rumah": False, "npwp": False, "nik": False},
    }


def test_flags_index_skips_rows_without_a_cashline_snapshot():
    """A ticket evaluated before reference_data was embedded has no snapshot; it
    must be ABSENT (so the caller can fall back), not present with all-False."""
    db = _FakeDb([
        ("010923HWcN", _cashline(**{"nik-new": "3174091234560001"})),
        ("271136Z1mY", None),
    ])
    assert crud.cashline_change_flags_index(db) == {
        "010923HWcN": {"kantor": False, "rumah": False, "npwp": False, "nik": True},
    }


def test_flags_index_narrows_to_the_requested_cids():
    db = _FakeDb([
        ("010923HWcN", _cashline(**{"alamat-rumah-1-new": "Jl. Pindah No. 2"})),
        ("271136Z1mY", _cashline(**{"nik-new": "3174091234560001"})),
    ])
    assert crud.cashline_change_flags_index(db, ["  010923HWcN  "]) == {
        "010923HWcN": {"kantor": False, "rumah": True, "npwp": False, "nik": False},
    }
    assert crud.cashline_change_flags_index(db, []) == {}


# --------------------------------------------------------------------------
# _missing_docs_map — must prefer the snapshot over the per-ticket HTTP call
# --------------------------------------------------------------------------

@pytest.fixture
def stub_docs(monkeypatch):
    """Neutralise everything _missing_docs_map touches except the change flags:
    no uploaded documents, no card-holder band, no credit limit."""
    monkeypatch.setattr(crud, "document_types_by_result", lambda db, ids: {})
    monkeypatch.setattr(crud, "document_ocr_by_result", lambda db, ids: {})
    monkeypatch.setattr(documents, "card_holder_bands_apply", lambda uploaded_at: False)
    monkeypatch.setattr(reference_data, "get_credit_limit", lambda cid, db: None)


@pytest.fixture
def no_dwh(monkeypatch):
    """Fail the test if the per-ticket DWH call fires — that is the timeout."""
    def _boom(db, cids):
        raise AssertionError(f"DWH fallback should not run, got {cids}")

    monkeypatch.setattr(crud, "get_tms_cashline_change_flags", _boom)


def test_missing_docs_map_reads_flags_from_snapshot_without_touching_dwh(
    monkeypatch, stub_docs, no_dwh
):
    monkeypatch.setattr(crud, "cashline_change_flags_index", lambda db, cids: {
        "010923HWcN": {"kantor": True, "rumah": False, "npwp": False, "nik": False},
        "271136Z1mY": {"kantor": False, "rumah": False, "npwp": False, "nik": False},
    })
    results = [
        _FakeResult("r-1", "010923HWcN"),   # data berubah, belum ada upload -> missing
        _FakeResult("r-2", "271136Z1mY"),   # tidak ada perubahan -> tidak missing
    ]
    assert stats_aggregate._missing_docs_map(_FakeDb(), results) == {
        "r-1": True,
        "r-2": False,
    }


def test_missing_docs_map_falls_back_to_dwh_only_for_cids_without_snapshot(
    monkeypatch, stub_docs
):
    monkeypatch.setattr(crud, "cashline_change_flags_index", lambda db, cids: {
        "010923HWcN": {"kantor": False, "rumah": False, "npwp": False, "nik": False},
    })
    asked = []

    def _fallback(db, cids):
        asked.append(list(cids))
        return {"271136Z1mY": {"kantor": False, "rumah": False, "npwp": True, "nik": False}}

    monkeypatch.setattr(crud, "get_tms_cashline_change_flags", _fallback)

    results = [
        _FakeResult("r-1", "010923HWcN"),
        _FakeResult("r-2", "271136Z1mY"),   # tanpa snapshot -> lewat DWH
    ]
    out = stats_aggregate._missing_docs_map(_FakeDb(), results)

    assert asked == [["271136Z1mY"]], "hanya cid tanpa snapshot yang boleh ditembak"
    assert out == {"r-1": False, "r-2": True}
