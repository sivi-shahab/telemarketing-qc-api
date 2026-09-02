from typing import Optional, Any
from datetime import datetime

from pydantic import BaseModel


class ResultCreateResponse(BaseModel):
    result_id: str
    status: str
    reused: bool = False


class ResultResponse(BaseModel):
    result_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


class WebhookDocumentItem(BaseModel):
    doc_type: str
    source_object: str  # object name matched in the documents source bucket


class WebhookProcessResponse(BaseModel):
    ticket_id: str
    result_id: str
    status: str
    campaign: str
    num_calls: int
    source_files: list[str]
    documents: list[WebhookDocumentItem] = []
    phase_2_enqueued: bool  # process_transcript (scorecard)
    phase_3_enqueued: bool  # process_document (OCR) — only when documents were found
    
class QcStatusRequestInfo(BaseModel):
    requested_status: str  # vonis human: PASS | FAIL | PENDING
    reason: Optional[str] = None
    requested_by_username: Optional[str] = None
    requested_by_role: Optional[str] = None
    requested_at: Optional[datetime] = None
    tl_qc_status: str = "pending"  # Team Leader QC intermediate: pending | approved | rejected
    tl_qc_username: Optional[str] = None
    tl_qc_reviewed_at: Optional[datetime] = None
    approval_status: str  # SPQ Head final: pending | approved | rejected
    reviewed_by_username: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    tl_qc_comment: Optional[str] = None  # Team Leader QC's note (approve/reject/escalate)
    review_comment: Optional[str] = None  # SPQ Head's note (approve/reject)
    origin: str = "qc"  # qc (usulan, lewat hierarki) | qc_confirm (sama dengan AI Status, final) | tl_direct | spq_direct (final saat dibuat)

    class Config:
        from_attributes = True


class QcStatusEventInfo(BaseModel):
    """Satu kejadian pada riwayat Manual Status (append-only, hanya untuk ditampilkan)."""
    id: int
    event: str  # usul | konfirmasi | set_langsung | tl_approve | tl_reject | tl_escalate | spq_approve | spq_reject
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    requested_status: Optional[str] = None  # vonis yang diusulkan/ditetapkan saat itu
    status_before: Optional[str] = None  # Manual Status efektif SEBELUM kejadian
    status_after: Optional[str] = None   # Manual Status efektif SESUDAH kejadian
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QcStatusEventListResponse(BaseModel):
    result_id: str
    events: list[QcStatusEventInfo] = []


class QcManualCheckInfo(BaseModel):
    """One "sudah dicek manual oleh QC" event (append-only; newest row wins)."""
    id: int
    checked_by_username: str
    checked_by_role: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ErrorCodeAppealInfo(BaseModel):
    id: int
    result_id: str
    error_code: str
    item_code: str
    ai_sumber: Optional[str] = None
    ai_risk_base: Optional[str] = None
    ai_details_error: Optional[str] = None
    ai_reason: Optional[str] = None
    ai_evidence: Optional[str] = None
    ai_ticket_id: Optional[str] = None
    qc_reason: Optional[str] = None
    qc_evidence: Optional[str] = None
    qc_ticket_id: Optional[str] = None
    qc_reference_value: Optional[str] = None
    qc_extracted_value: Optional[str] = None
    qc_new_error_code: Optional[str] = None
    qc_risk_base: Optional[str] = None  # QC-edited Risk Base override (empty => catalog default)
    appeal_kind: str = "remove"
    add_source: Optional[str] = None  # for appeal_kind='add': scorecard|cashline_data|card_holder|others
    origin: str = "qc"  # qc (tiered review) | tl_direct | spq_direct (reviewer direct edit, no hierarchy)
    requested_by_username: Optional[str] = None
    requested_at: Optional[datetime] = None
    tl_qc_status: str = "pending"  # Team Leader QC intermediate: pending | approved | rejected
    tl_qc_username: Optional[str] = None
    tl_qc_reviewed_at: Optional[datetime] = None
    approval_status: str  # SPQ Head final: pending | approved | rejected
    reviewed_by_username: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    tl_qc_comment: Optional[str] = None  # Team Leader QC's note (approve/reject/escalate)
    review_comment: Optional[str] = None  # SPQ Head's note (approve/reject)

    class Config:
        from_attributes = True


