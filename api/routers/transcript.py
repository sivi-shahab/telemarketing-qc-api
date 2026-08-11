import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_evaluation_detail_user,
    get_minio,
    get_qc_or_spq_head_user,
    get_settings,
)
from api.schemas.result import ResultCreateResponse, ResultResponse, TranscriptListResponse
from db import crud
from sales_lookup import new_joiner_info
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    added_appeals_visible,
    apply_added_score_appeals,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    build_error_code_table,
    effective_appeal_status,
    inject_added_rows,
    is_cashline_code,
    override_risk_base_for_new_joiner,
    relabel_error_table,
)
from compliance.scoring import (
    _to_num,
    base_ai_status,
    has_blocking_intolerable_item,
    scorecard_score,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/upload_transcript", response_model=ResultCreateResponse)
def upload_transcript(
    files: list[UploadFile] = File(...),
    campaign: str = Form(...),
    # True (default) = reuse hasil `done` sebelumnya untuk ID ini (clone tanpa LLM);
    # False = paksa proses ulang lewat LLM meski hasil lama ada.
    reuse: bool = Form(True),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimal satu file PDF transkrip diperlukan",
        )

    # Validate every file is a PDF before doing anything.
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"File '{f.filename}' bukan PDF — hanya .pdf yang diterima",
            )

    # Campaign must exist and be active.
    if crud.get_active_campaign(db, campaign) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign '{campaign}' tidak ditemukan atau tidak aktif",
        )

    source_files = [f.filename for f in files]

    # Cek apakah customer ID ini sudah punya hasil `done` sebelumnya (kandidat
    # untuk di-clone). Dipilih dengan tie-break: utamakan yang sudah ada banding,
    # jika tidak ada ambil upload terbaru.
    customer_id = _customer_id_from_files(source_files)
    # Reuse hanya dicari bila mode reuse aktif; mode "proses ulang" (reuse=False)
    # selalu memproses via LLM walau hasil lama ada.
    source = crud.pick_reusable_done_result(db, customer_id) if (reuse and customer_id) else None

    # Setiap upload = row Result baru (supaya muncul sebagai baris tersendiri di
    # tabel Results dengan Transcript Upload = waktu upload sekarang).
    result = crud.create_result(
        db,
        campaign=campaign,
        source_files=source_files,
        num_calls=len(files),
        transcript_path=None,
        uploaded_by_username=getattr(current_user, "username", None),
        uploaded_by_role=getattr(current_user, "role", None),
    )
    result_id = str(result.id)

    # Simpan file transkrip yang diupload ke transcripts/{result_id}/{filename}
    # (agar viewer/download PDF jalan untuk row baru ini).
    settings = get_settings()
    client = get_minio()
    for f in files:
        data = f.file.read()
        object_name = f"{result_id}/{f.filename}"
        client.put_object(
            settings.minio_bucket_transcripts,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type="application/pdf",
        )
    result.transcript_path = f"{result_id}/"
    db.commit()

    if source is not None:
        # Sudah pernah diproses -> clone hasil lama (evaluasi + banding +
        # approval SPQ Head) ke row baru, TANPA proses ulang ke LLM.
        result_json = crud.clone_result_from(db, source, result)
        # Mirror JSON hasil ke bucket results agar konsisten dengan alur worker.
        try:
            payload = json.dumps(result_json).encode("utf-8")
            client.put_object(
                settings.minio_bucket_results,
                f"{result_id}.json",
                io.BytesIO(payload),
                length=len(payload),
                content_type="application/json",
            )
        except Exception:
            pass
        return ResultCreateResponse(result_id=result_id, status="done", reused=True)

    # Belum pernah ada hasil `done` -> proses normal lewat LLM.
    from api.celery_client import celery_app

    celery_app.send_task(
        "worker.tasks.process_transcript.process_transcript", args=[result_id]
    )

    return ResultCreateResponse(result_id=result_id, status="pending")


# Accepted audio extensions -> Content-Type for MinIO storage.
AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
    ".webm": "audio/webm",
    ".amr": "audio/amr",
}


