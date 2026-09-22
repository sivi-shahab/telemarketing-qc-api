"""Menu Collection Results — hasil audit BERBOBOT campaign penagihan.

Terpisah dari ``/list_results`` karena laporannya berformat lain
(``compliance.collection_report``) dan karena seluruh pengayaan menu Results —
TMS submit_time, Ascend, dokumen/SLA, banding, manual check — tidak berlaku untuk
penagihan. Endpoint di sini HANYA membaca ``results`` + ``result_data``.

Reprocess / Delete per tiket memakai endpoint menu Results yang sudah ada
(``POST /reprocess_ticket``, ``DELETE /delete_ticket``) — keduanya bekerja per
ticket id, dan worker sendiri yang membelokkan tiket Collection ke jalur berbobot.
Yang khusus di sini hanya Reprocess All / Delete All, karena pemilihan tiketnya
harus mengikuti filter & cakupan menu INI, bukan ``/list_results`` (yang justru
mengecualikan campaign Collection).

PDF transkrip memakai ``GET /transcript_pdf/{result_id}`` yang sudah ada; untuk
tiket Collection ia menjaga cakupan dengan definisi yang SAMA dengan daftar dan
detail di sini (``api.qc_scope.collection_can_view``).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import ADMIN_TICKET_DELETE, ADMIN_TICKET_REPROCESS, MENU_COLLECTION_RESULTS
from api.qc_scope import collection_view_scope, ensure_can_view_collection_result
from api.rbac import has_perm, require
from api.schemas.reprocess import (
    CollectionFilterRequest,
    ReprocessFilterPreviewResponse,
    ReprocessJobResponse,
)
from api.schemas.result import TicketDeleteAllPreviewResponse, TicketDeleteAllResponse
from compliance.collection_report import (
    collection_list_row,
    is_collection_result_json,
    normalize_stored_report,
)
from compliance.processing_stages import stage_table
from db import crud

router = APIRouter(prefix="/collection", tags=["collection"])


def _view_scope(db, current_user) -> dict:
    """Cakupan daftar Collection login ini; ditolak = ``campaigns`` kosong."""
    return collection_view_scope(db, current_user) or {"campaigns": []}


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
    scope = _view_scope(db, current_user)
    campaigns = scope["campaigns"]
    rows, total = crud.list_collection_results(
        db, **scope, status=status, ai_status=ai_status, ticket_id=ticket_id,
        date_start=_parse_date(date_start), date_end=_parse_date(date_end),
        page=page, limit=limit,
    )
    items = [collection_list_row(r, rj) for r, rj in rows]
    # Penanda server untuk tombol Reprocess/Delete per baris — sama gunanya dengan
    # ``reprocess_active`` di /list_results: menahan tombol setelah refresh.
    busy = crud.active_reprocess_ticket_ids(db, [i["ticket_id"] for i in items if i["ticket_id"]])
    for i in items:
        i["reprocess_active"] = i["ticket_id"] in busy
    return {
        "items": items,
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
    # Campaign dicek SEBELUM cakupan, dan jawabannya 404: tiket Cashline (atau
    # campaign Collection di luar cakupan) memang bukan bagian menu ini, dan 403 di
    # sini akan mengonfirmasi keberadaan tiket yang tidak boleh dilihat.
    if (result.campaign or "").strip().casefold() not in _view_scope(db, current_user)["campaigns"]:
        raise HTTPException(status_code=404, detail="Result ini bukan campaign Collection")
    ensure_can_view_collection_result(db, current_user, result)

    report = None
    if result.status == "done":
        data = crud.get_result_data(db, result_id)
        rj = data.result_json if data else None
        if is_collection_result_json(rj):
            report = normalize_stored_report(rj.get("evaluation"))

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


# Rem, bukan paginasi — kembaran ``reprocess._FILTER_ROW_CAP``: Reprocess All /
# Delete All memang harus melihat SELURUH tiket yang cocok, bukan satu halaman.
_FILTER_ROW_CAP = 1_000_000


def _tickets_for_filter(db, current_user, body: CollectionFilterRequest):
    """Tiket Collection yang cocok dengan filter layar. Mengembalikan
    ``(tids, skipped, campaigns)``.

    Daftarnya datang dari ``crud.list_collection_results`` dengan cakupan yang sama
    dengan ``GET /collection/results``, jadi angka di modal = baris yang tampil di
    daftar. Tiket yang sedang direproses DILEWATI (alasannya sama dengan
    ``stats._tickets_for_filtered_delete`` / ``reprocess._plan_for_filtered``).
    """
    _require_menu(db, current_user)
    rows, _ = crud.list_collection_results(
        db, **_view_scope(db, current_user),
        status=body.status, ai_status=body.ai_status, ticket_id=body.ticket_id,
        date_start=_parse_date(body.date_start), date_end=_parse_date(body.date_end),
        page=1, limit=_FILTER_ROW_CAP,
    )
    by_tid = {}  # ticket id -> campaign, urutan daftar dipertahankan
    for r, _rj in rows:
        first = (r.source_files or [None])[0]
        tid = first.split("_", 1)[0] if isinstance(first, str) and first else None
        if tid and tid not in by_tid:
            by_tid[tid] = (r.campaign or "").strip()
    tids, campaigns = list(by_tid), set(by_tid.values())
    if not tids:
        return [], 0, []
    busy = crud.active_reprocess_ticket_ids(db, tids)
    wanted = [t for t in tids if t not in busy]
    return wanted, len(tids) - len(wanted), sorted(campaigns - {""})


@router.post(
    "/reprocess_filter_preview",
    response_model=ReprocessFilterPreviewResponse,
    dependencies=[Depends(require(ADMIN_TICKET_REPROCESS))],
)
def collection_reprocess_filter_preview(
    body: CollectionFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ongkos Reprocess All menu Collection SEBELUM dijalankan — tanpa efek samping."""
    tids, skipped, _campaigns = _tickets_for_filter(db, current_user, body)
    plan = crud.reprocess_plan_for_tickets(db, tids)
    running = crud.running_reprocess_job(db, scope="campaign")
    return ReprocessFilterPreviewResponse(
        matched=len(plan) + skipped,
        skipped=skipped,
        will_process=len(plan),
        campaigns=sorted({(p.get("campaign") or "").strip() for p in plan} - {""}),
        running_job_id=str(running.id) if running else None,
    )


