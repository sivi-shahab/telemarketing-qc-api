from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class RiplayKbChange(BaseModel):
    """One KB entry whose values were rewritten from the RIPLAY extraction."""

    kb_code: str
    aspect: str
    details_before: Optional[dict] = None
    details_after: Optional[dict] = None


class CampaignUploadResponse(BaseModel):
    campaign: str
    scorecard_chars: int
    kb_chars: int
    prompt_chars: int
    riplay_filename: Optional[str] = None
    riplay_product_name: Optional[str] = None
    riplay_similarity: Optional[float] = None
    riplay_pages: Optional[int] = None
    riplay_kb_changes: list[RiplayKbChange] = []


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


class CampaignReadiness(BaseModel):
    """Kesiapan satu campaign untuk benar-benar menghasilkan tiket yang terlihat.

    Sebuah campaign baru bisa langsung dipilih di filter maupun saat membuat role,
    tetapi itu belum berarti tiketnya akan muncul. Ada beberapa syarat yang bila
    kurang menyebabkan layar kosong TANPA pesan apa pun — di sinilah syarat-syarat
    itu dibuat terlihat.
    """
    name: str
    is_active: bool = True
    # Prompt/scorecard/KB terisi. Bila kosong, worker menolak transkrip campaign ini
    # (lihat worker/tasks/process_transcript.py) dan tiketnya berhenti di `failed`.
    has_config: bool = False
    missing_config: list[str] = []
    # Baris Sales Database yang kolom DEDICATED-nya campaign ini. Tanpa ini, role
    # sisi sales yang dibatasi ke campaign ini tidak punya cakupan sama sekali.
    roster_people: int = 0
    # Berapa di antaranya sudah punya akun login aktif.
    accounts: int = 0
    tickets: int = 0
    tickets_done: int = 0
    # Tiket yang customer id-nya TIDAK ada di tms_cashline: tidak bisa dipetakan ke
    # agent, jadi jatuh ke node "(Tidak diketahui)" dan tidak terlihat oleh satu pun
    # user sisi sales. Dihitung dari customer id UNIK — beberapa tiket bisa berbagi
    # customer id yang sama, sehingga membandingkan langsung dengan ``tickets``
    # akan menyesatkan.
    tickets_unmapped: int = 0


class CampaignReadinessResponse(BaseModel):
    items: list[CampaignReadiness]


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
    # KB as uploaded, before the RIPLAY overlay (None for pre-RIPLAY campaigns).
    kb_text_raw: Optional[str] = None
    riplay_filename: Optional[str] = None
    riplay_product_name: Optional[str] = None
    riplay_similarity: Optional[float] = None
    riplay_extraction: Optional[dict] = None
    riplay_applied: Optional[list] = None
    riplay_uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True