@router.post("/upload_audio", response_model=ResultCreateResponse)
def upload_audio(
    files: list[UploadFile] = File(...),
    campaign: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Template endpoint for audio upload (mirrors ``upload_transcript``).

    Stores the raw audio files in the ``audio`` bucket and creates a ``pending``
    result. NOTE: there is no speech-to-text / processing pipeline yet, so this
    endpoint only persists the upload. Wire the transcription task at the marked
    TODO below once the worker step exists.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimal satu file audio diperlukan",
        )

    # Validate every file is an accepted audio format before doing anything.
    for f in files:
        ext = "." + (f.filename or "").rsplit(".", 1)[-1].lower() if "." in (f.filename or "") else ""
        if ext not in AUDIO_CONTENT_TYPES:
            allowed = ", ".join(sorted(AUDIO_CONTENT_TYPES))
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"File '{f.filename}' bukan audio — hanya {allowed} yang diterima",
            )

    # Campaign must exist and be active.
    if crud.get_active_campaign(db, campaign) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign '{campaign}' tidak ditemukan atau tidak aktif",
        )

    source_files = [f.filename for f in files]
    result = crud.create_result(
        db,
        campaign=campaign,
        source_files=source_files,
        num_calls=len(files),
        transcript_path=None,
        uploaded_by_username=getattr(current_user, "username", None),
        uploaded_by_role=getattr(current_user, "role", None),
    )
    result_id = str(result.id)

    # Upload each audio file to audio/{result_id}/{original_filename}
    settings = get_settings()
    client = get_minio()
    for f in files:
        data = f.file.read()
        ext = "." + f.filename.rsplit(".", 1)[-1].lower()
        object_name = f"{result_id}/{f.filename}"
        client.put_object(
            settings.minio_bucket_audio,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=AUDIO_CONTENT_TYPES.get(ext, "application/octet-stream"),
        )

    # Record the storage prefix.
    result.transcript_path = f"{result_id}/"
    db.commit()

    # TODO: enqueue the audio -> transcript -> evaluation pipeline once it exists,
    # e.g. celery_app.send_task("worker.tasks.process_audio.process_audio", args=[result_id]).
    # The result stays "pending" until that task is implemented.

    return ResultCreateResponse(result_id=result_id, status="pending")


