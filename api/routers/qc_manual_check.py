"""Per-ticket manual check by QC ("ticket ini sudah saya cek manual").

Deliberately separate from ``qc_status.py``: that flow PROPOSES an AI-Status
change and needs TL QC + SPQ Head approval. This one asserts only that a human
QC looked at the ticket — it never changes the score, the AI verdict, or any
error code. Storage is append-only (see ``db.models.QcManualCheck``) so the trail
survives re-checks.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db, get_qc_user
from api.qc_scope import ensure_qc_assigned_to_result
from api.schemas.result import QcManualCheckInfo
from db import crud

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
    current_user=Depends(get_qc_user),
):
    """Mark a ticket as manually checked by the QC it is assigned to."""
    result = _validate_result(db, result_id)
    # A QC may only approve tickets assigned to them (same rule as every other
    # QC action); non-QC roles never reach here thanks to get_qc_user.
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
    """Full audit trail for a ticket, oldest first. Readable by any authenticated
    role — the Results list already scopes which tickets a user can see."""
    _validate_result(db, result_id)
    return crud.qc_manual_check_history(db, result_id)