class ResultListItem(BaseModel):
    result_id: str
    id: Optional[str] = None  # customer/ticket prefix from source filename
    customer_name: Optional[str] = None  # cashline CSV `cust_name` (Sales Agent view)
    account_number: Optional[str] = None  # "Nomor Kartu" — ascend `CUST_CR_CARD1`, masked (middle 8 digits) server-side; None → "NTB"
    credit_limit: Optional[str] = None  # "Limit Sebelumnya" — ascend `CUST_CRLIMIT`; only non-NTB customers, sales-side view
    campaign: Optional[str]
    source_files: Optional[list]
    num_calls: Optional[int]
    audio_duration: Optional[str] = None  # total spoken duration, e.g. "40m 30s"
    # Rincian durasi per PDF: [{"file": "<nama>.pdf", "duration": "12m 3s"}], urut
    # kronologis sama dengan `source_files`. Dipakai kolom Call Duration tata letak
    # Demo. None pada tiket lama yang diproses sebelum rincian ini disimpan —
    # tampilannya jatuh balik ke nama berkas tanpa durasi.
    audio_durations: Optional[list] = None
    # Panggilan tiket ini yang TIDAK ikut dinilai karena milik agent lain:
    # [{"filename", "detected_agent": [...], "similarity_percent", "duration"}].
    # Ikut dirender kolom Call Duration, ditandai terpisah dari yang dinilai — lihat
    # compliance/call_ownership.py. Kosong/None pada tiket satu-agent.
    excluded_calls: Optional[list] = None
    campaign_interest: Optional[list] = None  # LLM evaluation.campaign_interest (product names)
    critical_compliance_check: Optional[dict] = None  # LLM evaluation.critical_compliance_check (status + checked_items)
    # Kolom SCOREBOMB: seluruh item yang memotong skor lewat iris — kritis (ratio 0.25)
    # dan non-tolerable lain (ratio 0.10). Tiap entri:
    # {item_code, requirement, reason, status, ratio, amount}. Lihat
    # compliance.scoring.score_bomb_items.
    score_bomb_items: Optional[list] = None
    non_tolerable_items: Optional[list] = None  # negated reasons for non-tolerable (tolerable=NO) unmet scorecard items
    # Item scorecard yang belum beres: [{"item_code": "SC_CL_12", "status": "BELUM_SESUAI"
    # | "PENDING"}]. Kolom SCORECARD tata letak Demo — lihat _scorecard_issues.
    scorecard_issues: list[dict] = []
    status: str
    ai_score: Optional[float] = None  # LLM evaluation.ai_score_phase_3
    passing_grade: Optional[float] = None  # LLM evaluation.passing_grade
    maximum_score: Optional[float] = None  # LLM evaluation.maximum_score
    ai_status: Optional[str] = None  # PASS | FAIL (LLM evaluation.ai_status)
    uploaded_at: Optional[datetime]
    uploaded_by_username: Optional[str] = None  # who uploaded the transcript
    uploaded_by_role: Optional[str] = None  # role of the uploader
    generated_at: Optional[datetime] = None  # transcript "Generated" date
    submit_time: Optional[str] = None  # tms_cashline submit_time (raw string); basis for the Pending Check H+2 SLA timer
    completed_at: Optional[datetime]
    processing_sec: Optional[float]
    document_triggers: list[str] = []  # TMS data changes (Alamat Kantor/Rumah, NPWP, NIK) that enable the Upload Document button
    document_upload_types: list[str] = []  # document types allowed to upload (ktp/kk/npwp), matching the changed fields + similarity bands
    document_missing_types: list[str] = []  # subset of document_upload_types not yet uploaded
    document_missing_labels: list[str] = []  # label dokumen yang belum diunggah, mis. ["NPWP"] — dipakai catatan "Cek Dokumen NPWP"
    # Dokumen yang diminta BESERTA alasannya: [{"doc_type","doc_label","reason"}].
    # Kolom Document merangkainya jadi "Perlu Dokumen NPWP karena Perubahan NPWP".
    document_requirements: list[dict] = []
    # Tiket ini punya item reproses yang masih mengantre/berjalan. Menahan tombol
    # Reprocess di menu Results SETELAH refresh atau pindah menu — layar sendiri
    # hanya mengingat job yang ia mulai di sesi itu, dan lupa begitu komponennya
    # dibuang. Sumbernya sama dengan pengaman 409 di POST /reprocess_ticket.
    reprocess_active: bool = False
    has_documents: bool = False  # at least one uploaded document exists for this result
    document_uploaded_at: Optional[datetime] = None  # latest document upload time, if any
    manual_status: Optional[str] = None  # PASS | FAIL | PENDING — vonis human, default mengikuti AI Status
    # True bila nilainya benar-benar ditetapkan human; False = masih mengikuti AI Status.
    manual_status_by_human: bool = False
    # Keadaan alur kerja vonis human: 'final' | 'menunggu' | 'ditolak' | None.
    manual_review_state: Optional[str] = None
    # Dokumen wajib (perubahan TMS / limit >= 50jt / band similarity) belum diunggah —
    # inilah kondisi SLA H+2 yang memunculkan catatan "Cek Dokumen".
    missing_documents: bool = False
    # Keterangan singkat kenapa AI Status = PENDING, mis. "Menunggu dokumen NPWP
    # (SLA H+2)". None bila statusnya bukan PENDING atau PENDING-nya datang dari LLM.
    pending_reason: Optional[str] = None
    # Kenapa AI Status-nya Not Qualified, untuk sebab yang TIDAK terbaca dari skor —
    # sejak 21 Agustus 2026 hanya badword. None = tidak ada sebab khusus; kegagalan
    # biasa cukup dibaca dari skor & error code, dan kegagalan konsistensi verifikasi
    # statik dibaca dari item kritikal SC_CL_23_1/23_2 yang gagal.
    fail_reason: Optional[str] = None
    # Jumlah kejadian pada riwayat Manual Status (0 = belum pernah berubah).
    manual_status_history_count: int = 0
    qc_request: Optional[QcStatusRequestInfo] = None  # QC-proposed AI-status change, if any
    appeal_summary: Optional[dict] = None  # Error Code banding summary (counts + history) for this result
    assigned_qc: Optional[str] = None  # QC username this ticket is assigned to (Team Leader QC / SPQ Head view)
    assigned_at: Optional[datetime] = None  # when the Team Leader QC assigned it ("Assign Date")
    # Per-ticket manual check by QC ("sudah dicek manual"). Latest event only;
    # the full trail is at GET /qc_manual_check/{result_id}.
    qc_checked_at: Optional[datetime] = None
    qc_checked_by: Optional[str] = None

    class Config:
        from_attributes = True


