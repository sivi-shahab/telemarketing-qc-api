"""Webhook ingestion endpoint.

``POST /webhook/process_ticket`` is the receiver for the upstream phase-1 caller
(the PHP/n8n script that, for each finished recording, POSTs ``ticket_id`` +
``product`` as ``application/x-www-form-urlencoded``). Instead of uploading the
PDFs, the caller only sends the ticket id; this endpoint locates the already-
present session transcript PDFs in object storage by that id and kicks off the
existing pipeline:

  - phase 2 — ``process_transcript`` (LLM scorecard)
  - phase 3 — ``process_document`` (Mistral OCR + verification), only when
    supporting document PDFs (KTP/KK/NPWP/Cover Buku Tabungan) are found.

PDF discovery (no new storage — reuses the existing MinIO buckets):
  - transcripts: every ``.pdf`` under ``MINIO_TRANSCRIPTS_SOURCE_PREFIX`` whose
    customer id (filename prefix before the ``_<timestamp>``) equals the ticket's
    customer id is collected — a session can span several calls.
  - documents: every ``.pdf`` under ``MINIO_DOCUMENTS_SOURCE_PREFIX`` for the
    same customer id whose name contains a known doc-type token.
  - objects already filed under a ``{result_id}`` (UUID) folder are skipped, so
    previously-processed submissions are never re-ingested.

Matched objects are server-side copied into ``{result_id}/...`` (the layout the
workers download from), a ``results`` row is created, and the tasks are enqueued
by name — exactly like ``/upload_transcript`` + ``/upload_document``.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, status
from services.s3_buckets import CopySource
from sqlalchemy.orm import Session

from pydantic import BaseModel



from api.dependencies import get_db, get_minio, get_settings
from api.schemas.result import WebhookProcessResponse
from compliance.pdf_parser import ticket_id_from_filename
from db import crud



"""
Endpoint baru untuk backend utama (port 4000).
Tambahkan ke api/routers/webhook.py (di bawah process_ticket sudah ada),
lalu PASTIKAN router-nya sudah di-include di main.py (webhook.router
sudah ter-include, jadi cukup tambah fungsi ini di file yang sama).

Tujuan: terima notifikasi dari STT service setelah PDF transkrip selesai
disimpan ke S3 (port 8010). Buat row baru di tabel `results` dengan
id = job_id dari STT (BUKAN UUID baru dari DB), status langsung "done"
karena transkrip PDF adalah hasil akhir (tidak ada evaluasi LLM lanjutan
untuk jalur upload audio mandiri ini).
"""




logger = logging.getLogger(__name__)

# Public (no auth), mimicking the upstream n8n webhook the PHP caller hits — the
# caller sends only `ticket_id` + `product` form fields, no auth header.
router = APIRouter()

# Doc-type detection from a filename, longest/most-specific token first so e.g.
# "..._cover_buku_tabungan.pdf" isn't mistaken for a "kk" match. Each doc_type
# maps to the substrings (lower-cased) that identify it.
_DOC_TYPE_TOKENS: list[tuple[str, tuple[str, ...]]] = [
    ("cover_buku_tabungan", ("cover_buku_tabungan", "cover-buku-tabungan", "buku_tabungan", "tabungan", "cover")),
    ("npwp", ("npwp",)),
    ("ktp", ("ktp",)),
    ("kk", ("kk",)),
]


def customer_id_from_ticket(ticket_id: str) -> str:
    """Customer/session id = the prefix before the ``_<timestamp>`` of a ticket id.

    ``ticket_id`` may be the full PDF stem (``130220dkIM_20260519132045``) or just
    the prefix (``130220dkIM``); both yield ``130220dkIM``.
    """
    stem = ticket_id_from_filename(ticket_id)  # strips .pdf + duplicate suffix
    return stem.rsplit("_", 1)[0]


def _customer_id_of_object(object_name: str) -> str:
    """Customer id of a stored object, derived from its basename."""
    basename = object_name.rsplit("/", 1)[-1]
    return customer_id_from_ticket(basename)


def _is_result_folder(object_name: str) -> bool:
    """True if the object's first path segment is a ``{result_id}`` (UUID) folder."""
    first = object_name.split("/", 1)[0]
    try:
        uuid.UUID(first)
        return True
    except ValueError:
        return False


def _classify_doc_type(basename: str) -> str | None:
    """Map a document filename to a known ``doc_type`` (or ``None`` if unknown)."""
    lowered = basename.lower()
    for doc_type, tokens in _DOC_TYPE_TOKENS:
        if any(tok in lowered for tok in tokens):
            return doc_type
    return None


def _find_session_objects(client, bucket: str, prefix: str, customer_id: str) -> list[str]:
    """List ``.pdf`` objects under ``prefix`` whose customer id matches, skipping
    UUID (result) folders. Returns sorted object names."""
    matches: list[str] = []
    for obj in client.list_objects(bucket, prefix=prefix or None, recursive=True):
        name = obj.object_name
        if not name.lower().endswith(".pdf"):
            continue
        if _is_result_folder(name):
            continue
        if _customer_id_of_object(name) == customer_id:
            matches.append(name)
    return sorted(matches)


