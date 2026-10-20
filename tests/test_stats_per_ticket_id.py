"""Statistics menghitung per TICKET ID, bukan per baris Result (16 Oktober 2026).

Sejak 13 Oktober JOB-3 mengupload ulang tiket yang sama beberapa kali sehari; tiap
upload jadi baris Result baru (clone ``reuse``), sehingga 12-16 Oktober tercatat
1.148 baris untuk 211 ID. Satu ID harus terhitung sekali, dan Return (FAIL) bila
salah satu barisnya Return.
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from compliance import stats_aggregate as sa
from db import crud
from db.models import Result

T0 = datetime(2026, 10, 15, 4, 0)


def _row(tid, status="done", hours=0, files=None):
    return SimpleNamespace(
        id=uuid.uuid4(), status=status, uploaded_at=T0 + timedelta(hours=hours),
        source_files=files or [f"{tid}_20261015091552.pdf"],
    )


def _stub_ai(monkeypatch, verdicts, human=None):
    """``verdicts`` = AI Status per baris; ``human`` = ``{result.id: (status,
    tl_qc_status)}`` — Manual Status yang diajukan untuk baris itu."""
    calls = []

    def fake(db, rows):
        calls.append(list(rows))
        return {str(r.id): verdicts.get(r.id) for r in rows}

    def fake_qc(db, ids):
        out = {}
        for rid, spec in (human or {}).items():
            status, tl, decided = (*spec, None)[:3]
            if str(rid) in ids:
                out[str(rid)] = SimpleNamespace(
                    requested_status=status, tl_qc_status=tl, approval_status="pending",
                    requested_at=None, tl_qc_reviewed_at=decided, reviewed_at=None)
        return out

    monkeypatch.setattr(sa, "ai_status_map", fake)
    monkeypatch.setattr(crud, "qc_status_requests_for", fake_qc)
    return calls


def test_satu_baris_per_id_ambil_done_terbaru(monkeypatch):
    a1, a2, a3 = _row("A", hours=0), _row("A", hours=2), _row("A", "pending", hours=4)
    b = _row("B")
    _stub_ai(monkeypatch, {a1.id: "PASS", a2.id: "PASS"})
    out = sa.one_result_per_ticket(None, [a1, b, a2, a3])
    assert out == [b, a2]  # urutan input dipertahankan


def test_return_bila_salah_satu_recording_return(monkeypatch):
    old_fail, new_pass = _row("A", hours=0), _row("A", hours=3)
    _stub_ai(monkeypatch, {old_fail.id: "FAIL", new_pass.id: "PASS"})
    assert sa.one_result_per_ticket(None, [old_fail, new_pass]) == [old_fail]


def test_baris_usang_yang_tercakup_tidak_memvonis(monkeypatch):
    old = _row("A", hours=0, files=["A_1.pdf"])
    full = _row("A", hours=3, files=["A_1.pdf", "A_2.pdf"])
    _stub_ai(monkeypatch, {old.id: "FAIL", full.id: "PASS"})
    assert sa.one_result_per_ticket(None, [old, full]) == [full]


def test_vonis_human_final_menang_atas_return_baris_lain(monkeypatch):
    """Tiket 0803425lkJ (19 Oktober 2026): TL QC menyetujui PASS di baris 16 Okt,
    enam clone JOB-3 sesudahnya tetap FAIL tanpa vonis — Statistics memilih clone FAIL
    terbaru sehingga Qualified tidak pernah tampil. Vonis human berlaku untuk TIKETNYA."""
    voted = _row("A", hours=0)
    clones = [_row("A", hours=h) for h in (2, 4, 6)]
    _stub_ai(monkeypatch, {voted.id: "PASS", **{c.id: "FAIL" for c in clones}},
             human={voted.id: ("PASS", "approved")})
    assert sa.one_result_per_ticket(None, [voted, *clones]) == [voted]


def test_vonis_human_terbaru_bila_lebih_dari_satu(monkeypatch):
    old, new, fail = _row("A", hours=0), _row("A", hours=2), _row("A", hours=4)
    _stub_ai(monkeypatch, {old.id: "FAIL", new.id: "PASS", fail.id: "FAIL"},
             human={old.id: ("FAIL", "approved"), new.id: ("PASS", "approved")})
    assert sa.one_result_per_ticket(None, [old, new, fail]) == [new]


def test_vonis_yang_diputus_paling_akhir_menang(monkeypatch):
    """QC mengubah vonis lewat baris clone yang LEBIH LAMA: keputusan terakhir yang
    berlaku, bukan baris yang paling baru di-upload."""
    old, new = _row("A", hours=0), _row("A", hours=2)
    _stub_ai(monkeypatch, {old.id: "FAIL", new.id: "PASS"},
             human={old.id: ("FAIL", "approved", T0 + timedelta(days=2)),
                    new.id: ("PASS", "approved", T0 + timedelta(days=1))})
    assert sa.one_result_per_ticket(None, [old, new]) == [old]


def test_usulan_belum_final_tidak_mengalahkan_return(monkeypatch):
    voted, fail = _row("A", hours=0), _row("A", hours=2)
    _stub_ai(monkeypatch, {voted.id: "PASS", fail.id: "FAIL"},
             human={voted.id: ("PASS", "pending")})
    assert sa.one_result_per_ticket(None, [voted, fail]) == [fail]


def test_vonis_di_baris_usang_tidak_berlaku(monkeypatch):
    """Recording baru sudah dinilai di baris lain -> vonis atas evaluasi lama gugur
    seperti evaluasinya sendiri."""
    old = _row("A", hours=0, files=["A_1.pdf"])
    full = _row("A", hours=3, files=["A_1.pdf", "A_2.pdf"])
    _stub_ai(monkeypatch, {old.id: "PASS", full.id: "FAIL"},
             human={old.id: ("PASS", "approved")})
    assert sa.one_result_per_ticket(None, [old, full]) == [full]


def test_tanpa_done_ambil_baris_terbaru(monkeypatch):
    p1, p2 = _row("A", "failed", hours=0), _row("A", "pending", hours=1)
    _stub_ai(monkeypatch, {})
    assert sa.one_result_per_ticket(None, [p1, p2]) == [p2]


def test_tanpa_duplikat_tidak_menghitung_ai_status(monkeypatch):
    rows = [_row("A"), _row("B"), _row("", files=[])]
    calls = _stub_ai(monkeypatch, {})
    assert sa.one_result_per_ticket(None, rows) == rows
    assert calls == []


def test_status_per_ticket_done_menang_lalu_terbaru():
    rows = [
        ("A", "done", T0), ("A", "pending", T0 + timedelta(hours=1)),
        ("B", "failed", T0), ("B", "pending", T0 + timedelta(hours=1)),
        ("", "done", T0), (None, "done", T0),
    ]
    assert crud.status_per_ticket(rows) == {"A": "done", "B": "pending"}



# --- Menu Results: clone JOB-3 ikut menampilkan vonis tiketnya (19 Oktober 2026) ---

def _stub_siblings(monkeypatch, rows):
    def fake(db, tids):
        return [r for r in rows if r.status == "done" and sa._customer_id(r.source_files) in set(tids)]

    monkeypatch.setattr(crud, "done_results_by_ticket_ids", fake)


def test_clone_mewarisi_vonis_final_tiketnya(monkeypatch):
    voted, clone = _row("A", hours=0), _row("A", hours=3)
    other = _row("B")
    _stub_ai(monkeypatch, {}, human={voted.id: ("PASS", "approved")})
    _stub_siblings(monkeypatch, [voted, clone, other])
    out = sa.ticket_qc_requests(None, [clone, other])
    assert out[str(clone.id)].requested_status == "PASS"
    assert str(other.id) not in out


def test_clone_tidak_mewarisi_usulan_yang_belum_final(monkeypatch):
    voted, clone = _row("A", hours=0), _row("A", hours=3)
    _stub_ai(monkeypatch, {}, human={voted.id: ("PASS", "pending")})
    _stub_siblings(monkeypatch, [voted, clone])
    assert sa.ticket_qc_requests(None, [clone]) == {}


def test_baris_dengan_recording_baru_tidak_mewarisi(monkeypatch):
    """Recording yang belum pernah dilihat human tidak ikut divonis."""
    voted = _row("A", hours=0, files=["A_1.pdf"])
    newer = _row("A", hours=3, files=["A_1.pdf", "A_2.pdf"])
    _stub_ai(monkeypatch, {}, human={voted.id: ("PASS", "approved")})
    _stub_siblings(monkeypatch, [voted, newer])
    out = sa.ticket_qc_requests(None, [voted, newer])
    assert str(newer.id) not in out
    assert out[str(voted.id)].requested_status == "PASS"


def test_semua_baris_ikut_keputusan_terakhir(monkeypatch):
    a, b, c = _row("A", hours=0), _row("A", hours=1), _row("A", hours=2)
    _stub_ai(monkeypatch, {},
             human={a.id: ("FAIL", "approved", T0 + timedelta(days=1)),
                    b.id: ("PASS", "approved", T0 + timedelta(days=2))})
    _stub_siblings(monkeypatch, [a, b, c])
    out = sa.ticket_qc_requests(None, [a, b, c])
    assert {k: v.requested_status for k, v in out.items()} == {
        str(a.id): "PASS", str(b.id): "PASS", str(c.id): "PASS"}


def test_baris_belum_done_tidak_mewarisi(monkeypatch):
    voted, pend = _row("A", hours=0), _row("A", "pending", hours=3)
    _stub_ai(monkeypatch, {}, human={voted.id: ("PASS", "approved")})
    _stub_siblings(monkeypatch, [voted, pend])
    assert str(pend.id) not in sa.ticket_qc_requests(None, [pend])

def test_get_stats_menghitung_id_bukan_baris(db):
    before = crud.get_stats(db)
    tid = f"ZP{uuid.uuid4().hex[:8]}"
    for h in range(3):  # tiga upload ulang file yang sama
        db.add(Result(id=uuid.uuid4(), campaign="Cashline", status="done",
                      source_files=[f"{tid}_20261015091552.pdf"],
                      uploaded_at=T0 + timedelta(hours=h)))
    db.flush()
    after = crud.get_stats(db)
    assert after["total_uploaded"] - before["total_uploaded"] == 1
    assert after["done"] - before["done"] == 1


def test_ticket_qc_requests_dengan_db(db):
    """Query sungguhan: clone ``done`` membaca vonis final baris lain, baris dengan
    recording tambahan dan baris yang belum ``done`` tidak."""
    from db.models import QcStatusRequest

    tid = f"ZV{uuid.uuid4().hex[:8]}"
    f1, f2 = f"{tid}_20261015091552.pdf", f"{tid}_20261016091552.pdf"

    def add(status, hours, files):
        r = Result(id=uuid.uuid4(), campaign="Cashline", status=status,
                   source_files=files, uploaded_at=T0 + timedelta(hours=hours))
        db.add(r)
        return r

    voted, clone = add("done", 0, [f1]), add("done", 2, [f1])
    pend = add("pending", 3, [f1])
    db.flush()
    db.add(QcStatusRequest(result_id=voted.id, requested_status="PASS", reason="cek",
                           tl_qc_status="approved", tl_qc_reviewed_at=T0 + timedelta(days=1)))
    db.flush()
    out = sa.ticket_qc_requests(db, [clone, pend])
    assert out[str(clone.id)].requested_status == "PASS"
    assert str(pend.id) not in out

    newer = add("done", 5, [f1, f2])
    db.flush()
    out = sa.ticket_qc_requests(db, [clone, newer])
    assert str(newer.id) not in out
    # Baris bervonis kini usang (recording kedua sudah dinilai di ``newer``) ->
    # vonisnya gugur juga untuk clone.
    assert str(clone.id) not in out
