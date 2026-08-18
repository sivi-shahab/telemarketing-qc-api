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
)
from api.schemas.sales_database import (
    RosterResponse,
    RosterRow,
    SalesDatabaseItem,
    SalesDatabaseListResponse,
    SalesDatabaseUploadResponse,
)
from db import crud
from api.permissions import ADMIN_SALES_DATABASE_WRITE
from api.rbac import require

router = APIRouter(dependencies=[Depends(require(ADMIN_SALES_DATABASE_WRITE))])

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


@router.get("/sales_database/roster", response_model=RosterResponse)
def sales_database_roster(db: Session = Depends(get_db)):
    """Isi roster Sales Database yang sedang aktif.

    Sebelum ini isi roster tidak pernah bisa dilihat dari dashboard — hanya daftar
    BERKAS-nya. Padahal kolom ``Dedicated`` di dalamnya menentukan campaign tiap
    orang, dan karenanya menentukan tiket siapa yang mereka lihat. Tanpa tampilan
    ini, salah isi kolom tersebut baru ketahuan saat ada yang mengeluh.

    ``has_account`` menandai NIP yang sudah punya akun login, sehingga terlihat siapa
    saja di roster yang belum bisa masuk ke dashboard.
    """
    from sales_lookup import active_sales_map
    from db.models import User

    row = crud.get_active_sales_database(db)
    mapping = active_sales_map(db)

    known = {
        (u.username or "").strip().casefold()
        for u in db.query(User.username).all()
        if (u.username or "").strip()
    }

    rows = []
    campaigns = set()
    for uid, e in mapping.items():
        ded = (e.get("dedicated") or "").strip()
        if ded:
            campaigns.add(ded.casefold())
        nip = (e.get("nip_baru") or "").strip()
        join = e.get("join_date")
        rows.append(RosterRow(
            user_id=uid,
            nip_baru=nip or None,
            name=e.get("name"),
            dedicated=ded or None,
            nip_tl=e.get("nip_tl"),
            team_leader=e.get("team_leader"),
            nip_am=e.get("nip_am"),
            area_manager=e.get("area_manager"),
            join_date=join.isoformat() if join else None,
            has_account=bool(nip) and nip.casefold() in known,
        ))
    rows.sort(key=lambda r: ((r.dedicated or "").casefold(), (r.name or "").casefold()))
    return RosterResponse(
        filename=row.filename if row else None,
        total=len(rows),
        campaigns=sorted(campaigns),
        rows=rows,
    )
