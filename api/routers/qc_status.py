from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_manual_status_setter_user,
)
from api.qc_scope import ensure_can_view_result
from api.schemas.result import QcStatusEventListResponse, QcStatusRequestInfo
from qc_core.db import crud
from api.permissions import (
    MANUAL_STATUS_DIRECT,
    MANUAL_STATUS_REVIEW_SPQ,
    MANUAL_STATUS_REVIEW_TL,
)
from api.rbac import has_perm, require
from qc_core.compliance.stats_aggregate import ai_status_for_result, manual_status_of

router = APIRouter(dependencies=[Depends(get_current_user)])

# Vonis human (Manual Status), sejajar dengan AI Status.
#   PASS = Qualified · FAIL = Not Qualified · PENDING = belum bisa diputuskan.
VALID_STATUS = {"PASS", "FAIL", "PENDING"}
def _direct_origin(db, user) -> str:
    """Penanda asal vonis Manual Status.

    "qc"         -> usulan, harus lewat hierarki approval;
    "tl_direct"  -> ditetapkan reviewer tahap Team Leader QC, final seketika;
    "spq_direct" -> ditetapkan reviewer tahap SPQ Head, final seketika.

    Ditentukan dari capability, bukan nama role, supaya role buatan operator yang
    diberi MANUAL_STATUS_DIRECT ikut berlaku. Tahapnya diambil dari capability
    review yang dipegang: pemegang tahap TL dicatat sebagai tl_direct.
    """
    if not has_perm(db, user, MANUAL_STATUS_DIRECT):
        return "qc"
    return "tl_direct" if has_perm(db, user, MANUAL_STATUS_REVIEW_TL) else "spq_direct"


def _confirms_ai_status(db: Session, result, existing, requested_status: str) -> bool:
    """True bila usulan ini hanya MEMBENARKAN penilaian mesin, sehingga tidak perlu
    approval hierarki (permintaan 10 Agustus 2026).

    Dua syarat, keduanya wajib:

    * tiket ini BELUM pernah punya vonis human final (tombolnya masih "Set", bukan
      "Ubah") — usulan yang mengUBAH vonis sebelumnya tetap lewat alur banding;
    * vonis yang diajukan SAMA dengan AI Status tiket itu.

    Kalau QC memilih status yang BERBEDA dari AI Status, tidak ada yang berubah:
    usulannya tetap berjalan QC -> TL QC -> SPQ Head seperti sekarang.
    """
    if manual_status_of(existing) is not None:
        return False
    return requested_status == ai_status_for_result(db, result)
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
    current_user=Depends(get_manual_status_setter_user),
):
    """Tetapkan Manual Status (vonis human) untuk sebuah tiket.

    - tanpa MANUAL_STATUS_DIRECT -> USULAN, berjalan lewat hierarki
      QC -> TL QC -> SPQ Head; KECUALI penetapan pertama yang nilainya sama dengan
      AI Status, yang final saat itu juga (lihat ``_confirms_ai_status``);
    - dengan MANUAL_STATUS_DIRECT -> ditetapkan LANGSUNG, final saat disimpan
      (tanpa approval), menggantikan usulan QC yang masih menunggu.

    Role ber-cakupan ``qc_assigned`` hanya boleh menyentuh tiket yang di-assign
    kepadanya.
    """
    result = _validate_result(db, result_id)
    # Cakupan TIKET, bukan hanya assignment: ``ensure_can_view_result`` menegakkan
    # keduanya sekaligus (campaign role + assignment untuk cakupan ``qc_assigned``).
    # Versi lama hanya memeriksa assignment, sehingga pemegang MANUAL_STATUS_DIRECT
    # yang dipersempit ke satu campaign tetap bisa memvonis tiket campaign lain —
    # dan vonis itu final saat itu juga.
    ensure_can_view_result(db, current_user, result)

    requested_status = (requested_status or "").strip().upper()
    if requested_status not in VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status harus PASS, FAIL, atau PENDING",
        )
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alasan perubahan status wajib diisi",
        )

    origin = _direct_origin(db, current_user)
    # Penetapan PERTAMA yang nilainya SAMA dengan AI Status tidak mengubah apa pun —
    # QC hanya membenarkan penilaian mesin — jadi tidak perlu approval hierarki.
    if origin == "qc" and _confirms_ai_status(
        db, result, crud.get_qc_status_request(db, result_id), requested_status
    ):
        origin = "qc_confirm"
    req = crud.upsert_qc_status_request(
        db,
        result_id=result_id,
        requested_status=requested_status,
        reason=reason,
        username=current_user.username,
        role=current_user.role,
        origin=origin,
    )
    # TL QC / SPQ Head tidak butuh approval — vonisnya berlaku saat itu juga.
    if origin != "qc":
        req = crud.finalize_qc_status_request(
            db, result_id=result_id, reviewer_username=current_user.username
        )
    return req


@router.post("/qc_status_request/{result_id}/tl_review", response_model=QcStatusRequestInfo)
def tl_review_qc_status_request(
    result_id: str,
    decision: str = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(MANUAL_STATUS_REVIEW_TL)),
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
    ensure_can_view_result(db, current_user, _validate_result(db, result_id))
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
    current_user=Depends(require(MANUAL_STATUS_REVIEW_SPQ)),
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

    ensure_can_view_result(db, current_user, _validate_result(db, result_id))

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


@router.get("/qc_status_events/{result_id}", response_model=QcStatusEventListResponse)
def list_qc_status_events(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Riwayat perubahan Manual Status satu tiket (terlama dulu).

    Cakupannya mengikuti tiket, bukan role: siapa pun yang boleh melihat tiket itu
    boleh melihat riwayatnya (``ensure_can_view_result``, sama seperti dokumen)."""
    result = _validate_result(db, result_id)
    ensure_can_view_result(db, current_user, result)
    return {
        "result_id": str(result_id),
        "events": crud.qc_status_events_for_result(db, result_id),
    }
