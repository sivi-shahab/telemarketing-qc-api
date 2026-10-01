"""Menu OCR Gambar: upload gambar, worker menyalin teksnya, riwayat per pengunggah.

Alat mandiri (1 Oktober 2026) — tidak terikat tiket/result. Seluruh router di
belakang ``menu.ocr_image`` (Admin/Demo lewat role, user lain lewat
``OCR_IMAGE_CAMPAIGNS``, lihat ``api.rbac.permissions_for``). Non-admin hanya
melihat baris miliknya; milik orang lain dijawab 404 supaya keberadaannya tidak
bocor.
"""
import io
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api import ocr_image_store as store
from api.ocr_image_normalize import NotAnImage, TooManyPages, normalize
from api.dependencies import get_current_user, get_db, get_minio, get_settings
from api.permissions import ADMIN_LIKE_ROLES, MENU_OCR_IMAGE
from api.rbac import require

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require(MENU_OCR_IMAGE))])

MAX_FILES = 10
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGE_SIZE = 100
OBJECT_PREFIX = "ocr-images/"
TASK_NAME = "worker.tasks.process_ocr_image.process_ocr_image"


def _owner_id(current_user):
    return None if getattr(current_user, "role", None) in ADMIN_LIKE_ROLES else current_user.id


def _is_admin(current_user) -> bool:
    return _owner_id(current_user) is None


def _invalid(detail: str):
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _read_validated(files):
    """Baca, periksa, dan normalkan SEMUA file sebelum apa pun disimpan: satu salah =
    tolak semua. Mengembalikan daftar ``Page`` (TIFF multi-halaman sudah dipecah)."""
    if not files:
        raise _invalid("Pilih minimal satu gambar")
    if len(files) > MAX_FILES:
        raise _invalid(f"Maksimal {MAX_FILES} gambar per upload")
    pages = []
    for f in files:
        name = f.filename or "gambar"
        data = f.file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise _invalid(f"File '{name}' melebihi 10 MB")
        try:
            pages.extend(normalize(data, name, max_pages=MAX_FILES - len(pages)))
        except TooManyPages as exc:
            raise _invalid(
                f"Maksimal {MAX_FILES} gambar per upload "
                f"(termasuk tiap halaman TIFF; total {len(pages) + exc.pages})"
            )
        except NotAnImage:
            raise _invalid(f"File '{name}' bukan gambar yang bisa dibaca")
    return pages


def _iso(dt):
    return dt.isoformat() + "Z" if dt is not None else None


def _summary(row, uploader_name=None, admin=False) -> dict:
    out = {
        "id": str(row.id),
        "batch_id": str(row.batch_id),
        "filename": row.filename,
        "status": row.status,
        "size_bytes": row.size_bytes,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
    }
    if admin:
        out["uploader_name"] = uploader_name
    return out


def _get_or_404(db, image_id, current_user):
    row = store.get_for(db, image_id, owner_id=_owner_id(current_user))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gambar tidak ditemukan")
    return row


def _send(image_id) -> None:
    from api.celery_client import celery_app

    celery_app.send_task(TASK_NAME, args=[str(image_id)])


@router.post("/ocr_images")
def upload_ocr_images(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pages = _read_validated(files)
    settings = get_settings()
    client = get_minio()
    batch_id = uuid.uuid4()
    rows = []
    for page in pages:
        image_id = uuid.uuid4()
        object_path = f"{OBJECT_PREFIX}{image_id}{page.ext}"
        client.put_object(settings.minio_bucket_documents, object_path, io.BytesIO(page.data),
                          length=len(page.data), content_type=page.mime_type)
        rows.append(store.create(db, image_id=image_id, user_id=current_user.id, batch_id=batch_id,
                                 filename=page.filename, object_path=object_path,
                                 mime_type=page.mime_type, size_bytes=len(page.data)))
    for row in rows:
        _send(row.id)
    return {"batch_id": str(batch_id), "items": [_summary(r) for r in rows]}


@router.get("/ocr_images")
def list_ocr_images(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise _invalid(f"page minimal 1 dan page_size 1–{MAX_PAGE_SIZE}")
    admin = _is_admin(current_user)
    rows, total = store.list_for(db, owner_id=_owner_id(current_user), page=page, page_size=page_size)
    return {
        "items": [_summary(r, name, admin) for r, name in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/ocr_images/{image_id}")
def get_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    out = _summary(row)
    out.update(mime_type=row.mime_type, text=row.text, error_message=row.error_message)
    return out


@router.get("/ocr_images/{image_id}/image")
def ocr_image_file(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    settings = get_settings()
    response = None
    try:
        response = get_minio().get_object(settings.minio_bucket_documents, row.object_path)
        data = response.read()
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="File gambar tidak ditemukan di storage")
    finally:
        if response is not None:
            try:
                response.close()
                response.release_conn()
            except Exception:
                pass
    return StreamingResponse(io.BytesIO(data), media_type=row.mime_type,
                             headers={"Content-Disposition": f'inline; filename="{row.filename}"'})


@router.post("/ocr_images/{image_id}/retry")
def retry_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    if row.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Hanya gambar berstatus gagal yang bisa diproses ulang")
    store.reset_pending(db, row)
    _send(row.id)
    return _summary(row)


@router.delete("/ocr_images/{image_id}")
def delete_ocr_image(image_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = _get_or_404(db, image_id, current_user)
    settings = get_settings()
    try:
        get_minio().remove_object(settings.minio_bucket_documents, row.object_path)
    except Exception:
        # Objek yang tertinggal lebih murah daripada baris yang tak bisa dihapus.
        logger.warning("gagal menghapus objek %s; baris tetap dihapus", row.object_path, exc_info=True)
    store.delete(db, row)
    return {"deleted": str(image_id)}
