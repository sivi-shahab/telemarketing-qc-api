"""Snapshot Statistics harus gugur saat vonis human berubah (19 Oktober 2026).

``_stats_signature`` dulu hanya melihat results / result_data / banding
(``reviewed_at`` milik SPQ Head) / sales database. Manual Status yang disetujui
Team Leader QC — yang ikut mengunci AI Status — tidak menggeser sidik jarinya,
jadi Statistics terus menyajikan snapshot lama sampai kebetulan ada upload baru.
Keputusan TL QC atas banding juga hanya mengisi ``tl_qc_reviewed_at``.

Memakai fixture ``db`` (transaksi yang selalu di-rollback).
"""
import uuid
from datetime import datetime, timedelta

from db import crud
from db.models import ErrorCodeAppeal, QcStatusRequest, Result


def _later():
    # Lebih baru dari nilai apa pun yang sudah ada di DB, supaya MAX-nya bergeser.
    return datetime.utcnow() + timedelta(days=1)


def _result(db):
    r = Result(id=uuid.uuid4(), campaign="ZZSigVonis", status="done",
               source_files=[f"ZS{uuid.uuid4().hex[:8]}_call.pdf"],
               uploaded_at=datetime.utcnow())
    db.add(r)
    db.flush()
    return r


def test_signature_berubah_saat_manual_status_diajukan_dan_diputus(db):
    r = _result(db)
    before = crud._stats_signature(db)

    req = QcStatusRequest(result_id=r.id, requested_status="PASS", reason="cek",
                          requested_by_username="qc1", requested_by_role="qc")
    db.add(req)
    db.flush()
    diajukan = crud._stats_signature(db)
    assert diajukan != before

    req.tl_qc_status = "approved"
    req.tl_qc_username = "tl1"
    req.tl_qc_reviewed_at = _later()
    db.flush()
    disetujui_tl = crud._stats_signature(db)
    assert disetujui_tl != diajukan

    req.tl_qc_status = "escalated"
    req.approval_status = "approved"
    req.reviewed_at = _later() + timedelta(hours=1)
    db.flush()
    assert crud._stats_signature(db) != disetujui_tl


def test_signature_berubah_saat_tl_qc_memutus_banding(db):
    r = _result(db)
    ap = ErrorCodeAppeal(result_id=r.id, error_code="ZZ01", item_code="SC_CL_1",
                         qc_reason="cek", requested_by_username="qc1")
    db.add(ap)
    db.flush()
    before = crud._stats_signature(db)

    ap.tl_qc_status = "approved"
    ap.tl_qc_reviewed_at = _later()
    db.flush()
    assert crud._stats_signature(db) != before
