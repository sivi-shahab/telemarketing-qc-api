from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
)
from api.qc_scope import ensure_can_view_result
from api.schemas.result import ErrorCodeAppealInfo
from qc_core.compliance.error_codes import effective_appeal_status, is_cashline_code
from qc_core.compliance.error_reasons import ERROR_REASONS
from qc_core.db import crud
from api.permissions import (
    ERROR_CODE_APPEAL,
    ERROR_CODE_DIRECT_EDIT,
    ERROR_CODE_REVIEW_SPQ,
    ERROR_CODE_REVIEW_TL,
    MANUAL_STATUS_DIRECT,
)
from api.rbac import has_perm, require

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
        origin=getattr(appeal, "origin", "qc"),
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


def _normalize_appeal_form(
    *,
    error_code: str,
    item_code: str,
    ai_sumber: str,
    ai_risk_base: str,
    ai_details_error: str,
    ai_reason: str,
    ai_evidence: str,
    ai_ticket_id: str,
    qc_reason: str,
    qc_evidence: str,
    qc_ticket_id: str,
    qc_reference_value: str,
    qc_extracted_value: str,
    qc_new_error_code: str,
    qc_risk_base: str,
    appeal_kind: str,
    add_source: str,
) -> dict:
    """Validate + normalize the appeal form fields (shared by QC submit and the
    reviewer DIRECT edit). Returns the kwargs for ``crud.create_error_code_appeal``
    (minus ``result_id``/``origin``/``username``). Raises 422 on invalid input.

    Every Error Code row is manual-checkable: a 'remove' banding drops the error, a
    'change' banding relabels the code to ``qc_new_error_code``, an 'add' banding
    proposes a NEW error attached to an existing item/field (source 'others' is
    display-only)."""
    item_code = (item_code or "").strip()
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
    reason = (qc_reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alasan perubahan wajib diisi",
        )
    return dict(
        error_code=error_code,
        item_code=item_code,
        ai_sumber=ai_sumber,
        ai_risk_base=ai_risk_base,
        ai_details_error=ai_details_error,
        ai_reason=ai_reason,
        ai_evidence=ai_evidence,
        ai_ticket_id=ai_ticket_id,
        qc_reason=reason,
        qc_evidence=(qc_evidence or "").strip() or None,
        qc_ticket_id=(qc_ticket_id or "").strip() or None,
        qc_reference_value=qc_ref,
        qc_extracted_value=qc_ext,
        qc_new_error_code=new_code,
        qc_risk_base=(qc_risk_base or "").strip().upper() or None,
        appeal_kind=kind,
        add_source=src,
    )


def _ensure_no_active_appeal(db: Session, result_id: str, error_code: str, item_code: str):
    """Block a new banding while the latest one for this row is still in-flight (not
    yet finally decided). A finally-approved/rejected banding may be re-appealed. A
    reviewer's DIRECT edit is likewise blocked while a QC appeal is pending — the
    reviewer should decide that appeal via Review Banding instead of racing it."""
    existing = crud.error_code_appeals_for_result(db, result_id)
    latest = crud.latest_appeal_for_row(existing, error_code, item_code)
    if latest is not None and _appeal_active(latest):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sudah ada banding aktif untuk error code ini",
        )


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
    current_user=Depends(require(ERROR_CODE_APPEAL)),
):
    result = _validate_result(db, result_id)
    # Assignment DAN campaign sekaligus — ``ensure_can_view_result`` menegakkan
    # keduanya, jadi cakupan banding sama persis dengan cakupan melihat tiketnya.
    ensure_can_view_result(db, current_user, result)

    fields = _normalize_appeal_form(
        error_code=error_code,
        item_code=item_code,
        ai_sumber=ai_sumber,
        ai_risk_base=ai_risk_base,
        ai_details_error=ai_details_error,
        ai_reason=ai_reason,
        ai_evidence=ai_evidence,
        ai_ticket_id=ai_ticket_id,
        qc_reason=qc_reason,
        qc_evidence=qc_evidence,
        qc_ticket_id=qc_ticket_id,
        qc_reference_value=qc_reference_value,
        qc_extracted_value=qc_extracted_value,
        qc_new_error_code=qc_new_error_code,
        qc_risk_base=qc_risk_base,
        appeal_kind=appeal_kind,
        add_source=add_source,
    )
    _ensure_no_active_appeal(db, result_id, fields["error_code"], fields["item_code"])

    appeal = crud.create_error_code_appeal(
        db, result_id=result_id, origin="qc", username=current_user.username, **fields
    )
    return _appeal_info(appeal)


