"""QC ticket assignment (Team Leader QC assigns a ticket to a QC).

One ticket -> one QC (reassignable). Managed by Team Leader QC (and SPQ Head). A QC
is then scoped to only their assigned tickets for Results / Statistics / appeals.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db, get_tl_qc_or_spq_head_user
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


@router.get("/qc_assignment/qc_users")
def list_qc_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_tl_qc_or_spq_head_user),
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
    current_user=Depends(get_tl_qc_or_spq_head_user),
):
    """All ticket -> QC assignments (newest first)."""
    return [_assignment_dict(a) for a in crud.list_qc_assignments(db)]


@router.post("/qc_assignment")
def assign_ticket(
    ticket_id: str = Form(...),
    qc_username: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_tl_qc_or_spq_head_user),
):
    """Assign (or reassign) a ticket to a QC user."""
    ticket_id = (ticket_id or "").strip()
    qc_username = (qc_username or "").strip()
    if not ticket_id or not qc_username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ticket_id dan qc_username wajib diisi")
    qc = db.query(User).filter(User.username == qc_username, User.role == "qc").first()
    if qc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User QC tidak ditemukan")
    a = crud.assign_ticket_to_qc(db, ticket_id, qc_username, assigned_by_username=current_user.username)
    return _assignment_dict(a)


@router.delete("/qc_assignment/{ticket_id}")
def remove_assignment(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_tl_qc_or_spq_head_user),
):
    """Unassign a ticket (QC then no longer sees it)."""
    removed = crud.unassign_ticket(db, ticket_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment tidak ditemukan")
    return {"ticket_id": ticket_id.strip(), "removed": True}
