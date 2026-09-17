"""Stats Collection — statistik audit berbobot campaign penagihan.

Hanya membaca ``results`` + ``result_data`` dalam cakupan Collection login
(``api.qc_scope.collection_view_scope``) — tanpa TMS, Ascend, maupun roster sales.
Siapa yang boleh membuka tampilan ini ditentukan ``api.rbac.stats_views_for``.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.qc_scope import collection_view_scope
from api.rbac import STATS_COLLECTION, stats_views_for
from compliance.collection_stats import aggregate_collection_stats
from db import crud

router = APIRouter(tags=["stats"])


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Tanggal tidak valid: {value}")


@router.get("/stats/collection")
def collection_stats(
    date_start: Optional[str] = Query(None, description="YYYY-MM-DD, tanggal transkrip WIB"),
    date_end: Optional[str] = Query(None, description="YYYY-MM-DD, tanggal transkrip WIB"),
    campaign: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if STATS_COLLECTION not in stats_views_for(db, current_user):
        raise HTTPException(status_code=403, detail="Akses ditolak")
    scope = collection_view_scope(db, current_user)
    if scope is None:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    campaigns = scope["campaigns"]
    if campaign:
        wanted = campaign.strip().casefold()
        campaigns = [c for c in campaigns if c == wanted]
    d_start, d_end = _parse_date(date_start), _parse_date(date_end)
    iso = {k: v for k, v in scope.items() if k != "campaigns"}
    rows = crud.collection_stats_rows(db, campaigns=campaigns, date_start=d_start, date_end=d_end, **iso)
    return {
        **aggregate_collection_stats(rows),
        "campaigns": campaigns,
        "date_start": date_start,
        "date_end": date_end,
    }