@router.post("/error_code_appeal/direct", response_model=ErrorCodeAppealInfo)
def direct_error_code_appeal(
    result_id: str = Form(...),
    error_code: str = Form(...),
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
    qc_risk_base: str = Form(None),
    appeal_kind: str = Form("remove"),
    add_source: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(ERROR_CODE_DIRECT_EDIT)),
):
    """DIRECT error-code edit by Team Leader QC / SPQ Head — no approval hierarchy.

    Same remove/change/add semantics and validation as a QC ``/error_code_appeal``,
    but the banding is created already FINALIZED (auto tl-approved) so it applies
    immediately to the score / Error Code table. ``origin`` records who did it
    ('tl_direct' / 'spq_direct'). QC still submits through the tiered review; only
    reviewers may edit directly. Blocked (409) while a QC appeal is pending on the
    same row — use Review Banding for that instead."""
    # Edit langsung berlaku SEKETIKA (auto-approved), jadi cakupan tiketnya wajib
    # ditegakkan di sini: tanpa ini reviewer yang dipersempit ke satu campaign bisa
    # mengubah error code — dan karenanya skor — tiket campaign lain.
    ensure_can_view_result(db, current_user, _validate_result(db, result_id))

    fields = _normalize_appeal_form(
        error_code=error_code,
        item_code=item_code,
        ai_sumber=ai_sumber,
        ai_risk_base=ai_risk_base,
        ai_details_error=ai_details_error,
        ai_reason=ai_reason,
        ai_evidence=ai_evidence,
        ai_ticket_id=ai_ticket_id,
        qc_reason=qc_reason,
        qc_evidence=qc_evidence,
        qc_ticket_id=qc_ticket_id,
        qc_reference_value=qc_reference_value,
        qc_extracted_value=qc_extracted_value,
        qc_new_error_code=qc_new_error_code,
        qc_risk_base=qc_risk_base,
        appeal_kind=appeal_kind,
        add_source=add_source,
    )
    _ensure_no_active_appeal(db, result_id, fields["error_code"], fields["item_code"])

    # Tahap reviewer diambil dari capability, bukan nama role, supaya role buatan
    # operator yang diberi ERROR_CODE_REVIEW_TL tercatat sebagai tl_direct.
    origin = "tl_direct" if has_perm(db, current_user, ERROR_CODE_REVIEW_TL) else "spq_direct"
    appeal = crud.create_error_code_appeal(
        db, result_id=result_id, origin=origin, username=current_user.username, **fields
    )
    # Finalize immediately (no hierarchy): a direct edit IS the approval. Reuse the
    # TL-QC finalize path so effective_appeal_status(appeal) == 'approved' and the
    # apply/relabel pipeline treats it exactly like an approved banding.
    appeal = crud.tl_review_error_code_appeal(
        db,
        appeal_id=appeal.id,
        decision="approve",
        reviewer_username=current_user.username,
        comment=None,
    )
    return _appeal_info(appeal)


def _appeal_in_scope(db: Session, current_user, appeal_id: int):
    """Banding ``appeal_id`` + jaminan pemanggil boleh menyentuh TIKETNYA.

    Endpoint review bekerja dengan ``appeal_id``, bukan ``result_id``, sehingga
    cakupan tiket gampang terlewat: sebelum ini seorang reviewer yang dipersempit ke
    satu campaign tetap bisa approve/reject banding milik campaign lain — cukup
    dengan menebak id banding-nya (integer berurutan). 404 bila banding tidak ada,
    403 bila tiketnya di luar cakupan."""
    appeal = crud.get_error_code_appeal(db, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Banding tidak ditemukan")
    ensure_can_view_result(db, current_user, _validate_result(db, str(appeal.result_id)))
    return appeal


@router.post("/error_code_appeal/{appeal_id}/tl_review", response_model=ErrorCodeAppealInfo)
def tl_review_error_code_appeal(
    appeal_id: int,
    decision: str = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(ERROR_CODE_REVIEW_TL)),
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
    _appeal_in_scope(db, current_user, appeal_id)
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
    current_user=Depends(require(ERROR_CODE_REVIEW_SPQ)),
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
    existing = _appeal_in_scope(db, current_user, appeal_id)
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
