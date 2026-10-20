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


def test_slot_aktif_dan_slot_sebelumnya():
    now = datetime(2026, 10, 13, 11, 40, tzinfo=WIB)
    assert auto.current_slot(now) == (
        datetime(2026, 10, 13, 11, 0, tzinfo=WIB), datetime(2026, 10, 13, 8, 0, tzinfo=WIB))


def test_slot_aktif_tepat_di_jamnya():
    now = datetime(2026, 10, 13, 8, 0, tzinfo=WIB)
    assert auto.current_slot(now)[0] == datetime(2026, 10, 13, 8, 0, tzinfo=WIB)


def test_slot_aktif_melewati_tengah_malam():
    # 06:00 WIB: slot aktif masih 16:30 kemarin, sebelumnya 15:00 kemarin.
    now = datetime(2026, 10, 13, 6, 0, tzinfo=WIB)
    assert auto.current_slot(now) == (
        datetime(2026, 10, 12, 16, 30, tzinfo=WIB), datetime(2026, 10, 12, 15, 0, tzinfo=WIB))
    # Slot 08:00: data barunya sejak 16:30 kemarin.
    now = datetime(2026, 10, 13, 8, 5, tzinfo=WIB)
    assert auto.current_slot(now)[1] == datetime(2026, 10, 12, 16, 30, tzinfo=WIB)


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

def _ep(h, m, day=13):
    """Epoch detik untuk jam WIB (bentuk ``inserted_at`` App C)."""
    return datetime(2026, 10, day, h, m, tzinfo=WIB).timestamp()


SLOT = datetime(2026, 10, 13, 8, 0, tzinfo=WIB)
PREV = datetime(2026, 10, 12, 16, 30, tzinfo=WIB)


def _row(tid, campaign="Personal Loan", processed=True, context="PL01", rec=None, ins=None):
    return {"id": tid, "tiket_id": rec or f"{tid}_1", "campaign": campaign,
            "context": context, "processed_at": 1791815402 if processed else None,
            "inserted_at": _ep(7, 0) if ins is None else ins}


