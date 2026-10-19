"""Retry otomatis data acuan TMS/Ascend (19 Oktober 2026).

Tiket yang dievaluasi tanpa CASHLINE/CARD HOLDER tidak dinilai LLM dan tersimpan
PENDING. Worker (``tasks/reference_retry.py``) mengecek ulang DWH tiap 30 menit
untuk tiket yang dipilih ``crud.reference_gap_retry_plan``, dan halaman Results
menulis jadwalnya lewat ``stats._reference_retry_note``.

Baris test memakai ticket id acak dan transaksi yang selalu di-rollback.
"""
import uuid
from datetime import datetime, timedelta

SINCE = datetime(2000, 1, 1)


def _ticket(db, *, cashline=None, customer=None, ref=True, status="done",
            uploaded_at=datetime(2000, 1, 2)):
    from db.models import Result, ResultData

    tid = uuid.uuid4().hex[:10]
    r = Result(id=uuid.uuid4(), campaign="Cashline", status=status,
               source_files=[f"{tid}_call1.pdf"], uploaded_at=uploaded_at)
    db.add(r)
    db.flush()
    rj = {"evaluation": {"ai_status": "PENDING"}}
    if ref:
        rj["reference_data"] = {"cashline": cashline, "customer": customer}
    db.add(ResultData(result_id=r.id, result_json=rj))
    db.flush()
    return tid, r


def _plan(db):
    from db import crud

    return {p["ticket_id"]: p for p in crud.reference_gap_retry_plan(db, SINCE)}


def test_tms_kosong_dan_ascend_kosong_ikut(db):
    tms, _ = _ticket(db, cashline=None, customer=None)
    asc, _ = _ticket(db, cashline={"agent_id": "a1"}, customer=None)

    plan = _plan(db)

    assert plan[tms]["gaps"] == ("tms", "ascend")
    assert plan[asc]["gaps"] == ("ascend",)
    assert plan[asc]["campaign"] == "Cashline"


def test_data_lengkap_snapshot_lama_dan_lewat_batas_tidak_ikut(db):
    lengkap, _ = _ticket(db, cashline={"agent_id": "a1"}, customer={"CUST_CR_CARD1": "x"})
    lama, _ = _ticket(db, ref=False)
    basi, _ = _ticket(db, uploaded_at=SINCE - timedelta(days=1))
    belum, _ = _ticket(db, status="processing")

    plan = _plan(db)

    for tid in (lengkap, lama, basi, belum):
        assert tid not in plan


def test_yang_dinilai_hanya_row_terbaru(db):
    """Row lama kosong, row terbaru (JOB-3 mengunggah ulang) sudah lengkap -> tidak ikut."""
    from db.models import Result, ResultData

    tid, _ = _ticket(db, uploaded_at=datetime(2000, 1, 2))
    r = Result(id=uuid.uuid4(), campaign="Cashline", status="done",
               source_files=[f"{tid}_call1.pdf"], uploaded_at=datetime(2000, 1, 3))
    db.add(r)
    db.flush()
    db.add(ResultData(result_id=r.id, result_json={
        "reference_data": {"cashline": {"agent_id": "a"}, "customer": {"x": 1}}}))
    db.flush()

    assert tid not in _plan(db)


def test_pengajuan_manual_status_dan_reproses_aktif_dilewati(db):
    from db import crud
    from db.models import QcStatusRequest

    diajukan, r = _ticket(db)
    db.add(QcStatusRequest(result_id=r.id, requested_status="PASS", reason="cek"))
    db.flush()
    jalan, _ = _ticket(db)
    biasa, _ = _ticket(db)
    crud.create_reprocess_job(db, ["Cashline"], [crud.reprocess_plan_for_ticket(db, jalan)],
                              "test", scope="ticket")

    plan = _plan(db)

    assert diajukan not in plan
    assert jalan not in plan
    assert biasa in plan


# --- keterangan di kolom AI Status -------------------------------------------

NOW = datetime(2026, 10, 19, 3, 40)  # 10.40 WIB


def test_keterangan_selama_masih_dalam_batas():
    from api.routers.stats import _reference_retry_note

    note = _reference_retry_note(
        ("tms", "ascend"), datetime(2026, 10, 18, 2, 15),
        {"last_run_at": "2026-10-19T03:30:00+00:00", "interval_min": 30}, NOW,
    )

    assert note == "Dicek ulang otomatis tiap 30 menit s/d 25/10 09.15 WIB · terakhir 10.30 WIB"


def test_keterangan_tanpa_putaran_dan_lewat_batas():
    from api.routers.stats import _reference_retry_note

    assert _reference_retry_note(("ascend",), NOW, None, NOW).endswith("WIB")
    assert "terakhir" not in _reference_retry_note(("ascend",), NOW, None, NOW)
    assert _reference_retry_note(("ascend",), NOW - timedelta(days=8), None, NOW) == (
        "Cek ulang otomatis berhenti (lewat 7 hari)")


def test_agent_tidak_terpetakan_tidak_diberi_keterangan():
    from api.routers.stats import _reference_retry_note

    assert _reference_retry_note(("agent",), NOW, None, NOW) is None
    assert _reference_retry_note((), NOW, None, NOW) is None