@router.post(
    "/reprocess_filtered",
    response_model=ReprocessJobResponse,
    dependencies=[Depends(require(ADMIN_TICKET_REPROCESS))],
)
def collection_reprocess_filtered(
    body: CollectionFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Proses ulang SELURUH tiket Collection yang cocok dengan filter. Rencananya
    dihitung ULANG di sini, bukan diambil dari preview."""
    from api.routers.reprocess import start_filtered_job

    tids, _skipped, _campaigns = _tickets_for_filter(db, current_user, body)
    return start_filtered_job(db, current_user, crud.reprocess_plan_for_tickets(db, tids))


@router.post(
    "/delete_tickets_preview",
    response_model=TicketDeleteAllPreviewResponse,
    dependencies=[Depends(require(ADMIN_TICKET_DELETE))],
)
def collection_delete_tickets_preview(
    body: CollectionFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ongkos Delete All menu Collection SEBELUM dijalankan — tanpa efek samping."""
    tids, skipped, campaigns = _tickets_for_filter(db, current_user, body)
    return TicketDeleteAllPreviewResponse(
        matched=len(tids) + skipped,
        skipped=skipped,
        will_delete=len(tids),
        results=crud.results_count_by_ticket_ids(db, tids),
        campaigns=campaigns,
    )


@router.post(
    "/delete_tickets_filtered",
    response_model=TicketDeleteAllResponse,
    dependencies=[Depends(require(ADMIN_TICKET_DELETE))],
)
def collection_delete_tickets_filtered(
    body: CollectionFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Hapus SELURUH entry tiket Collection yang cocok dengan filter. Tidak bisa
    dibatalkan; daftar tiketnya dihitung ULANG di sini, bukan diambil dari preview."""
    tids, _skipped, _campaigns = _tickets_for_filter(db, current_user, body)
    if not tids:
        raise HTTPException(
            status_code=404,
            detail="Tidak ada ticket yang cocok dengan filter (atau semuanya sedang diproses ulang).",
        )
    return TicketDeleteAllResponse(tickets=len(tids), deleted=crud.delete_results_by_ticket_ids(db, tids))
