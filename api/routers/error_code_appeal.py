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
from api.schemas.result import ErrorCodeAppealInfo
from compliance.error_codes import effective_appeal_status, is_cashline_code
from compliance.error_reasons import ERROR_REASONS
from db import crud

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/error_reasons")
def list_error_reasons():
    """Master Error Code catalog (46 codes: System/Human/Customer) for the Manual
    Check "New Error Code" dropdown. Each entry: code, error_type, category,
    risk_base, campaign, details, label."""
    return ERROR_REASONS

VALID_DECISION = {"approve", "reject"}
# Team Leader QC has an extra option: escalate (forward to SPQ Head).
VALID_TL_DECISION = {"approve", "reject", "escalate"}

# Sources a QC may 'add' an error to (OCR deferred). The 3 structured sources attach
# to an existing evaluation item/field; 'others' is display-only.
_VALID_ADD_SOURCES = {"scorecard", "cashline_data", "card_holder", "others"}
# Added codes must come from the master catalog (same dropdown as 'change').
_MASTER_CODES = {str(e.get("code") or "").strip().upper() for e in ERROR_REASONS if e.get("code")}


def _appeal_active(appeal) -> bool:
    """An appeal blocks a re-submission only while it is still IN REVIEW (pending) —
    you cannot have two in-flight bandings on the same row. A FINALIZED banding
    (approved OR rejected) may be re-appealed, e.g. to REMOVE an error code that a
    previous banding added (approved) or that a rejected banding left behind."""
    return effective_appeal_status(appeal) == "pending"


def _appeal_info(appeal) -> ErrorCodeAppealInfo:
    return ErrorCodeAppealInfo(
        id=appeal.id,
        result_id=str(appeal.result_id),
        error_code=appeal.error_code,
        item_code=appeal.item_code,
        ai_sumber=appeal.ai_sumber,
        ai_risk_base=appeal.ai_risk_base,
        ai_details_error=appeal.ai_details_error,
        ai_reason=appeal.ai_reason,
        ai_evidence=appeal.ai_evidence,
        ai_ticket_id=appeal.ai_ticket_id,
        qc_reason=appeal.qc_reason,
        qc_evidence=appeal.qc_evidence,
        qc_ticket_id=appeal.qc_ticket_id,
        qc_reference_value=appeal.qc_reference_value,
        qc_extracted_value=appeal.qc_extracted_value,
        qc_new_error_code=appeal.qc_new_error_code,
        qc_risk_base=getattr(appeal, "qc_risk_base", None),
        appeal_kind=getattr(appeal, "appeal_kind", "remove"),
        add_source=getattr(appeal, "add_source", None),
        requested_by_username=appeal.requested_by_username,
        requested_at=appeal.requested_at,
        tl_qc_status=appeal.tl_qc_status,
        tl_qc_username=appeal.tl_qc_username,
        tl_qc_reviewed_at=appeal.tl_qc_reviewed_at,
        approval_status=appeal.approval_status,
        reviewed_by_username=appeal.reviewed_by_username,
        reviewed_at=appeal.reviewed_at,
        tl_qc_comment=getattr(appeal, "tl_qc_comment", None),
        review_comment=getattr(appeal, "review_comment", None),
    )


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


