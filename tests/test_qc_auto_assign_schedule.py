"""Batch auto assign terjadwal + Log QC (diport dari 4-service@e17ecca/2c1c01e, 6 Oktober 2026).

Tanpa DB: crud dan sesi diganti tiruan, karena yang diuji adalah keputusan
modulnya — kapan batch berikutnya, kapan di-skip, apa yang masuk antrean — bukan
SQL-nya (``bulk_assign_tickets_to_qc`` diuji di repo core).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

import qc_auto_assign as auto

WIB = timezone(timedelta(hours=7))


# --------------------------------------------------------------------------
# Jadwal
# --------------------------------------------------------------------------

def test_saklar_default_mati(monkeypatch):
    """Keputusan 6 Oktober 2026: worker kube berbagi DB prod, jadi tanpa env
    eksplisit tidak boleh ada yang membagi tiket."""
    monkeypatch.delenv("QC_AUTO_ASSIGN_ENABLED", raising=False)
    assert auto.schedule_enabled() is False


def test_saklar_bisa_dinyalakan(monkeypatch):
    for val in ("true", "1", " TRUE ", "on"):
        monkeypatch.setenv("QC_AUTO_ASSIGN_ENABLED", val)
        assert auto.schedule_enabled() is True
    for val in ("false", "0", "", "off"):
        monkeypatch.setenv("QC_AUTO_ASSIGN_ENABLED", val)
        assert auto.schedule_enabled() is False


def test_slot_berikutnya_hari_yang_sama():
    now = datetime(2026, 10, 6, 9, 30, tzinfo=WIB)
    assert auto.next_run(now) == datetime(2026, 10, 6, 11, 0, tzinfo=WIB)


def test_tepat_di_slot_menunjuk_slot_sesudahnya():
    now = datetime(2026, 10, 6, 16, 30, tzinfo=WIB)
    assert auto.next_run(now) == datetime(2026, 10, 7, 8, 0, tzinfo=WIB)


def test_input_utc_dibaca_sebagai_wib():
    # 00:30 UTC = 07:30 WIB -> slot 08:00 WIB hari itu.
    now = datetime(2026, 10, 6, 0, 30, tzinfo=timezone.utc)
    assert auto.next_run(now) == datetime(2026, 10, 6, 8, 0, tzinfo=WIB)


def test_label_slot():
    assert auto.schedule_labels() == ["08:00", "11:00", "13:00", "15:00", "16:30"]


# --------------------------------------------------------------------------
# Antrean
# --------------------------------------------------------------------------

def test_antrean_mengecualikan_collection_dan_qc_support(monkeypatch):
    seen = {}

    def fake_list_results(db, **kw):
        seen.update(kw)
        return [], 0

    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection, Complaint Handling")
    monkeypatch.setattr(auto.crud, "list_results", fake_list_results)
    monkeypatch.setattr(auto.crud, "list_qc_assignments", lambda db: [])
    auto.unassigned_pool(None)
    assert seen["exclude_uploaded_by_role"] == "qc_support"
    assert seen["exclude_campaigns"] == ["collection", "complaint handling"]
    assert seen["campaigns"] is None and seen["customer_ids"] is None, "jadwal = tanpa cakupan"


# --------------------------------------------------------------------------
# Batch terjadwal
# --------------------------------------------------------------------------

class _DB:
    def __init__(self):
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


def _wire(monkeypatch, qcs, pool, bulk=None):
    monkeypatch.setattr(auto, "active_qc_usernames", lambda db: list(qcs))
    monkeypatch.setattr(auto, "unassigned_pool", lambda db: (list(pool), list(pool)))
    calls = []

    def default_bulk(db, pairs, assigned_by_username=None):
        calls.append((list(pairs), assigned_by_username))
        return len(pairs)

    monkeypatch.setattr(auto.crud, "bulk_assign_tickets_to_qc", bulk or default_bulk)
    return calls


def test_batch_skip_tanpa_qc_aktif(monkeypatch):
    calls = _wire(monkeypatch, [], ["t1"])
    assert auto.run_scheduled_batch(_DB()) == {"assigned": 0, "skipped": "no_active_qc"}
    assert calls == []


def test_batch_skip_saat_antrean_habis(monkeypatch):
    calls = _wire(monkeypatch, ["a"], [])
    assert auto.run_scheduled_batch(_DB()) == {"assigned": 0, "skipped": "no_unassigned_tickets"}
    assert calls == []


def test_batch_membagi_rata_atas_nama_scheduler(monkeypatch):
    calls = _wire(monkeypatch, ["a", "b", "c"], [f"t{i}" for i in range(7)])
    out = auto.run_scheduled_batch(_DB())
    assert out["assigned"] == 7 and out["pool"] == 7 and out["qc_count"] == 3
    counts = sorted(out["per_qc"].values())
    assert sum(counts) == 7 and max(counts) - min(counts) <= 1
    (pairs, by), = calls
    assert by == auto.SCHEDULER_USERNAME


def test_batch_bentrok_dibatalkan_utuh(monkeypatch):
    def boom(db, pairs, assigned_by_username=None):
        raise IntegrityError("insert", {}, Exception("duplicate ticket_id"))

    _wire(monkeypatch, ["a"], ["t1"], bulk=boom)
    db = _DB()
    assert auto.run_scheduled_batch(db) == {"assigned": 0, "skipped": "conflict"}
    assert db.rolled_back


# --------------------------------------------------------------------------
# Log QC (GET /qc_assignment/log)
# --------------------------------------------------------------------------

class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _LogDB:
    def __init__(self, users):
        self._users = users

    def query(self, *_a):
        return _Q(self._users)


def _a(tid, qc, assigned_at):
    return SimpleNamespace(ticket_id=tid, qc_username=qc, assigned_at=assigned_at)


def test_log_dikelompokkan_per_hari_wib_dan_disaring_cakupan(monkeypatch):
    from api.routers import qc_assignment as qa

    rows = [
        # 2026-10-05 17:30 UTC = 6 Okt 00:30 WIB -> masuk 6 Oktober, bukan 5.
        _a("t1", "ani", datetime(2026, 10, 5, 17, 30)),
        _a("t2", "budi", datetime(2026, 10, 6, 2, 0)),
        _a("t3", "ani", datetime(2026, 10, 4, 3, 0)),
        _a("tx", "ani", datetime(2026, 10, 6, 2, 0)),  # di luar cakupan
        _a("t4", "budi", None),                        # tanpa tanggal -> dilewati
    ]
    monkeypatch.setattr(qa.crud, "list_qc_assignments", lambda db: rows)
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: {"t1", "t2", "t3", "t4"})
    users = [SimpleNamespace(username="ani", name="Ani"), SimpleNamespace(username="budi", name="Budi")]

    out = qa.qc_assignment_log(date_start="2026-10-05", date_end="2026-10-06",
                               db=_LogDB(users), current_user=object())
    assert [d["date"] for d in out["days"]] == ["2026-10-06"]
    (day,) = out["days"]
    assert day["total"] == 2
    assert [(q["qc_name"], q["ticket_ids"]) for q in day["qc"]] == [("Ani", ["t1"]), ("Budi", ["t2"])]


def test_log_tanggal_tidak_valid_berarti_tanpa_batas(monkeypatch):
    from api.routers import qc_assignment as qa

    rows = [_a("t1", "ani", datetime(2026, 1, 1, 3, 0))]
    monkeypatch.setattr(qa.crud, "list_qc_assignments", lambda db: rows)
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: None)
    out = qa.qc_assignment_log(date_start="bukan-tanggal", date_end=None,
                               db=_LogDB([]), current_user=object())
    assert out["date_start"] is None
    assert out["days"][0]["qc"][0]["qc_name"] == "ani", "tanpa nama di tabel user -> username"


def test_endpoint_jadwal_mengikuti_saklar(monkeypatch):
    from api.routers import qc_assignment as qa

    monkeypatch.delenv("QC_AUTO_ASSIGN_ENABLED", raising=False)
    out = qa.auto_assign_schedule(current_user=object())
    assert out["enabled"] is False
    assert out["slots"] == auto.schedule_labels()
    assert 0 <= out["seconds_until_next"] <= 24 * 3600
