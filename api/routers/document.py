import io
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_document_uploader_user,
    get_document_viewer_user,
    get_minio,
    get_settings,
)
from api.qc_scope import ensure_can_view_result
from api.permissions import DOCUMENT_VERIFICATION_TABLE
from api.rbac import has_perm
from qc_core.compliance.documents import (
    DOCUMENT_TYPES,
    card_holder_bands_apply,
    card_holder_doc_types,
)
from qc_core.compliance.reference_data import get_credit_limit, npwp_required_by_limit
from qc_core.compliance.stats_aggregate import _normalized_json
from qc_core.db import crud

router = APIRouter(dependencies=[Depends(get_current_user)])

ALLOWED_EXT = {".pdf"}
_EXT_MIME = {
    ".pdf": "application/pdf",
}


def _validate_result(db: Session, result_id: str):
    try:
        result = crud.get_result(db, result_id)
    except (ValueError, Exception):  # invalid UUID, etc.
        result = None
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Result tidak ditemukan"
        )
    return result


@router.post("/upload_document")
def upload_document(
    result_id: str = Form(...),
    ktp: UploadFile | None = File(None),
    kk: UploadFile | None = File(None),
    npwp: UploadFile | None = File(None),
    cover_buku_tabungan: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_document_uploader_user),
):
    result = _validate_result(db, result_id)

    # Once-only PER DOCUMENT TYPE. A ticket can need two different documents from two
    # different triggers (e.g. KTP for a TMS address change + KK because
    # nama_ibu_kandung landed in the 80-89% band), and they may be uploaded in
    # separate visits — but the same type is never uploaded twice.
    already = crud.result_document_types(db, result_id)

    uploads = {
        "ktp": ktp,
        "kk": kk,
        "npwp": npwp,
        "cover_buku_tabungan": cover_buku_tabungan,
    }
    # Keep only non-empty files (a file with a filename).
    chosen = {k: f for k, f in uploads.items() if f is not None and f.filename}
    if not chosen:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimal satu file dokumen diperlukan",
        )
    dup = [dt for dt in chosen if dt in already]
    if dup:
        labels = ", ".join(DOCUMENT_TYPES.get(d, {}).get("label", d) for d in dup)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dokumen {labels} untuk result ini sudah pernah diunggah",
        )

    # Only allow document types that match the TMS data changes for this result
    # (server-side enforcement; the dashboard already hides disallowed slots). The
    # cid is the customer/ticket prefix of the first source filename.
    source_files = result.source_files or []
    cid = source_files[0].split("_", 1)[0] if source_files and isinstance(source_files[0], str) else None
    flags = crud.get_tms_cashline_change_flags(db, [cid]).get(cid or "", {}) if cid else {}
    allowed_types = set(crud.allowed_doc_types_from_flags(flags))
    # A disbursement limit (CUST_CRLIMIT) >= Rp 50 juta requires an NPWP, so allow it
    # even without a TMS NPWP change flag (mirrors the Results upload trigger).
    if cid and npwp_required_by_limit(get_credit_limit(cid, db)):
        allowed_types.add("npwp")
    # Card-holder similarity bands (Fase #5) allow their own document type: KK when
    # nama_ibu_kandung scored 80-89%, KTP when tanggal_lahir scored 87,5-99%.
    #
    # Dibaca dari evaluasi yang SUDAH dinormalkan (1 September 2026), sama dengan
    # ``_missing_docs_map`` dan kolom Document di Results. Dengan angka mentah LLM
    # gerbang ini bisa menolak (422) dokumen yang justru diminta sistem: pada
    # 020532VF8Y band ternormalisasi meminta KK dan tiketnya PENDING, tetapi angka
    # mentahnya tidak meminta apa-apa sehingga slotnya tertutup dan tiket itu tidak
    # punya cara untuk dibereskan.
    if card_holder_bands_apply(result.uploaded_at):
        data = crud.get_result_data(db, result_id)
        allowed_types.update(
            card_holder_doc_types(_normalized_json(getattr(data, "result_json", None)))
        )
    bad = [dt for dt in chosen if dt not in allowed_types]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Jenis dokumen {bad} tidak sesuai perubahan data untuk result ini",
        )

    # Validate extensions before storing anything.
    for doc_type, f in chosen.items():
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"File '{f.filename}' bukan PDF — hanya file PDF yang diterima",
            )

    settings = get_settings()
    client = get_minio()
    created = []
    for doc_type, f in chosen.items():
        ext = os.path.splitext(f.filename)[1].lower()
        data = f.file.read()
        object_name = f"{result_id}/{doc_type}{ext}"
        mime = f.content_type or _EXT_MIME.get(ext, "application/octet-stream")
        client.put_object(
            settings.minio_bucket_documents,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=mime,
        )
        doc = crud.create_document(
            db,
            result_id=result_id,
            doc_type=doc_type,
            filename=f.filename,
            object_path=object_name,
            mime_type=mime,
        )
        created.append({"doc_type": doc_type, "status": doc.status})

    from api.celery_client import celery_app

    celery_app.send_task(
        "worker.tasks.process_document.process_document", args=[result_id]
    )

    return {"result_id": result_id, "documents": created}


@router.get("/documents/{result_id}")
def list_documents(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_document_viewer_user),
):
    result = _validate_result(db, result_id)
    # Every role may view documents; the scope is the TICKET, not the role.
    ensure_can_view_result(db, current_user, result)
    # Tabel perbandingan (OCR vs acuan TMS/Ascend) adalah penilaian QC, bukan
    # dokumennya. Role tanpa capability itu tetap menerima dokumennya, tetapi
    # ``ocr_json``/``error_message`` DIBUANG di sini — menyembunyikannya di frontend
    # saja tidak cukup, datanya tetap terkirim dan terbaca di respons jaringan.
    may_see_verification = has_perm(db, current_user, DOCUMENT_VERIFICATION_TABLE)
    docs = crud.list_documents(db, result_id)
    return {
        "can_view_verification": may_see_verification,
        "documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "label": DOCUMENT_TYPES.get(d.doc_type, {}).get("label", d.doc_type),
                "filename": d.filename,
                "mime_type": d.mime_type,
                "status": d.status,
                "ocr_json": d.ocr_json if may_see_verification else None,
                "error_message": d.error_message if may_see_verification else None,
                "created_at": d.created_at,
                "completed_at": d.completed_at,
            }
            for d in docs
        ],
    }


@router.get("/document_file/{document_id}")
def document_file(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_document_viewer_user),
):
    doc = crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dokumen tidak ditemukan"
        )
    # Same ticket scope as /documents — a document id alone must not bypass it.
    ensure_can_view_result(db, current_user, _validate_result(db, str(doc.result_id)))

    settings = get_settings()
    client = get_minio()
    try:
        response = client.get_object(settings.minio_bucket_documents, doc.object_path)
        data = response.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File dokumen tidak ditemukan di storage",
        )
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

    return StreamingResponse(
        io.BytesIO(data),
        media_type=doc.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{doc.filename or doc.object_path}"'},
    )