def _customer_id_from_files(source_files):
    """Customer/session ID = prefix before the first ``_`` of the first source file."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]


def _appeal_history_entry(a):
    """Serialize an appeal ORM row into a plain dict for the Error Code table."""
    return {
        "id": a.id,
        "approval_status": a.approval_status,
        "qc_reason": a.qc_reason,
        "qc_evidence": a.qc_evidence,
        "qc_ticket_id": a.qc_ticket_id,
        "qc_reference_value": a.qc_reference_value,
        "qc_extracted_value": a.qc_extracted_value,
        "qc_new_error_code": getattr(a, "qc_new_error_code", None),
        "appeal_kind": getattr(a, "appeal_kind", "remove"),
        "add_source": getattr(a, "add_source", None),
        "ai_sumber": a.ai_sumber,
        "ai_risk_base": a.ai_risk_base,
        "ai_details_error": a.ai_details_error,
        "ai_reason": a.ai_reason,
        "ai_evidence": a.ai_evidence,
        "ai_ticket_id": a.ai_ticket_id,
        "requested_by_username": a.requested_by_username,
        "requested_at": a.requested_at.isoformat() if a.requested_at else None,
        "tl_qc_status": getattr(a, "tl_qc_status", "pending"),
        "tl_qc_username": getattr(a, "tl_qc_username", None),
        "tl_qc_reviewed_at": a.tl_qc_reviewed_at.isoformat() if getattr(a, "tl_qc_reviewed_at", None) else None,
        "tl_qc_comment": getattr(a, "tl_qc_comment", None),
        "reviewed_by_username": a.reviewed_by_username,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "review_comment": getattr(a, "review_comment", None),
    }


def _with_error_code_table(result_json, is_new_joiner: bool = False, appeals=None):
    """Return a shallow copy of result_json with evaluation.error_code_table
    computed by the shared single-source-of-truth builder (so the dashboard
    renders the same grouped table the XLSX export uses).

    For a new-joiner submission, each row's Risk Base ``L``/``M`` is softened to
    ``N`` (the qc / SPQ Head Error Code table reads ``risk_base``).

    ``appeals`` (Error Code banding rows for this result) drive two things:
    approved appeals are applied to the evaluation first (flipping the linked
    scorecard item to SESUAI, so the appealed error row disappears and the score
    lifts), and each remaining row is annotated with its latest appeal status +
    full history for the QC "Manual Check" / SPQ Head "Review Banding" columns."""
    if not isinstance(result_json, dict):
        return result_json
    evaluation = result_json.get("evaluation")
    if not isinstance(evaluation, dict):
        return result_json
    appeals = appeals or []
    approved = approved_appeals_only(appeals)
    # 'change' bandings to a deduction-bearing code keep their deduction (relabel
    # only); every other approved remove/change banding flips the item/field to lift
    # the score. 'add' bandings are handled separately (they lower the score).
    flip = [a for a in appeals_that_flip(approved) if _appeal_kind(a) != "add"]
    evaluation = apply_approved_appeals(evaluation, flip)
    evaluation = apply_approved_card_holder_appeals(evaluation, flip)
    evaluation = apply_approved_cashline_appeals(evaluation, flip)
    evaluation = apply_approved_critical_compliance_appeals(evaluation, flip)
    # 'add' bandings: attach a NEW error to an existing item/field and LOWER the score
    # (source 'others' is display-only, injected into the table below).
    added = added_appeals_only(appeals)
    evaluation = apply_added_score_appeals(evaluation, added)
    # Recompute the aggregate score fields from the appeal-adjusted evaluation so the
    # detail response is self-consistent (the apply_* helpers only lift the frozen
    # verification/critical penalties; ai_score_phase_2/phase_3/ai_status stay at the
    # original LLM values otherwise). Mirrors api/routers/stats.py::list_results.
    phase2 = scorecard_score(evaluation)
    if phase2 is not None:
        verif = _to_num(evaluation.get("ai_score_verification")) or 0
        critical = _to_num(evaluation.get("ai_score_critical_compliance_check")) or 0
        phase3 = phase2 + verif + critical
        status_val = base_ai_status(evaluation)
        if status_val == "PASS" and has_blocking_intolerable_item(evaluation):
            status_val = "FAIL"
        evaluation = {
            **evaluation,
            "ai_score_phase_2": phase2,
            "ai_score_phase_3": int(phase3) if phase3 == int(phase3) else phase3,
            "ai_status": status_val,
        }
    table = build_error_code_table(evaluation)
    # Inject display rows for 'add' bandings (pending awaiting review + approved),
    # keyed by their master code so the annotation below attaches their review state.
    table = inject_added_rows(table, added_appeals_visible(appeals))
    if is_new_joiner:
        table = override_risk_base_for_new_joiner(table)
    table = _annotate_appeals(table, appeals)
    # Relabel/inject/drop rows for approved 'change'/'remove' bandings (after
    # annotation so each row keeps its appeal metadata under the original code).
    table = relabel_error_table(table, [a for a in approved if _appeal_kind(a) != "add"])
    evaluation = {**evaluation, "error_code_table": table}
    return {**result_json, "evaluation": evaluation}


def _annotate_appeals(table, appeals):
    """Attach appeal state to each Error Code row. Every row is manual-checkable
    (banding may REMOVE or CHANGE the code); ``appeal`` carries latest status +
    history for the QC Manual Check / TL QC / SPQ Head columns."""
    # Group appeals by (error_code, item_code), oldest-first (input order).
    by_row = {}
    for a in appeals:
        by_row.setdefault((a.error_code, a.item_code), []).append(a)
    annotated = []
    for row in table:
        item_code = row.get("item_code") or ""
        # Every Error Code row can be manual-checked now.
        row = {**row, "appealable": True}
        matched = by_row.get((row.get("error_code"), item_code))
        if matched:
            latest = matched[-1]
            row["appeal"] = {
                "latest_id": latest.id,
                "latest_status": latest.approval_status,
                "tl_qc_status": getattr(latest, "tl_qc_status", "pending"),
                "tl_qc_username": getattr(latest, "tl_qc_username", None),
                "effective_status": effective_appeal_status(latest),
                "requested_by_username": latest.requested_by_username,
                "history": [_appeal_history_entry(a) for a in matched],
            }
        else:
            row["appeal"] = None
        annotated.append(row)
    return annotated


@router.get("/result/{result_id}", response_model=ResultResponse)
def get_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_evaluation_detail_user),
):
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result tidak ditemukan",
        )

    if result.status == "done":

        data = crud.get_result_data(db, result_id)
        # New-joiner check softens Risk Base L/M -> N in the Error Code table.
        cid = _customer_id_from_files(result.source_files)
        cashline_row = crud.get_tms_cashline_by_result_id(db, cid) if cid else None
        is_new_joiner = new_joiner_info(cashline_row, db)["is_new_joiner"]
        appeals = crud.error_code_appeals_for_result(db, result_id)
        result_json = _with_error_code_table(
            data.result_json if data else None, is_new_joiner, appeals
        )

        return ResultResponse(
            result_id=result_id,
            status=result.status,
            result=result_json,
        )

    if result.status == "failed":
        return ResultResponse(
            result_id=result_id,
            status=result.status,
            error=result.error_message,
        )

    # pending / processing
    return ResultResponse(result_id=result_id, status=result.status)


@router.get("/list_transcripts", response_model=TranscriptListResponse)
def list_transcripts(
    status: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None, description="Filter Approve/Reject: PASS | FAIL"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List every transcript PDF across all tickets (one row per PDF, not per
    ticket). QC / Team Leader QC / SPQ Head / Admin see the main set; QC Support
    sees ONLY its own isolated (complaint) transcripts."""
    role = getattr(current_user, "role", None)
    if role not in ("qc", "team_leader_qc", "qc_support", "spq_head", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")
    # QC Support: isolated set (only its own uploads); everyone else excludes them.
    iso = ({"uploaded_by_role": "qc_support"} if role == "qc_support"
           else {"exclude_uploaded_by_role": "qc_support"})
    items, total = crud.list_transcripts(
        db, status=status, campaign=campaign, ticket_id=ticket_id,
        ai_status=ai_status, page=page, limit=limit, **iso,
    )
    return TranscriptListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/transcript_pdf/{result_id}")
def transcript_pdf(
    result_id: str,
    filename: str = Query(..., description="Nama file PDF transkrip"),
    db: Session = Depends(get_db),
):
    """Stream a single transcript PDF from MinIO for the dashboard PDF viewer.

    The filename must belong to the result's ``source_files`` (guards against
    arbitrary object access / path traversal)."""
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result tidak ditemukan")

    if filename not in (result.source_files or []):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' bukan bagian dari result ini",
        )

    settings = get_settings()
    client = get_minio()
    object_name = f"{result_id}/{filename}"
    try:
        response = client.get_object(settings.minio_bucket_transcripts, object_name)
        data = response.read()
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF tidak ditemukan di storage")
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

    # Source PDFs are generated externally (ReportLab) with /Title = "untitled", which
    # the browser's embedded PDF viewer shows as the document name. Overwrite /Title
    # with the real filename so the viewer shows a meaningful name (works for existing
    # tickets too — no re-upload). Best-effort: on any failure, stream the original.
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(data))
        writer = PdfWriter(clone_from=reader)
        writer.add_metadata({"/Title": filename})
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()
    except Exception:
        pass

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/download_transcript/{transcript_id}")
def download_transcript(
    transcript_id: str,
    db: Session = Depends(get_db),
):
    """Download 1 PDF transkrip asli berdasarkan ID nama file (stem).

    Contoh: ``GET /download_transcript/061058ecB3_20260612171830`` mengunduh
    ``061058ecB3_20260612171830.pdf`` dari MinIO sebagai attachment.
    """
    filename = (
        transcript_id
        if transcript_id.lower().endswith(".pdf")
        else f"{transcript_id}.pdf"
    )

    result = crud.get_result_by_source_file(db, filename)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript '{filename}' tidak ditemukan",
        )

    settings = get_settings()
    client = get_minio()
    object_name = f"{result.id}/{filename}"
    try:
        response = client.get_object(settings.minio_bucket_transcripts, object_name)
        data = response.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF tidak ditemukan di storage",
        )
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
