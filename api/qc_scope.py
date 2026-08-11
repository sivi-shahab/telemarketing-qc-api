"""QC ticket-assignment scoping helpers.

A QC (role ``qc``) may only see and act on tickets a Team Leader QC has assigned to
them. These helpers translate a result -> its ticket id (the customer-id prefix of
the source filenames) and enforce the assignment for QC callers. Non-QC roles are
gated by their own role dependencies and pass through untouched.
"""
from fastapi import HTTPException, status

from db import crud


def ticket_id_for_result(result) -> str | None:
    """The customer/ticket id (prefix before the first ``_``) of a result's first
    source filename, e.g. ``181001bWvi_2026...pdf`` -> ``181001bWvi``."""
    sf = getattr(result, "source_files", None) or []
    if sf and isinstance(sf[0], str) and sf[0]:
        return sf[0].split("_", 1)[0]
    return None


def ensure_qc_assigned_to_result(db, current_user, result) -> None:
    """Raise 403 if a ``qc`` user acts on a ticket not assigned to them. No-op for
    every other role (they are already gated by their own dependency)."""
    if getattr(current_user, "role", None) != "qc":
        return
    ticket_id = ticket_id_for_result(result)
    assigned = crud.qc_username_for_ticket(db, ticket_id) if ticket_id else None
    me = (getattr(current_user, "username", "") or "").strip().casefold()
    if not assigned or assigned.strip().casefold() != me:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini tidak di-assign kepada Anda",
        )
