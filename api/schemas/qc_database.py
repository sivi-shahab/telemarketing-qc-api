from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class QcDatabaseItem(BaseModel):
    id: int
    filename: str
    is_active: bool
    uploaded_by_username: Optional[str] = None
    uploaded_by_role: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QcDatabaseListResponse(BaseModel):
    items: list[QcDatabaseItem]


class QcDatabaseUploadResponse(BaseModel):
    id: int
    filename: str
    is_active: bool
