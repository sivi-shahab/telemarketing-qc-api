"""Akses data tabel ``ocr_images`` (menu OCR Gambar).

``owner_id=None`` berarti tanpa filter pemilik — hanya untuk Admin/Demo. Router
yang menentukan nilainya; modul ini tidak mengenal role.
"""
import uuid

from sqlalchemy.orm import Session

from db.models import OcrImage, User


def create(db: Session, *, image_id, user_id, batch_id, filename, object_path,
           mime_type, size_bytes) -> OcrImage:
    row = OcrImage(id=image_id, user_id=user_id, batch_id=batch_id, filename=filename,
                   object_path=object_path, mime_type=mime_type, size_bytes=size_bytes,
                   status="pending")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_for(db: Session, *, owner_id, page: int, page_size: int):
    """``([(OcrImage, nama_pengunggah), ...], total)``, terbaru dulu."""
    q = db.query(OcrImage, User.name, User.username).outerjoin(User, User.id == OcrImage.user_id)
    if owner_id is not None:
        q = q.filter(OcrImage.user_id == owner_id)
    total = q.count()
    rows = (
        q.order_by(OcrImage.created_at.desc(), OcrImage.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [(row, name or username) for row, name, username in rows], total


def get_for(db: Session, image_id, *, owner_id):
    try:
        uid = uuid.UUID(str(image_id))
    except ValueError:
        return None
    q = db.query(OcrImage).filter(OcrImage.id == uid)
    if owner_id is not None:
        q = q.filter(OcrImage.user_id == owner_id)
    return q.first()


def reset_pending(db: Session, row: OcrImage) -> None:
    row.status = "pending"
    row.text = None
    row.error_message = None
    row.started_at = None
    row.finished_at = None
    db.commit()


def delete(db: Session, row: OcrImage) -> None:
    db.delete(row)
    db.commit()
