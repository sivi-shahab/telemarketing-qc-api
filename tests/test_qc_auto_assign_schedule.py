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


def test_interval_default_5_menit_dan_bisa_diatur(monkeypatch):
    monkeypatch.delenv("QC_AUTO_ASSIGN_INTERVAL_MIN", raising=False)
    assert auto.interval_minutes() == 5
    monkeypatch.setenv("QC_AUTO_ASSIGN_INTERVAL_MIN", "10")
    assert auto.interval_minutes() == 10
    for bad in ("0", "-3", "abc", ""):
        monkeypatch.setenv("QC_AUTO_ASSIGN_INTERVAL_MIN", bad)
        assert auto.interval_minutes() == 5


def test_putaran_berikutnya_kelipatan_interval(monkeypatch):
    monkeypatch.delenv("QC_AUTO_ASSIGN_INTERVAL_MIN", raising=False)
    now = datetime(2026, 10, 13, 9, 31, 20, tzinfo=WIB)
    assert auto.next_run(now) == datetime(2026, 10, 13, 9, 35, tzinfo=WIB)


def test_tepat_di_putaran_menunjuk_putaran_sesudahnya(monkeypatch):
    monkeypatch.delenv("QC_AUTO_ASSIGN_INTERVAL_MIN", raising=False)
    now = datetime(2026, 10, 13, 23, 55, tzinfo=WIB)
    assert auto.next_run(now) == datetime(2026, 10, 14, 0, 0, tzinfo=WIB)


def test_input_utc_dibaca_sebagai_wib(monkeypatch):
    monkeypatch.delenv("QC_AUTO_ASSIGN_INTERVAL_MIN", raising=False)
    now = datetime(2026, 10, 13, 0, 32, tzinfo=timezone.utc)  # 07:32 WIB
    assert auto.next_run(now) == datetime(2026, 10, 13, 7, 35, tzinfo=WIB)


def test_label_jadwal(monkeypatch):
    monkeypatch.delenv("QC_AUTO_ASSIGN_INTERVAL_MIN", raising=False)
    assert auto.schedule_labels() == ["tiap 5 menit"]


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

# --------------------------------------------------------------------------
# Antrean siap (App C, 13 Oktober 2026): hanya tiket yang SEMUA rekamannya done
# --------------------------------------------------------------------------

def _row(tid, campaign="Personal Loan", processed=True, context="PL01", rec=None):
    return {"id": tid, "tiket_id": rec or f"{tid}_1", "campaign": campaign,
            "context": context, "processed_at": 1791815402 if processed else None}


