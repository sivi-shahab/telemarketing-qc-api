"""QC ticket assignment (Team Leader QC assigns a ticket to a QC).

One ticket -> one QC (reassignable). Managed by Team Leader QC (and SPQ Head). A QC
is then scoped to only their assigned tickets for Results / Statistics / appeals.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import QC_ASSIGNMENT_WRITE
from api.qc_scope import scoped_customer_ids
from api.rbac import require
from db import crud
from db.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])


def _assignment_dict(a) -> dict:
    return {
        "ticket_id": a.ticket_id,
        "qc_username": a.qc_username,
        "assigned_by_username": a.assigned_by_username,
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
    }


def _ensure_ticket_in_scope(db: Session, current_user, ticket_id: str) -> None:
    """403 bila ``ticket_id`` di luar cakupan pemanggil.

    Assignment memakai ticket id (prefix customer), sedangkan cakupan role sudah
    dinyatakan sebagai daftar ticket id yang sama oleh ``scoped_customer_ids`` —
    termasuk pembatasan CAMPAIGN. ``None`` = tanpa batas (SPQ Head / TL QC tanpa tag).
    """
    allowed = scoped_customer_ids(db, current_user)
    if allowed is None:
        return
    if (ticket_id or "").strip() not in set(allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini di luar campaign yang menjadi cakupan Anda",
        )


@router.get("/qc_assignment/qc_users")
def list_qc_users(
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """The QC users a ticket can be assigned to (role == qc, active)."""
    rows = (
        db.query(User)
        .filter(User.role == "qc", User.is_active == True)  # noqa: E712
        .order_by(User.name, User.username)
        .all()
    )
    return [{"username": u.username, "name": u.name} for u in rows]


@router.get("/qc_assignments")
def list_assignments(
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Ticket -> QC assignments (newest first), DALAM CAKUPAN pemanggil.

    Dulu selalu seluruh tabel: seorang pengawas yang dipersempit ke satu campaign
    tetap membaca daftar ticket id campaign lain dari sini, padahal menu Results-nya
    sudah kosong."""
    allowed = scoped_customer_ids(db, current_user)
    rows = crud.list_qc_assignments(db)
    if allowed is not None:
        allowed_set = set(allowed)
        rows = [a for a in rows if (a.ticket_id or "").strip() in allowed_set]
    return [_assignment_dict(a) for a in rows]


@router.post("/qc_assignment")
def assign_ticket(
    ticket_id: str = Form(...),
    qc_username: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Assign (or reassign) a ticket to a QC user."""
    ticket_id = (ticket_id or "").strip()
    qc_username = (qc_username or "").strip()
    if not ticket_id or not qc_username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ticket_id dan qc_username wajib diisi")
    _ensure_ticket_in_scope(db, current_user, ticket_id)
    qc = db.query(User).filter(User.username == qc_username, User.role == "qc").first()
    if qc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User QC tidak ditemukan")
    a = crud.assign_ticket_to_qc(db, ticket_id, qc_username, assigned_by_username=current_user.username)
    return _assignment_dict(a)


@router.delete("/qc_assignment/{ticket_id}")
def remove_assignment(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Unassign a ticket (QC then no longer sees it)."""
    _ensure_ticket_in_scope(db, current_user, ticket_id)
    removed = crud.unassign_ticket(db, ticket_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment tidak ditemukan")
    return {"ticket_id": ticket_id.strip(), "removed": True}