def test_data_baru_belum_done_semua_menahan_seluruh_pembagian(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    items = [
        _row("A"),
        _row("B", rec="B_1"), _row("B", rec="B_2", processed=False),  # sebagian belum
    ]
    pool, _c, waiting = auto.slot_pool(items, set(), SLOT, PREV)
    assert waiting == 1
    assert pool == ["A"], "pool dikembalikan, tapi pemanggil tidak membagi selama waiting"


def test_data_baru_done_semua_dibagi_bersama_sisa_lama_yang_sudah_done(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    items = [
        _row("A"),
        _row("L1", ins=_ep(14, 0, day=12)),                  # lama, sudah done
        _row("L2", ins=_ep(14, 0, day=12), processed=False),  # lama, macet: tidak menahan
    ]
    pool, campaign_of, waiting = auto.slot_pool(items, set(), SLOT, PREV)
    assert sorted(pool) == ["A", "L1"] and waiting == 0
    assert campaign_of["A"] == "Personal Loan"


def test_tiket_yang_masuk_setelah_slot_menunggu_slot_berikutnya(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    items = [
        _row("A"),
        _row("N", ins=_ep(8, 1), processed=False),  # masuk setelah slot: tidak menahan
        _row("M", ins=_ep(9, 0)),                   # masuk setelah slot: belum dibagi
        _row("X", rec="X_1"), _row("X", rec="X_2", ins=_ep(8, 30)),  # rekaman baru setelah slot
    ]
    pool, _c, waiting = auto.slot_pool(items, set(), SLOT, PREV)
    assert pool == ["A"] and waiting == 0


def test_slot_pool_melewati_yang_sudah_punya_qc_dan_collection(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    items = [
        _row("A"),
        _row("B", processed=False),                                 # sudah punya QC
        _row("K", campaign="Collection", context="ACT02", processed=False),
        _row("L", campaign="Kartu", context="collection", processed=False),
    ]
    pool, _c, waiting = auto.slot_pool(items, assigned_ids={"B"}, slot_start=SLOT, prev_start=PREV)
    assert pool == ["A"] and waiting == 0


def test_slot_pool_tanpa_id_dibuang():
    pool, _c, _w = auto.slot_pool([{"id": None, "tiket_id": None, "processed_at": 1}],
                                  set(), SLOT, PREV)
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
    # Tanpa QC nonaktif hari ini, kecuali test-nya mengganti (lihat _wire_reassign).
    monkeypatch.setattr(auto.crud, "qc_reassign_candidates", lambda db, since, slot_start: [])
    return calls, fetched


def test_batch_membaca_app_c_h0_dan_h1(monkeypatch):
    _calls, fetched = _wire(monkeypatch, ["a"], {})
    auto.run_scheduled_batch(_DB(), now=NOW)
    assert fetched == ["2026-10-13", "2026-10-12"]


def test_batch_skip_tanpa_qc_aktif(monkeypatch):
    calls, fetched = _wire(monkeypatch, [], {"2026-10-13": [_row("t1")]})
    assert auto.run_scheduled_batch(_DB(), now=NOW) == {"assigned": 0, "skipped": "no_active_qc"}
    assert calls == [] and fetched == []


def test_batch_menunggu_bila_data_baru_belum_done_semua(monkeypatch):
    calls, _f = _wire(monkeypatch, ["a"], {"2026-10-13": [
        _row("t1"), _row("t2", processed=False)]})
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    assert out == {"assigned": 0, "skipped": "waiting_not_done", "waiting": 1, "slot": "08:00"}
    assert calls == []


def test_batch_skip_bila_tidak_ada_yang_siap(monkeypatch):
    calls, _f = _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1", ins=_ep(9, 0))]})
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    assert out == {"assigned": 0, "skipped": "no_ready_tickets", "slot": "08:00"}
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
    assert out["slot"] == "08:00"
    (pairs, by), = calls
    assert by == auto.SCHEDULER_USERNAME
    final = {"a": 2, "b": 1, "c": 0}
    for _t, q in pairs:
        final[q] += 1
    assert sorted(final.values()) == [2, 2, 3]


def test_batch_beban_per_campaign_memakai_campaign_tiket_yang_sudah_di_assign(monkeypatch):
    """Tiket hari ini yang SUDAH punya QC harus terhitung di campaign-nya (dari App C),
    bukan di kelompok kosong — kalau tidak, rata per campaign mulai dari nol tiap
    putaran. Total a dan b seri (2-2), jadi hanya hitungan per campaign yang
    menentukan: kedua tiket PL baru harus ke b."""
    today = datetime(2026, 10, 13, 1, 0)
    calls, _f = _wire(
        monkeypatch, ["a", "b"],
        {"2026-10-13": [_row("p1", campaign="PL"), _row("p2", campaign="PL"),
                        _row("m1", campaign="MG"), _row("m2", campaign="MG"),
                        _row("new1", campaign="PL"), _row("new2", campaign="PL")]},
        assignments=[_a("p1", "a", today), _a("p2", "a", today),
                     _a("m1", "b", today), _a("m2", "b", today)],
    )
    auto.run_scheduled_batch(_DB(), now=NOW)
    (pairs, _by), = calls
    assert sorted(pairs) == [("new1", "b"), ("new2", "b")]


def test_batch_bentrok_dibatalkan_utuh(monkeypatch):
    def boom(db, pairs, assigned_by_username=None, source=None):
        raise IntegrityError("insert", {}, Exception("duplicate ticket_id"))

    _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1")]}, bulk=boom)
    db = _DB()
    assert auto.run_scheduled_batch(db, now=NOW) == {"assigned": 0, "skipped": "conflict"}
    assert db.rolled_back


# --------------------------------------------------------------------------
# Bagi ulang tiket QC nonaktif (19 Oktober 2026)
# --------------------------------------------------------------------------

def _wire_reassign(monkeypatch, moving, result_campaign=None):
    asked, moved = [], []

    def candidates(db, since, slot_start):
        asked.append((since, slot_start))
        return list(moving)

    def reassign(db, pairs, assigned_by_username=None, source=None):
        moved.append((sorted(pairs), assigned_by_username, source))
        return len(pairs)

    monkeypatch.setattr(auto.crud, "qc_reassign_candidates", candidates)
    monkeypatch.setattr(auto.crud, "reassign_tickets_to_qc", reassign)
    monkeypatch.setattr(auto.crud, "campaign_by_ticket_ids",
                        lambda db, ids: dict(result_campaign or {}))
    return asked, moved


def test_reassign_memakai_batas_hari_ini_dan_slot_aktif(monkeypatch):
    _wire(monkeypatch, ["a"], {})
    asked, _m = _wire_reassign(monkeypatch, [])
    auto.run_scheduled_batch(_DB(), now=NOW)  # 10.00 WIB -> slot 08.00
    (since, slot_start), = asked
    assert since == datetime(2026, 10, 12, 17, 0)  # 00.00 WIB 13 Okt, UTC naive
    assert slot_start == datetime(2026, 10, 13, 1, 0)  # 08.00 WIB


def test_tiket_qc_nonaktif_dibagi_rata_ke_qc_aktif(monkeypatch):
    today = datetime(2026, 10, 13, 1, 30)
    olds = [_a(f"x{i}", "z", today) for i in range(4)]
    calls, _f = _wire(monkeypatch, ["a", "b"], {}, assignments=olds)
    _asked, moved = _wire_reassign(monkeypatch, [(f"x{i}", "z", "qc_nonaktif") for i in range(4)])

    out = auto.run_scheduled_batch(_DB(), now=NOW)

    (pairs, by, source), = moved
    assert by == auto.SCHEDULER_USERNAME and source == "qc_nonaktif"
    assert sorted(t for t, _q in pairs) == ["x0", "x1", "x2", "x3"]
    assert sorted(q for _t, q in pairs).count("a") == 2  # rata: 2-2
    assert out["reassigned"] == 4 and out["reassigned_per_qc"] == {"a": 2, "b": 2}
    assert calls == []  # tidak ada tiket baru


def test_reassign_tidak_tertahan_gerbang_data_baru(monkeypatch):
    """Data baru slot ini belum done -> tiket baru menunggu, tetapi tiket QC
    nonaktif (sudah done, tinggal dikerjakan) tetap dibagi ulang."""
    calls, _f = _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1", processed=False)]})
    _asked, moved = _wire_reassign(monkeypatch, [("x1", "z", "qc_nonaktif")])

    out = auto.run_scheduled_batch(_DB(), now=NOW)

    assert out["skipped"] == "waiting_not_done" and out["reassigned"] == 1
    assert moved[0][0] == [("x1", "a")]
    assert calls == []


def test_reassign_rata_per_campaign_dengan_beban_hari_ini(monkeypatch):
    """Beban hari ini dihitung TANPA tiket yang dipindah: b sudah memegang 1 PL hari
    ini, jadi tiket PL dari QC nonaktif jatuh ke a."""
    today = datetime(2026, 10, 13, 1, 30)
    calls, _f = _wire(monkeypatch, ["a", "b"], {"2026-10-13": [_row("p0", campaign="PL")]},
                      assignments=[_a("p0", "b", today), _a("x1", "z", today)])
    _asked, moved = _wire_reassign(monkeypatch, [("x1", "z", "qc_nonaktif")], result_campaign={"x1": "PL"})

    auto.run_scheduled_batch(_DB(), now=NOW)

    assert moved[0][0] == [("x1", "a")]


def test_kandidat_campuran_dipanggil_per_source(monkeypatch):
    """QC nonaktif dan QC ganti role dibagi dalam satu putaran, tetapi dicatat
    dengan source masing-masing (dua panggilan reassign_tickets_to_qc)."""
    today = datetime(2026, 10, 13, 1, 30)
    olds = [_a("x1", "z", today), _a("x2", "y", today), _a("x3", "y", today)]
    calls, _f = _wire(monkeypatch, ["a", "b"], {}, assignments=olds)
    _asked, moved = _wire_reassign(monkeypatch, [
        ("x1", "z", "qc_nonaktif"), ("x2", "y", "qc_ganti_role"), ("x3", "y", "qc_ganti_role"),
    ])

    out = auto.run_scheduled_batch(_DB(), now=NOW)

    by_source = {src: sorted(t for t, _q in pairs) for pairs, _by, src in moved}
    assert len(moved) == 2
    assert by_source == {"qc_nonaktif": ["x1"], "qc_ganti_role": ["x2", "x3"]}
    assert all(by == auto.SCHEDULER_USERNAME for _p, by, _s in moved)
    assert out["reassigned"] == 3 and sum(out["reassigned_per_qc"].values()) == 3


def test_tanpa_tiket_qc_nonaktif_hasil_batch_tidak_berubah(monkeypatch):
    calls, _f = _wire(monkeypatch, ["a"], {"2026-10-13": [_row("t1")]})
    _asked, moved = _wire_reassign(monkeypatch, [])
    out = auto.run_scheduled_batch(_DB(), now=NOW)
    assert moved == [] and "reassigned" not in out and out["assigned"] == 1


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