def test_antrean_siap_hanya_tiket_yang_semua_rekamannya_done(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    items = [
        _row("A"),
        _row("B", rec="B_1"), _row("B", rec="B_2", processed=False),  # sebagian belum
        _row("C", processed=False),
        _row("D", campaign="CashLine NTB", context="CLENTB"),
    ]
    pool, campaign_of, waiting = auto.ready_pool(items, assigned_ids=set())
    assert sorted(pool) == ["A", "D"]
    assert campaign_of == {"A": "Personal Loan", "D": "CashLine NTB"}
    assert waiting == 2, "B dan C dicoba lagi di putaran berikutnya"


def test_antrean_siap_melewati_yang_sudah_punya_qc_dan_collection(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    items = [
        _row("A"),
        _row("B"),
        _row("K", campaign="Collection", context="ACT02"),   # nama Collection
        _row("L", campaign="Kartu", context="collection"),   # context Collection
    ]
    pool, _c, waiting = auto.ready_pool(items, assigned_ids={"B"})
    assert pool == ["A"] and waiting == 0


def test_antrean_siap_tanpa_id_dibuang():
    pool, _c, _w = auto.ready_pool([{"id": None, "tiket_id": None, "processed_at": 1}], set())
    assert pool == []


# --------------------------------------------------------------------------
# Pemerataan HARIAN: beban QC hari ini ikut dihitung
# --------------------------------------------------------------------------

def test_rata_harian_mengejar_qc_yang_bebannya_masih_sedikit():
    import random
    total = {"a": 5, "b": 5, "c": 0}
    per_campaign = {("X", "a"): 5, ("X", "b"): 5}
    pool = [f"t{i}" for i in range(7)]
    pairs = auto.distribute_daily(pool, ["a", "b", "c"], {t: "X" for t in pool},
                                  total, per_campaign, rnd=random.Random(1))
    got = {}
    for _t, q in pairs:
        got[q] = got.get(q, 0) + 1
    assert got["c"] >= 5, "QC yang hari ini belum dapat apa-apa didahulukan"
    final = sorted(total[q] + got.get(q, 0) for q in "abc")
    assert final[-1] - final[0] <= 1


def test_rata_harian_per_campaign_dan_total_dari_batch_kecil_berturut():
    import random
    rnd = random.Random(7)
    total, per_campaign = {}, {}
    qcs = ["a", "b", "c", "d"]
    camps = ["P", "Q", "R"]
    n = 0
    for batch in range(40):  # 40 putaran 5 menit, 1-2 tiket per putaran
        pool = [f"t{n + i}" for i in range(1 + batch % 2)]
        n += len(pool)
        camp = {t: camps[int(t[1:]) % 3] for t in pool}
        for t, q in auto.distribute_daily(pool, qcs, camp, total, per_campaign, rnd=rnd):
            total[q] = total.get(q, 0) + 1
            per_campaign[(camp[t], q)] = per_campaign.get((camp[t], q), 0) + 1
    totals = [total.get(q, 0) for q in qcs]
    assert max(totals) - min(totals) <= 1
    for c in camps:
        counts = [per_campaign.get((c, q), 0) for q in qcs]
        assert max(counts) - min(counts) <= 1, c


def test_beban_hari_ini_dari_assignment_sejak_tengah_malam_wib():
    since = datetime(2026, 10, 12, 17, 0)  # 13 Okt 00:00 WIB, naive UTC
    rows = [
        _a("t1", "a", datetime(2026, 10, 13, 2, 0)),
        _a("t2", "a", datetime(2026, 10, 12, 16, 59)),  # kemarin -> tidak dihitung
        _a("t3", "b", datetime(2026, 10, 13, 9, 30)),
    ]
    total, per_campaign = auto.daily_loads(rows, since, {"t1": "X"})
    assert total == {"a": 1, "b": 1}
    assert per_campaign == {("X", "a"): 1, ("", "b"): 1}


# --------------------------------------------------------------------------
# Batch terjadwal
# --------------------------------------------------------------------------

class _DB:
    def __init__(self):
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


NOW = datetime(2026, 10, 13, 10, 0, tzinfo=WIB)


def _wire(monkeypatch, qcs, items_by_date, assignments=(), bulk=None):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    monkeypatch.setattr(auto, "active_qc_usernames", lambda db: list(qcs))
    fetched = []

    def fake_fetch_all(load_date=None, **_kw):
        fetched.append(load_date)
        if isinstance(items_by_date, Exception):
            raise items_by_date
        return {"items": list(items_by_date.get(load_date, []))}

    monkeypatch.setattr(auto.tickets_daily, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(auto.crud, "list_qc_assignments", lambda db: list(assignments))
    calls = []

    def default_bulk(db, pairs, assigned_by_username=None, source=None):
        # Batch terjadwal dicatat di qc_assignment_events dengan source "scheduler".
        assert source == "scheduler"
        calls.append((list(pairs), assigned_by_username))
        return len(pairs)

    monkeypatch.setattr(auto.crud, "bulk_assign_tickets_to_qc", bulk or default_bulk)
    return calls, fetched


def test_batch_membaca_app_c_h0_dan_h1(monkeypatch):
    _calls, fetched = _wire(monkeypatch, ["a"], {})
    auto.run_scheduled_batch(_DB(), now=NOW)
    assert fetched == ["2026-10-13", "2026-10-12"]


def test_batch_skip_tanpa_qc_aktif(monkeypatch):
    calls, fetched = _wire(monkeypatch, [], {"2026-10-13": [_row("t1")]})
    assert auto.run_scheduled_batch(_DB(), now=NOW) == {"assigned": 0, "skipped": "no_active_qc"}
    assert calls == [] and fetched == []


def test_batch_skip_bila_belum_ada_yang_done(monkeypatch):
    calls, _f = _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1", processed=False)]})
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    assert out == {"assigned": 0, "skipped": "no_ready_tickets", "waiting": 1}
    assert calls == []


def test_batch_app_c_mati_di_skip(monkeypatch):
    from services.tickets_daily import TicketsDailyError
    calls, _f = _wire(monkeypatch, ["a"], TicketsDailyError("down"))
    assert auto.run_scheduled_batch(_DB(), now=NOW) == {"assigned": 0, "skipped": "app_c_error"}
    assert calls == []


def test_batch_tiket_dua_tanggal_tidak_dobel(monkeypatch):
    calls, _f = _wire(monkeypatch, ["a", "b"], {
        "2026-10-13": [_row("t1")], "2026-10-12": [_row("t1"), _row("t2")],
    })
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    (pairs, _by), = calls
    assert sorted(t for t, _q in pairs) == ["t1", "t2"]
    assert out["assigned"] == 2


def test_batch_membagi_rata_harian_atas_nama_scheduler(monkeypatch):
    today = datetime(2026, 10, 13, 1, 0)  # naive UTC, hari ini WIB
    calls, _f = _wire(
        monkeypatch, ["a", "b", "c"],
        {"2026-10-13": [_row(f"t{i}") for i in range(4)]},
        assignments=[_a("x1", "a", today), _a("x2", "a", today), _a("x3", "b", today)],
    )
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    assert out["assigned"] == 4 and out["pool"] == 4 and out["qc_count"] == 3
    assert out["waiting"] == 0
    (pairs, by), = calls
    assert by == auto.SCHEDULER_USERNAME
    final = {"a": 2, "b": 1, "c": 0}
    for _t, q in pairs:
        final[q] += 1
    assert sorted(final.values()) == [2, 2, 3]


def test_batch_bentrok_dibatalkan_utuh(monkeypatch):
    def boom(db, pairs, assigned_by_username=None, source=None):
        raise IntegrityError("insert", {}, Exception("duplicate ticket_id"))

    _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1")]}, bulk=boom)
    db = _DB()
    assert auto.run_scheduled_batch(db, now=NOW) == {"assigned": 0, "skipped": "conflict"}
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


# --------------------------------------------------------------------------
# Penerima: QC Collection tidak ikut (12 Oktober 2026)
# --------------------------------------------------------------------------

def test_qc_yang_cakupannya_hanya_collection_dikecualikan():
    col = frozenset({"collection", "complaint handling"})
    assert auto.collection_only(["Collection"], col) is True
    assert auto.collection_only([" complaint handling ", "COLLECTION"], col) is True


def test_qc_tanpa_batas_atau_campuran_tetap_menerima():
    col = frozenset({"collection"})
    assert auto.collection_only([], col) is False, "tanpa batas = semua campaign"
    assert auto.collection_only(None, col) is False
    assert auto.collection_only(["Collection", "Cashline"], col) is False
    assert auto.collection_only(["Telemarketing"], col) is False


def test_env_collection_kosong_tidak_mengecualikan_siapa_pun():
    assert auto.collection_only(["Collection"], frozenset()) is False


# --------------------------------------------------------------------------
# campaign_map — campaign App C, jatuh ke Result.campaign
# --------------------------------------------------------------------------

def test_campaign_map_utamakan_app_c_lalu_result(monkeypatch):
    monkeypatch.setattr(auto.crud, "campaign_by_ticket_ids",
                        lambda db, ids: {"t1": "Cashline", "t2": "Cashline", "tx": "Cashline"})
    seen = {}

    def fake_fetch(**k):
        seen.update(k)
        return {"items": [
            {"id": "t1", "tiket_id": "t1_20261012", "campaign": "Personal Loan"},
            {"id": "t9", "campaign": "Megapay"},  # bukan bagian antrean
            {"id": "t2", "campaign": ""},          # kosong -> tetap Result.campaign
        ]}

    monkeypatch.setattr(auto.tickets_daily, "fetch_all", fake_fetch)
    got = auto.campaign_map(None, ["t1", "t2", "t3"], " 2026-10-10 ")
    assert got == {"t1": "Personal Loan", "t2": "Cashline"}
    assert seen == {"load_date": "2026-10-10"}


def test_campaign_map_app_c_mati_tidak_memblokir(monkeypatch):
    monkeypatch.setattr(auto.crud, "campaign_by_ticket_ids", lambda db, ids: {"t1": "Cashline"})

    def boom(**k):
        raise auto.tickets_daily.TicketsDailyError("down")

    monkeypatch.setattr(auto.tickets_daily, "fetch_all", boom)
    assert auto.campaign_map(None, ["t1"]) == {"t1": "Cashline"}
