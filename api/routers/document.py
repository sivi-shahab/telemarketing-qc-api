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
from compliance.documents import DOCUMENT_TYPES
from compliance.reference_data import get_credit_limit, npwp_required_by_limit
from db import crud

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

    # Enforce once-only upload per result.
    if crud.result_has_documents(db, result_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dokumen untuk result ini sudah pernah diunggah",
        )

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
    _validate_result(db, result_id)
    docs = crud.list_documents(db, result_id)
    return {
        "documents": [
            {
                "id": d.id,
                "doc_type": d.doc_type,
                "label": DOCUMENT_TYPES.get(d.doc_type, {}).get("label", d.doc_type),
                "filename": d.filename,
                "mime_type": d.mime_type,
                "status": d.status,
                "ocr_json": d.ocr_json,
                "error_message": d.error_message,
                "created_at": d.created_at,
                "completed_at": d.completed_at,
            }
            for d in docs
        ]
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