class ResultListResponse(BaseModel):
    items: list[ResultListItem]
    total: int
    page: int
    limit: int


class TranscriptListItem(BaseModel):
    result_id: str
    filename: str
    ticket_id: str  # prefix before the first "_" of the filename
    campaign: Optional[str] = None
    status: str
    uploaded_at: Optional[datetime] = None
    uploaded_by_username: Optional[str] = None
    uploaded_by_role: Optional[str] = None


class TranscriptListResponse(BaseModel):
    items: list[TranscriptListItem]
    total: int
    page: int
    limit: int


class StatsResponse(BaseModel):
    total_uploaded: int
    pending: int
    processing: int
    done: int
    failed: int
    avg_processing_sec: Optional[float]
    active_campaigns: list[str]


class DailyStatItem(BaseModel):
    date: str
    uploaded: int
    done: int
    processing: int
    pending: int
    failed: int


class DailyStatsResponse(BaseModel):
    days: list[DailyStatItem]


class TicketDeleteResponse(BaseModel):
    ticket_id: str
    deleted: int


class ScorecardEvidence(BaseModel):
    """``evidence`` sebuah item scorecard: kutipan transkrip + menit ke berapa + file
    PDF asalnya."""
    quote: Optional[str] = None
    timestamp: Optional[str] = None
    ticket_id: Optional[str] = None


class NamaIbuKandungItem(BaseModel):
    ticket_id: str
    submit_time: Optional[str] = None
    ascend: Optional[str] = None
    transkrip: Optional[str] = None
    match: Optional[str] = None
    evidence: Optional[ScorecardEvidence] = None
    similarity: Optional[float] = None
    reason: Optional[str] = None


class NamaIbuKandungResponse(BaseModel):
    total: int
    rows: list[NamaIbuKandungItem]
