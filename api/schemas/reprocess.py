from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReprocessCampaignOption(BaseModel):
    """Satu campaign pada daftar checkbox, lengkap dengan ongkos yang menantinya."""

    campaign: str
    tickets: int          # unique ticket id -> sebanyak inilah panggilan LLM-nya
    results: int          # jumlah baris Result yang ada sekarang
    obsolete: int         # baris lama yang akan hilang (= results - tickets)


class ReprocessPreviewResponse(BaseModel):
    campaigns: list[ReprocessCampaignOption]
    running_job_id: Optional[str] = None


class ReprocessStartRequest(BaseModel):
    campaigns: list[str]


class ReprocessFilterRequest(BaseModel):
    """Filter menu Results, apa adanya — tombol Reprocess All.

    Nama field-nya SENGAJA sama persis dengan parameter ``/list_results`` supaya
    layar bisa mengirim ``buildParams()`` tanpa pemetaan ulang. Pemetaan nama
    adalah tempat paling mudah bagi filter untuk diam-diam hilang, dan filter yang
    hilang di sini berarti tiket yang diproses lebih banyak daripada yang dilihat
    Admin di layar.
    """

    status: Optional[str] = None
    campaign: Optional[str] = None
    ticket_id: Optional[str] = None
    ai_status: Optional[str] = None
    manual_status: Optional[str] = None
    am_nip: Optional[str] = None
    tl_nip: Optional[str] = None
    agent_nip: Optional[str] = None
    qc_username: Optional[str] = None
    qc_support_username: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None


class CollectionFilterRequest(BaseModel):
    """Filter menu Collection Results, apa adanya — tombol Reprocess All / Delete All.

    Sama alasannya dengan ``ReprocessFilterRequest``: nama field-nya persis parameter
    ``GET /collection/results``, jadi layar mengirim filternya tanpa pemetaan ulang.
    """

    status: Optional[str] = None
    ai_status: Optional[str] = None
    ticket_id: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None


class ReprocessFilterPreviewResponse(BaseModel):
    """Ongkos yang menanti, dihitung dengan jalur yang sama dengan job-nya."""

    matched: int          # tiket yang cocok filter
    skipped: int          # di antaranya yang sedang direproses -> dilewati
    will_process: int     # matched - skipped; sebanyak inilah panggilan LLM-nya
    campaigns: list[str]  # campaign yang tersentuh, untuk ditulis di modal
    running_job_id: Optional[str] = None  # job massal yang sedang berjalan, kalau ada


class ReprocessItem(BaseModel):
    id: int
    ticket_id: str
    campaign: Optional[str] = None
    status: str
    new_result_id: Optional[str] = None
    deleted_old: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # Checkpoint pipeline TERAKHIR yang selesai untuk ``new_result_id`` (14
    # September 2026 — lihat results.current_stage dan
    # compliance.processing_stages.PROCESSING_STAGES). Hanya berarti selagi
    # status="processing"; None sebelum item ini mulai diproses atau setelah
    # selesai/gagal.
    current_stage: Optional[str] = None


class ReprocessCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0


class ReprocessJobResponse(BaseModel):
    job_id: str
    campaigns: list[str]
    scope: Optional[str] = None  # "campaign" (massal) | "ticket" (satu tiket)
    status: str
    total_tickets: int
    counts: ReprocessCounts
    created_by_username: Optional[str] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    items: list[ReprocessItem] = []


class ReprocessJobListResponse(BaseModel):
    jobs: list[ReprocessJobResponse]


class ReprocessKillTicketResponse(BaseModel):
    """Hasil tombol Kill per baris di menu Results."""

    ticket_id: str
    closed: int   # item yang ditutup (antre + sedang diproses)
    killed: int   # di antaranya yang sedang diproses -> task Celery-nya dihentikan
