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


class RosterRow(BaseModel):
    """Satu baris roster Sales Database aktif.

    ``dedicated`` adalah tag campaign orang tersebut — kolom yang menentukan tiket
    siapa yang terlihat olehnya, jadi harus bisa diperiksa dari dashboard tanpa
    membuka berkas XLSX-nya.
    """
    user_id: Optional[str] = None
    nip_baru: Optional[str] = None
    name: Optional[str] = None
    dedicated: Optional[str] = None
    nip_tl: Optional[str] = None
    team_leader: Optional[str] = None
    nip_am: Optional[str] = None
    area_manager: Optional[str] = None
    join_date: Optional[str] = None
    # True bila NIP-nya sudah punya akun login (dicek ke tabel users).
    has_account: bool = False


class RosterResponse(BaseModel):
    filename: Optional[str] = None
    total: int = 0
    campaigns: list[str] = []
    rows: list[RosterRow] = []