@router.post("/webhook/process_ticket", response_model=WebhookProcessResponse)
def process_ticket(
    ticket_id: str = Form(...),
    product: str = Form(...),
    db: Session = Depends(get_db),
):
    ticket_id = (ticket_id or "").strip()
    product = (product or "").strip()
    if not ticket_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ticket_id wajib diisi"
        )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="product wajib diisi"
        )

    # 1. product -> active campaign (case-insensitive).
    campaign = crud.get_active_campaign_ci(db, product)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tidak ada campaign aktif untuk product '{product}'",
        )

    settings = get_settings()
    client = get_minio()
    customer_id = customer_id_from_ticket(ticket_id)

    # 2. find the session's transcript PDFs already present in the bucket.
    transcript_objs = _find_session_objects(
        client,
        settings.minio_bucket_transcripts,
        settings.minio_transcripts_source_prefix,
        customer_id,
    )
    if not transcript_objs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Tidak ada PDF transkrip untuk ticket '{ticket_id}' "
                f"(customer id '{customer_id}') di bucket '{settings.minio_bucket_transcripts}'"
            ),
        )

    source_files = [name.rsplit("/", 1)[-1] for name in transcript_objs]

    # 3. create the result row, then copy the PDFs into {result_id}/ (the layout
    #    the worker downloads from). Same shape as /upload_transcript.
    result = crud.create_result(
        db,
        campaign=campaign.name,
        source_files=source_files,
        num_calls=len(source_files),
        transcript_path=None,
    )
    result_id = str(result.id)

    for src in transcript_objs:
        basename = src.rsplit("/", 1)[-1]
        client.copy_object(
            settings.minio_bucket_transcripts,
            f"{result_id}/{basename}",
            CopySource(settings.minio_bucket_transcripts, src),
        )
    result.transcript_path = f"{result_id}/"
    db.commit()

    # 4. (phase 3) find + ingest supporting documents for the same customer id.
    documents: list[dict] = []
    seen_types: set[str] = set()
    for src in _find_session_objects(
        client,
        settings.minio_bucket_documents,
        settings.minio_documents_source_prefix,
        customer_id,
    ):
        basename = src.rsplit("/", 1)[-1]
        doc_type = _classify_doc_type(basename)
        if doc_type is None:
            logger.warning("ticket %s: unrecognised document filename '%s' (skipped)", ticket_id, basename)
            continue
        if doc_type in seen_types:
            logger.warning("ticket %s: duplicate %s document '%s' (skipped)", ticket_id, doc_type, basename)
            continue
        seen_types.add(doc_type)
        object_name = f"{result_id}/{doc_type}.pdf"
        client.copy_object(
            settings.minio_bucket_documents,
            object_name,
            CopySource(settings.minio_bucket_documents, src),
        )
        crud.create_document(
            db,
            result_id=result_id,
            doc_type=doc_type,
            filename=basename,
            object_path=object_name,
            mime_type="application/pdf",
        )
        documents.append({"doc_type": doc_type, "source_object": src})

    # 5. enqueue the pipeline by name (API does not import worker/pdfplumber).
    from api.celery_client import celery_app

    celery_app.send_task(
        "worker.tasks.process_transcript.process_transcript", args=[result_id]
    )
    phase_3_enqueued = bool(documents)
    if phase_3_enqueued:
        celery_app.send_task(
            "worker.tasks.process_document.process_document", args=[result_id]
        )

    logger.info(
        "webhook ticket=%s product=%s -> result=%s calls=%d docs=%d",
        ticket_id, product, result_id, len(source_files), len(documents),
    )

    return WebhookProcessResponse(
        ticket_id=ticket_id,
        result_id=result_id,
        status="pending",
        campaign=campaign.name,
        num_calls=len(source_files),
        source_files=source_files,
        documents=documents,
        phase_2_enqueued=True,
        phase_3_enqueued=phase_3_enqueued,
    )





# Pakai router yang SAMA dengan process_ticket (webhook.router) kalau
# ditaruh di file webhook.py yang sama — tinggal tambah fungsi ini,
# tidak perlu `router = APIRouter()` baru.
# router = APIRouter()   # <- hapus baris ini kalau ditaruh di webhook.py


class RegisterSttResultRequest(BaseModel):
    result_id: str            # = job_id dari STT service
    pdf_filename: str          # nama file PDF di S3 (port 8010), tanpa ekstensi
    source_filename: str       # nama file audio asli yang diupload user
    speaker_count: int | None = None
    confidence: float | None = None


class RegisterSttResultResponse(BaseModel):
    result_id: str
    status: str


@router.post("/webhook/register_stt_result", response_model=RegisterSttResultResponse)
def register_stt_result(
    payload: RegisterSttResultRequest,
    db: Session = Depends(get_db),
):
    # Idempotency check: kalau job_id ini sudah pernah diregister
    # sebelumnya (misal STT retry webhook karena timeout), jangan bikin
    # row duplikat — langsung balas sukses dengan data yang sudah ada.
    existing = crud.get_result(db, payload.result_id)
    if existing is not None:
        logger.info(
            "STT result %s sudah pernah diregister sebelumnya, skip insert.",
            payload.result_id,
        )
        return RegisterSttResultResponse(
            result_id=str(existing.id), status=existing.status
        )

    # STT service tidak memberi info campaign — hasil transkrip plain ini
    # tidak terikat campaign tertentu (campaign = NULL, kolom nullable).
    result = crud.create_result(
        db,
        campaign=None,
        source_files=[payload.source_filename],
        num_calls=1,
        transcript_path=payload.pdf_filename,
        id=payload.result_id,
        status="done",
    )

    logger.info(
        "STT result registered: result_id=%s pdf=%s source=%s",
        payload.result_id, payload.pdf_filename, payload.source_filename,
    )

    return RegisterSttResultResponse(result_id=str(result.id), status=result.status)