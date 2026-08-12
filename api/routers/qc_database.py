"""Upload Database QC — an SPQ-Head / Admin-only XLSX upload.

Mirrors Upload Database Sales: the raw .xlsx is archived in the ``qc-database``
MinIO bucket and one row per upload is recorded in ``qc_databases``. Uploading a new
file flips every previous row to inactive, so only the newest database is active.
"""
import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_minio,
    get_settings,
    get_spq_head_user,
)
from api.schemas.qc_database import (
    QcDatabaseItem,
    QcDatabaseListResponse,
    QcDatabaseUploadResponse,
)
from db import crud

router = APIRouter(dependencies=[Depends(get_spq_head_user)])

_XLSX_EXT = ".xlsx"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# DINONAKTIFKAN: setting ``minio_bucket_qc_database`` sudah di-comment di
# api/dependencies.py, jadi endpoint upload ini tidak punya bucket tujuan.
# @router.post("/upload_qc_database", response_model=QcDatabaseUploadResponse)
# def upload_qc_database(
#     file: UploadFile = File(...),
#     db: Session = Depends(get_db),
#     current_user=Depends(get_current_user),
# ):
#     """Upload a QC database (.xlsx). Makes it the only active QC database."""
#     if not (file.filename or "").lower().endswith(_XLSX_EXT):
#         raise HTTPException(
#             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
#             detail="File harus berformat .xlsx",
#         )
#     data = file.file.read()
#     if not data:
#         raise HTTPException(
#             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File kosong"
#         )
#
#     settings = get_settings()
#     client = get_minio()
#     object_name = f"{uuid.uuid4().hex}/{file.filename}"
#     client.put_object(
#         settings.minio_bucket_qc_database,
#         object_name,
#         io.BytesIO(data),
#         length=len(data),
#         content_type=_XLSX_MIME,
#     )
#     row = crud.create_qc_database(
#         db,
#         filename=file.filename,
#         object_path=object_name,
#         mime_type=_XLSX_MIME,
#         uploaded_by_username=getattr(current_user, "username", None),
#         uploaded_by_role=getattr(current_user, "role", None),
#     )
#     return QcDatabaseUploadResponse(id=row.id, filename=row.filename, is_active=row.is_active)


@router.get("/list_qc_databases", response_model=QcDatabaseListResponse)
def list_qc_databases(db: Session = Depends(get_db)):
    """List uploaded QC databases, newest first (for the dashboard table)."""
    rows = crud.list_qc_databases(db)
    return QcDatabaseListResponse(items=[QcDatabaseItem.model_validate(r) for r in rows])
