"""Unit tests for crud.cashline_agent_index — the cid -> agent_id/submit_time map.

Regression guard for the bug where these lookups read the local ``tms_cashline``
table. That table stopped being filled when reference data moved to the DWH API,
so every lookup returned nothing: the Statistics hierarchy collapsed into a single
"(Tidak diketahui)" node and Team Leaders saw zero tickets.

The fast path must stay SQL-only (the snapshot already stored in
``result_data.result_json``); the DWH API is a fallback for rows evaluated before
App A started caching ``agent_id``/``submit_time``.
"""
import pytest

from db import crud


# --------------------------------------------------------------------------
# Fake SQLAlchemy query chain — returns canned (cid, agent_id, submit_time) rows
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
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a, **k):
        return _FakeQuery(self._rows)


@pytest.fixture(autouse=True)
def _clear_memo():
    """The DWH fallback memo is module-level; isolate it between tests."""
    crud._CASHLINE_ID_MEMO.clear()
    yield
    crud._CASHLINE_ID_MEMO.clear()


@pytest.fixture
def no_dwh(monkeypatch):
    """Fail the test if the fallback fires — the fast path must not touch DWH."""
    def _boom(cids):
        raise AssertionError(f"DWH fallback should not run, got {cids}")

    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", _boom)


# --------------------------------------------------------------------------
# Fast path — everything resolved straight from the stored snapshot
# --------------------------------------------------------------------------

def test_reads_agent_and_submit_time_from_stored_snapshot(no_dwh):
    db = _FakeDb([
        ("010923HWcN", "chreste801", "2026-07-27 16:02:21"),
        ("271136Z1mY", "sartika801", "2026-07-27 11:52:32"),
    ])
    assert crud.cashline_agent_index(db) == {
        "010923HWcN": {"agent_id": "chreste801", "submit_time": "2026-07-27 16:02:21"},
        "271136Z1mY": {"agent_id": "sartika801", "submit_time": "2026-07-27 11:52:32"},
    }


def test_trims_and_normalises_blank_values(no_dwh):
    db = _FakeDb([("  010923HWcN  ", "  chreste801  ", "   ")])
    assert crud.cashline_agent_index(db) == {
        "010923HWcN": {"agent_id": "chreste801", "submit_time": None},
    }


def test_skips_rows_without_a_customer_id(no_dwh):
    db = _FakeDb([("", "chreste801", "2026-07-27 16:02:21"), (None, "x801", "2026-01-01 00:00:00")])
    assert crud.cashline_agent_index(db) == {}


# --------------------------------------------------------------------------
# Fallback — only for rows whose snapshot predates the agent_id/submit_time fix
# --------------------------------------------------------------------------

def test_fallback_runs_only_for_rows_missing_agent_id(monkeypatch):
    asked = []

    def _fake(cids):
        asked.append(sorted(cids))
        return {c: {"agent_id": "recovered801", "submit_time": "2026-06-01 09:00:00"} for c in cids}

    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", _fake)
    db = _FakeDb([
        ("hasAgent", "chreste801", "2026-07-27 16:02:21"),
        ("noAgent", None, None),
    ])
    index = crud.cashline_agent_index(db)

    assert asked == [["noAgent"]], "only the row missing agent_id should hit DWH"
    assert index["hasAgent"]["agent_id"] == "chreste801"
    assert index["noAgent"]["agent_id"] == "recovered801"


def test_dwh_failure_leaves_entry_unknown_instead_of_raising(monkeypatch):
    monkeypatch.setattr(crud.data_dwh, "fetch_bundle", lambda cid: (_ for _ in ()).throw(RuntimeError("DWH down")))
    db = _FakeDb([("noAgent", None, None)])
    assert crud.cashline_agent_index(db) == {"noAgent": {"agent_id": None, "submit_time": None}}


def test_empty_dwh_result_is_not_memoised(monkeypatch):
    """A blank answer may just mean the DWH row has not landed yet — caching it
    would pin the ticket to "(Tidak diketahui)" until the process restarts."""
    monkeypatch.setattr(crud.data_dwh, "fetch_bundle", lambda cid: {"cashline": None})
    crud._cashline_ids_from_dwh(["noAgent"])
    assert "noAgent" not in crud._CASHLINE_ID_MEMO

    monkeypatch.setattr(
        crud.data_dwh, "fetch_bundle",
        lambda cid: {"cashline": {"agent_id": "late801", "submit_time": "2026-06-01 09:00:00"}},
    )
    assert crud._cashline_ids_from_dwh(["noAgent"])["noAgent"]["agent_id"] == "late801"
    assert crud._CASHLINE_ID_MEMO["noAgent"]["agent_id"] == "late801", "positive result must be memoised"


# --------------------------------------------------------------------------
# customer_ids_for_agent_ids — the login-scoping lookup built on the index
# --------------------------------------------------------------------------

def test_customer_ids_for_agent_ids_matches_case_insensitively(no_dwh):
    db = _FakeDb([
        ("cidA", "Chreste801", "2026-07-27 16:02:21"),
        ("cidB", "sartika801", "2026-07-27 11:52:32"),
    ])
    assert crud.customer_ids_for_agent_ids(db, ["CHRESTE801"]) == ["cidA"]
    assert sorted(crud.customer_ids_for_agent_ids(db, ["chreste801", "sartika801"])) == ["cidA", "cidB"]


def test_customer_ids_for_agent_ids_empty_input_skips_all_work():
    assert crud.customer_ids_for_agent_ids(_FakeDb([]), []) == []
    assert crud.customer_ids_for_agent_ids(_FakeDb([]), None) == []
