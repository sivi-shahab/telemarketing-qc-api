"""Upload Database Sales — an SPQ-Head-only XLSX upload.

The raw .xlsx file is archived in the ``sales-database`` MinIO bucket and one
row per upload is recorded in ``sales_databases``. Uploading a new file flips
every previous row to inactive, so only the newest database is active. The
dashboard "Database Sales" table lists filename / status / created / uploader.
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
from api.schemas.sales_database import (
    SalesDatabaseItem,
    SalesDatabaseListResponse,
    SalesDatabaseUploadResponse,
)
from db import crud

router = APIRouter(dependencies=[Depends(get_spq_head_user)])

_XLSX_EXT = ".xlsx"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/upload_sales_database", response_model=SalesDatabaseUploadResponse)
def upload_sales_database(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload a sales database (.xlsx). Makes it the only active database."""
    if not (file.filename or "").lower().endswith(_XLSX_EXT):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File harus berformat .xlsx",
        )

    data = file.file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File kosong",
        )

    # Archive the raw file to MinIO first (unique folder so filenames never clash),
    # then record the DB row — which flips previous databases to inactive.
    settings = get_settings()
    client = get_minio()
    object_name = f"{uuid.uuid4().hex}/{file.filename}"
    client.put_object(
        settings.minio_bucket_sales_database,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=_XLSX_MIME,
    )

    row = crud.create_sales_database(
        db,
        filename=file.filename,
        object_path=object_name,
        mime_type=_XLSX_MIME,
        uploaded_by_username=getattr(current_user, "username", None),
        uploaded_by_role=getattr(current_user, "role", None),
    )
    return SalesDatabaseUploadResponse(
        id=row.id, filename=row.filename, is_active=row.is_active
    )


@router.get("/list_sales_databases", response_model=SalesDatabaseListResponse)
def list_sales_databases(db: Session = Depends(get_db)):
    """List uploaded sales databases, newest first (for the dashboard table)."""
    rows = crud.list_sales_databases(db)
    return SalesDatabaseListResponse(
        items=[SalesDatabaseItem.model_validate(r) for r in rows]
    )
