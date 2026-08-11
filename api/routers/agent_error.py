"""Agent Error Summary — for a single result, the agent (from the cashline CSV)
and campaign interest together with that result's error-code table.

Surfaced inside the Results row dropdown untuk SEMUA role, dengan isi yang identik:
  Agent ID    <- tms_cashline ``agent_id`` (matched by result_id == customer ID)
  Agent Name  <- NAME from the active sales database, matched by USER ID == agent_id;
                 falls back to the alphabetic chars of agent_id when unmatched.
  New Joiner  <- "NEW JOINER" when the agent joined < 18 days before submit_time,
                 else "-" (Sales Agent column).
  Campaign    <- evaluation ``campaign_interest`` (bullet list)
  Tanggal     <- cashline CSV ``submit_time``
  Ticket ID / Detail Error / Reason  <- per-row from build_error_code_table().
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_agent_error_summary_user
from sales_lookup import active_sales_map, new_joiner_info
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    apply_added_score_appeals,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    build_error_code_table,
    inject_added_rows,
    relabel_error_table,
)
from db import crud

router = APIRouter(dependencies=[Depends(get_agent_error_summary_user)])


def _customer_id(source_files) -> Optional[str]:
    """Customer/session ID = prefix before the first ``_`` of the first source file."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]
def _agent_name(agent_id: Optional[str]) -> Optional[str]:
    """Agent name = alphabetic characters of the agent id (``rizqi801`` -> ``rizqi``)."""
    if not agent_id:
        return None
    letters = "".join(c for c in agent_id if c.isalpha())
    return letters or None
def _campaign_interest(evaluation: dict) -> list:
    """Campaign interest list; fall back to the per-product INTERESTED flags."""
    ci = evaluation.get("campaign_interest")
    if isinstance(ci, list) and ci:
        return [str(c) for c in ci]
    out = []
    if (evaluation.get("cashline_interest") or {}).get("status") == "INTERESTED":
        out.append("Mega Cashline")
    if (evaluation.get("mus_interest") or {}).get("status") == "INTERESTED":
        out.append("Mega Ultima Shield")
    return out
@router.get("/agent_error_summary/{result_id}")
def agent_error_summary(result_id: str, db: Session = Depends(get_db)):
    """Agent + campaign + error-code rows for one result (used in the Results dropdown)."""
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result tidak ditemukan")
    cid = _customer_id(result.source_files)
    cashline_row = crud.get_tms_cashline_by_result_id(db, cid) if cid else None
    ref = cashline_row or {}
    agent_id = (ref.get("agent_id") or "").strip() or None

    # [FIX] agent_name & nj sebelumnya dipakai di response tanpa pernah di-assign
    # -> NameError setiap kali endpoint ini dipanggil. Keduanya direkonstruksi
    # sesuai docstring modul: NAME dari active sales database (dicocokkan
    # USER ID == agent_id), fallback ke karakter alfabet agent_id kalau tidak
    # ketemu; new_joiner_info() untuk tenure & selisih hari.
    agent_name = None
    if agent_id:
        entry = active_sales_map(db).get(agent_id.casefold())
        if entry:
            agent_name = (entry.get("name") or "").strip() or None
        if not agent_name:
            agent_name = _agent_name(agent_id)
    nj = new_joiner_info(cashline_row, db)

    evaluation = {}
    data = crud.get_result_data(db, result_id)
    if data is not None and isinstance(data.result_json, dict):
        ev = data.result_json.get("evaluation")
        if isinstance(ev, dict):
            evaluation = ev

    # Apply approved bandings so the summary matches the Error Code table: a
    # 'remove' drops the row; a 'change' relabels it and swaps in the QC-approved
    # reason/evidence; an 'add' contributes a NEW row (every source, including
    # 'others'). Mirrors api/routers/transcript.py::_with_error_code_table.
    table = []
    if evaluation:
        appeals = crud.error_code_appeals_for_result(db, result_id)
        approved = approved_appeals_only(appeals)
        # 'add' bandings are handled separately — they must NOT go through the
        # remove/change appliers nor relabel_error_table (which would treat them
        # as removes and drop the very rows they add).
        flip = [a for a in appeals_that_flip(approved) if _appeal_kind(a) != "add"]
        evaluation = apply_approved_appeals(evaluation, flip)
        evaluation = apply_approved_card_holder_appeals(evaluation, flip)
        evaluation = apply_approved_cashline_appeals(evaluation, flip)
        evaluation = apply_approved_critical_compliance_appeals(evaluation, flip)
        evaluation = apply_added_score_appeals(evaluation, added_appeals_only(appeals))
        # Only APPROVED adds are listed here: this summary reports an agent's real
        # errors, so a banding still awaiting Team Leader QC / SPQ Head must not
        # surface its QC reason yet (the detail Error Code table shows pending ones
        # so the reviewers can act on them).
        table = inject_added_rows(build_error_code_table(evaluation), added_appeals_only(appeals))
        table = relabel_error_table(table, [a for a in approved if _appeal_kind(a) != "add"])

    # Collapse rows that repeat the same reason into a single entry (first wins,
    # order preserved) — the summary lists an agent's distinct errors, so an
    # identical value surfacing twice is noise. De-dup on ``details_error``: that
    # is the code description the frontend actually renders in the "Reason" column,
    # so two rows sharing the same code (e.g. B17 for both Tanggal Lahir & Nama Ibu
    # Kandung) collapse into one instead of showing a duplicated reason. Empty
    # values are left as-is.
    errors = []
    seen_details: set = set()
    for row in table:
        details = row.get("details_error") or ""
        if details and details in seen_details:
            continue
        if details:
            seen_details.add(details)
        errors.append(
            {
                "ticket_id": row.get("ticket_id") or "",
                "details_error": details,
                "reason": row.get("reason") or "",
            }
        )

    return {
        "result_id": result_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        # Lama bergabung sebagai TLO, dihitung sampai tanggal submit tiket ini
        # (bukan sampai hari ini) — ex: "3 tahun 1 hari".
        "durasi_bergabung": nj["tenure"] or "-",
        "selisih_hari": nj["diff_days"],  # submit_time - JOIN POSISI, in days (None if unknown)
        "campaign": _campaign_interest(evaluation),
        "tanggal": (ref.get("submit_time") or "").strip() or None,
        "errors": errors,
    }