@router.post("/error_code_appeal", response_model=ErrorCodeAppealInfo)
def submit_error_code_appeal(
    result_id: str = Form(...),
    error_code: str = Form(...),
    # Optional: free-floating LLM error codes have no SC_CL item_code, yet every
    # row is manual-checkable now. FastAPI treats an empty required Form field as
    # "missing", so default to "" instead of Form(...).
    item_code: str = Form(""),
    ai_sumber: str = Form(None),
    ai_risk_base: str = Form(None),
    ai_details_error: str = Form(None),
    ai_reason: str = Form(None),
    ai_evidence: str = Form(None),
    ai_ticket_id: str = Form(None),
    qc_reason: str = Form(...),
    qc_evidence: str = Form(None),
    qc_ticket_id: str = Form(None),
    qc_reference_value: str = Form(None),
    qc_extracted_value: str = Form(None),
    qc_new_error_code: str = Form(None),
    # QC-edited Risk Base override (empty => keep the master-catalog default).
    qc_risk_base: str = Form(None),
    appeal_kind: str = Form("remove"),
    # For appeal_kind='add' only: which source the new error belongs to.
    add_source: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_qc_user),
):
    result = _validate_result(db, result_id)
    ensure_qc_assigned_to_result(db, current_user, result)

    item_code = (item_code or "").strip()
    # Every Error Code row is manual-checkable. A 'remove' banding drops the error
    # (flips the scorecard item / verification field); a 'change' banding relabels
    # the code to qc_new_error_code (deduction kept only if the new code is
    # deduction-bearing — see compliance.error_codes.DEDUCTION_BEARING_CODES); an
    # 'add' banding proposes a NEW error code attached to an existing item/field
    # (source 'others' is display-only).
    kind = (appeal_kind or "remove").strip().lower()
    if kind not in ("remove", "change", "add"):
        kind = "remove"
    new_code = (qc_new_error_code or "").strip() or None
    if kind == "change" and not new_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New Error Code wajib diisi untuk banding 'Ubah Error Code'",
        )
    src = (add_source or "").strip().lower() or None
    qc_ref = (qc_reference_value or "").strip() or None
    qc_ext = (qc_extracted_value or "").strip() or None
    if kind == "add":
        if src not in _VALID_ADD_SOURCES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Sumber error (add_source) tidak valid",
            )
        if (error_code or "").strip().upper() not in _MASTER_CODES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Error Code harus dari katalog master (error_reasons)",
            )
        if src != "others" and not item_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Item/field yang ditandai (item_code) wajib untuk sumber ini",
            )
        if src in ("cashline_data", "card_holder") and (not qc_ref or not qc_ext):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nilai referensi & ekstraksi wajib untuk banding verifikasi",
            )
    else:
        src = None  # add_source only applies to 'add'
    qc_reason = (qc_reason or "").strip()
    if not qc_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alasan perubahan wajib diisi",
        )

    # Block a new appeal while the latest one for this row is still in-flight (not
    # yet finally decided). A finally-rejected appeal — TL QC rejected, or SPQ Head
    # rejected — may be re-appealed.
    existing = crud.error_code_appeals_for_result(db, result_id)
    latest = crud.latest_appeal_for_row(existing, error_code, item_code)
    if latest is not None and _appeal_active(latest):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sudah ada banding aktif untuk error code ini",
        )

    appeal = crud.create_error_code_appeal(
        db,
        result_id=result_id,
        error_code=error_code,
        item_code=item_code,
        ai_sumber=ai_sumber,
        ai_risk_base=ai_risk_base,
        ai_details_error=ai_details_error,
        ai_reason=ai_reason,
        ai_evidence=ai_evidence,
        ai_ticket_id=ai_ticket_id,
        qc_reason=qc_reason,
        qc_evidence=(qc_evidence or "").strip() or None,
        qc_ticket_id=(qc_ticket_id or "").strip() or None,
        qc_reference_value=qc_ref,
        qc_extracted_value=qc_ext,
        qc_new_error_code=new_code,
        qc_risk_base=(qc_risk_base or "").strip().upper() or None,
        appeal_kind=kind,
        add_source=src,
        username=current_user.username,
    )
    return _appeal_info(appeal)


@router.post("/error_code_appeal/{appeal_id}/tl_review", response_model=ErrorCodeAppealInfo)
def tl_review_error_code_appeal(
    appeal_id: int,
    decision: str = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_team_leader_qc_user),
):
    """Team Leader QC decision (Checker): 'approve'/'reject' are FINAL (banding
    applied/ditolak tanpa SPQ Head), 'escalate' meneruskan ke SPQ Head. ``comment``
    wajib diisi saat 'reject'."""
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
            detail="Komentar wajib diisi saat menolak banding",
        )
    appeal = crud.tl_review_error_code_appeal(
        db, appeal_id=appeal_id, decision=decision, reviewer_username=current_user.username,
        comment=comment,
    )
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Banding tidak ditemukan")
    return _appeal_info(appeal)


@router.post("/error_code_appeal/{appeal_id}/review", response_model=ErrorCodeAppealInfo)
def review_error_code_appeal(
    appeal_id: int,
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
            detail="Komentar wajib diisi saat menolak banding",
        )

    # Tiered flow: SPQ Head may only decide banding that Team Leader QC ESCALATED.
    existing = crud.get_error_code_appeal(db, appeal_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Banding tidak ditemukan")
    if getattr(existing, "tl_qc_status", "pending") != "escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Banding ini belum diteruskan (escalate) oleh Team Leader QC ke SPQ Head",
        )

    appeal = crud.review_error_code_appeal(
        db,
        appeal_id=appeal_id,
        decision=decision,
        reviewer_username=current_user.username,
        comment=comment,
    )
    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Banding tidak ditemukan",
        )
    return _appeal_info(appeal)
