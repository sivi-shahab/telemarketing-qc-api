"""Per-ticket manual check by QC ("ticket ini sudah saya cek manual").

Deliberately separate from ``qc_status.py``: that flow PROPOSES an AI-Status
change and needs TL QC + SPQ Head approval. This one asserts only that a human
QC looked at the ticket — it never changes the score, the AI verdict, or any
error code. Storage is append-only (see ``db.models.QcManualCheck``) so the trail
survives re-checks.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.qc_scope import ensure_can_view_result, ensure_qc_assigned_to_result
from api.schemas.result import QcManualCheckInfo
from db import crud
from api.permissions import QC_MANUAL_CHECK_APPROVE
from api.rbac import require

router = APIRouter(dependencies=[Depends(get_current_user)])


def _validate_result(db: Session, result_id: str):
    try:
        result = crud.get_result(db, result_id)
    except Exception:  # invalid UUID, etc.
        result = None
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Result tidak ditemukan"
        )
    return result


@router.post("/qc_manual_check/{result_id}", response_model=QcManualCheckInfo)
def approve_manual_check(
    result_id: str,
    note: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_MANUAL_CHECK_APPROVE)),
):
    """Mark a ticket as manually checked by the QC it is assigned to."""
    result = _validate_result(db, result_id)
    # A QC may only approve tickets assigned to them (same rule as every other
    # QC action); role tanpa QC_MANUAL_CHECK_APPROVE tidak pernah sampai sini.
    ensure_qc_assigned_to_result(db, current_user, result)
    return crud.create_qc_manual_check(
        db,
        result_id=result_id,
        username=current_user.username,
        role=current_user.role,
        note=note,
    )


@router.get("/qc_manual_check/{result_id}", response_model=list[QcManualCheckInfo])
def get_manual_check_history(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Full audit trail for a ticket, oldest first.

    Cakupannya mengikuti TIKET (``ensure_can_view_result``), bukan sekadar "sudah
    login". Asumsi lama — "daftar Results toh sudah men-scope" — hanya benar untuk
    UI: endpoint ini dipanggil dengan result_id, jadi tanpa gate ini riwayat
    pemeriksaan tiket campaign lain terbaca oleh siapa pun yang tahu id-nya."""
    result = _validate_result(db, result_id)
    ensure_can_view_result(db, current_user, result)
    return crud.qc_manual_check_history(db, result_id)
