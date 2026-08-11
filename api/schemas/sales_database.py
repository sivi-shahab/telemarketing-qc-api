from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SalesDatabaseItem(BaseModel):
    id: int
    filename: str
    is_active: bool
    uploaded_by_username: Optional[str] = None  # profile username of the Sales Agent uploader
    uploaded_by_role: Optional[str] = None  # role of the uploader (e.g. sales_agent)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SalesDatabaseListResponse(BaseModel):
    items: list[SalesDatabaseItem]


class SalesDatabaseUploadResponse(BaseModel):
    id: int
    filename: str
    is_active: bool
