"""Menu Collection Results — hasil audit BERBOBOT campaign penagihan.

Terpisah dari ``/list_results`` karena laporannya berformat lain
(``compliance.collection_report``) dan karena seluruh pengayaan menu Results —
TMS submit_time, Ascend, dokumen/SLA, banding, manual check — tidak berlaku untuk
penagihan. Endpoint di sini HANYA membaca ``results`` + ``result_data``.

PDF transkrip memakai ``GET /transcript_pdf/{result_id}`` yang sudah ada: ia
hanya membaca MinIO dan sudah menjaga cakupan tiket.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import MENU_COLLECTION_RESULTS
from api.qc_scope import ensure_can_view_result
from api.rbac import collection_campaigns_from_env, effective_campaigns_for, has_perm
from compliance.collection_report import (
    collection_list_row,
    is_collection_result_json,
    normalize_weighted_report,
)
from compliance.processing_stages import stage_table
from db import crud

router = APIRouter(prefix="/collection", tags=["collection"])


def _allowed_campaigns(db, current_user) -> list:
    """Campaign Collection yang boleh dilihat: env ∩ cakupan campaign efektif.
    ``None`` dari ``effective_campaigns_for`` = tidak dibatasi."""
    collection = collection_campaigns_from_env()
    scope = effective_campaigns_for(db, current_user)
    if scope is None:
        return sorted(collection)
    return sorted(collection & {c.strip().casefold() for c in scope})


def _require_menu(db, current_user):
    if not has_perm(db, current_user, MENU_COLLECTION_RESULTS):
        raise HTTPException(status_code=403, detail="Akses ditolak")


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Tanggal tidak valid: {value}")


@router.get("/results")
def list_collection_results(
    status: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None, description="PASS | FAIL"),
    ticket_id: Optional[str] = Query(None),
    date_start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_menu(db, current_user)
    campaigns = _allowed_campaigns(db, current_user)
    rows, total = crud.list_collection_results(
        db, campaigns=campaigns, status=status, ai_status=ai_status, ticket_id=ticket_id,
        date_start=_parse_date(date_start), date_end=_parse_date(date_end),
        page=page, limit=limit,
    )
    return {
        "items": [collection_list_row(r, rj) for r, rj in rows],
        "total": total, "page": page, "limit": limit, "campaigns": campaigns,
    }


@router.get("/results/{result_id}")
def get_collection_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_menu(db, current_user)
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result tidak ditemukan")
    ensure_can_view_result(db, current_user, result)
    # 404, bukan 403: tiket Cashline tidak "terlarang" di sini, ia memang bukan
    # bagian menu ini — detailnya ada di menu Results.
    if (result.campaign or "").strip().casefold() not in _allowed_campaigns(db, current_user):
        raise HTTPException(status_code=404, detail="Result ini bukan campaign Collection")

    report = None
    if result.status == "done":
        data = crud.get_result_data(db, result_id)
        rj = data.result_json if data else None
        if is_collection_result_json(rj):
            report = normalize_weighted_report(rj.get("evaluation"))

    iso = lambda dt: dt.isoformat() if dt is not None else None  # noqa: E731
    return {
        "result_id": str(result.id),
        "campaign": result.campaign,
        "status": result.status,
        "source_files": list(result.source_files or []),
        "uploaded_at": iso(result.uploaded_at),
        "completed_at": iso(result.completed_at),
        "processing_sec": result.processing_sec,
        "error": result.error_message if result.status == "failed" else None,
        "current_stage": result.current_stage,
        "stages": stage_table(result.current_stage) if result.status in ("pending", "processing") else [],
        "report": report,
    }
