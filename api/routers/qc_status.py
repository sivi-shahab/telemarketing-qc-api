from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import (
    get_spq_head_user,
    get_current_user,
    get_db,
    get_qc_user,
    get_team_leader_qc_user,
)
from api.qc_scope import ensure_qc_assigned_to_result
from api.schemas.result import QcStatusRequestInfo
from db import crud

router = APIRouter(dependencies=[Depends(get_current_user)])

VALID_STATUS = {"PASS", "FAIL"}
VALID_DECISION = {"approve", "reject"}
VALID_TL_DECISION = {"approve", "reject", "escalate"}


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


@router.post("/qc_status_request", response_model=QcStatusRequestInfo)
def submit_qc_status_request(
    result_id: str = Form(...),
    requested_status: str = Form(...),
    reason: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_qc_user),
):
    result = _validate_result(db, result_id)
    ensure_qc_assigned_to_result(db, current_user, result)

    requested_status = (requested_status or "").strip().upper()
    if requested_status not in VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status harus PASS atau FAIL",
        )
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alasan perubahan status wajib diisi",
        )

    req = crud.upsert_qc_status_request(
        db,
        result_id=result_id,
        requested_status=requested_status,
        reason=reason,
        username=current_user.username,
        role=current_user.role,
    )
    return req


@router.post("/qc_status_request/{result_id}/tl_review", response_model=QcStatusRequestInfo)
def tl_review_qc_status_request(
    result_id: str,
    decision: str = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_team_leader_qc_user),
):
    """Team Leader QC decision on a QC AI-status change request: 'approve'/'reject'
    final, atau 'escalate' ke SPQ Head. ``comment`` wajib diisi saat 'reject'."""
    decision = (decision or "").strip().lower()
    if decision not in VALID_TL_DECISION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Keputusan harus approve, reject, atau escalate",
        )
    comment = (comment or "").strip() or None
    if decision == "reject" and not comment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Komentar wajib diisi saat menolak permintaan",
        )
    req = crud.tl_review_qc_status_request(
        db, result_id=result_id, decision=decision, reviewer_username=current_user.username,
        comment=comment,
    )
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada permintaan perubahan status untuk result ini",
        )
    return req


@router.post("/qc_status_request/{result_id}/review", response_model=QcStatusRequestInfo)
def review_qc_status_request(
    result_id: str,
    decision: str = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_spq_head_user),
):
    decision = (decision or "").strip().lower()
    if decision not in VALID_DECISION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Keputusan harus approve atau reject",
        )
    comment = (comment or "").strip() or None
    if decision == "reject" and not comment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Komentar wajib diisi saat menolak permintaan",
        )

    # Tiered flow: SPQ Head may only decide requests that Team Leader QC ESCALATED.
    existing = crud.get_qc_status_request(db, result_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada permintaan perubahan status untuk result ini",
        )
    if getattr(existing, "tl_qc_status", "pending") != "escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Permintaan ini belum diteruskan (escalate) oleh Team Leader QC ke SPQ Head",
        )

    req = crud.review_qc_status_request(
        db,
        result_id=result_id,
        decision=decision,
        reviewer_username=current_user.username,
        comment=comment,
    )
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada permintaan perubahan status untuk result ini",
        )
    return req
