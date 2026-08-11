from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class CampaignUploadResponse(BaseModel):
    campaign: str
    scorecard_chars: int
    kb_chars: int
    prompt_chars: int


class CampaignItem(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CampaignListResponse(BaseModel):
    campaigns: list[CampaignItem]


class CampaignDeleteResponse(BaseModel):
    campaign: str
    deleted: bool
    archive_objects_removed: int


class CampaignDetailResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    prompt_filename: Optional[str] = None
    scorecard_filename: Optional[str] = None
    kb_filename: Optional[str] = None
    prompt_text: str
    scorecard_text: str
    kb_text: str

    class Config:
        from_attributes = True
