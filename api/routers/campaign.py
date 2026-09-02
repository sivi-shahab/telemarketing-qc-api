import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_llm_client,
    get_minio,
    get_settings,
)
from api.schemas.campaign import (
    CampaignDeleteResponse,
    CampaignReadiness,
    CampaignReadinessResponse,
    CampaignDetailResponse,
    CampaignItem,
    CampaignListResponse,
    CampaignUploadResponse,
    RiplayKbChange,
)
from compliance import riplay as riplay_lib
from db import crud
from api.permissions import ADMIN_CAMPAIGN_WRITE
from api.rbac import require

router = APIRouter(dependencies=[Depends(get_current_user)])


def _read_text(upload: UploadFile, label: str) -> str:
    if not (upload.filename or "").lower().endswith(".txt"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File '{label}' harus berformat .txt",
        )
    raw = upload.file.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File '{label}' bukan teks UTF-8 yang valid",
        )


def _read_riplay_pdf(upload: UploadFile) -> bytes:
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File 'RIPLAY' harus berformat .pdf",
        )
    raw = upload.file.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File 'RIPLAY' kosong",
        )
    return raw


def _extract_and_gate_riplay(pdf_bytes: bytes, campaign: str) -> tuple[dict, str, float]:
    """Run the RIPLAY vision extraction and enforce the product-name gate.

    Returns ``(extraction, product_name, similarity)``. Raises 422 when the model
    can't read the PDF or when the product name on the RIPLAY doesn't match the
    campaign being uploaded — a mismatch means the wrong fact sheet was attached,
    and letting it through would overwrite the KB with another product's values.
    """
    settings = get_settings()
    # Konfigurasi dibaca DI LUAR try. Kalau ikut di dalam, setting yang hilang
    # (AttributeError) tertangkap `except Exception` di bawah dan dilaporkan sebagai
    # 502 "gagal dihubungi" — orang lalu mengejar jaringan & kuota LLM padahal
    # masalahnya ada di Settings aplikasi sendiri. Ini persis yang terjadi pada
    # riplay_model dkk. sebelum keempatnya dideklarasikan.
    model = settings.riplay_model or settings.llm_model
    max_pages = settings.riplay_max_pages
    scale = settings.riplay_render_scale
    min_similarity = settings.riplay_min_similarity
    temperature = settings.llm_temperature
    try:
        extraction = riplay_lib.extract_riplay(
            pdf_bytes,
            llm_client=get_llm_client(),
            model=model,
            max_pages=max_pages,
            scale=scale,
            temperature=temperature,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Gagal mengekstraksi RIPLAY: {exc}",
        )
    except Exception as exc:  # network / provider failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ekstraksi RIPLAY gagal dihubungi: {exc}",
        )

    product_name = (extraction.get("nama_produk") or "").strip()
    similarity = riplay_lib.product_name_similarity(product_name, campaign)
    if similarity < min_similarity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Nama produk pada RIPLAY ('{product_name or '-'}') tidak cocok dengan "
                f"campaign '{campaign}' (similarity {similarity}%, minimal "
                f"{min_similarity}%). Pastikan RIPLAY yang diupload "
                "sesuai dengan campaign."
            ),
        )
    return extraction, product_name, similarity


@router.post(
    "/upload_detail_campaign",
    response_model=CampaignUploadResponse,
    # Sebelumnya endpoint ini HANYA di-gate get_current_user (dependency router),
    # sehingga role apa pun yang login bisa menimpa prompt/KB/scorecard — yaitu
    # seluruh aturan QC. Sekarang butuh ADMIN_CAMPAIGN_WRITE, sejalan dengan
    # menu Upload Campaign yang memang hanya milik SPQ Head / Admin.
    dependencies=[Depends(require(ADMIN_CAMPAIGN_WRITE))],
)
def upload_detail_campaign(
    scorecard: UploadFile = File(...),
    knowledge_base: UploadFile = File(...),
    prompt: UploadFile = File(...),
    campaign: str = Form(...),
    riplay: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Upload a campaign config (scorecard / KB / prompt) plus an optional RIPLAY.

    The three TXT files feed the LLM as-is (no JSON parsing/validation). When a
    RIPLAY PDF is attached it is rendered to page images, extracted by the LLM,
    gated on the product name, and overlaid onto the KB — the RIPLAY wins wherever
    the two disagree. When none is attached, the campaign's previously stored
    RIPLAY extraction (if any) is re-applied, so the KB stays in sync with the
    bank's latest fact sheet without a manual edit.
    """
    scorecard_text = _read_text(scorecard, "scorecard")
    kb_text_raw = _read_text(knowledge_base, "knowledge_base")
    prompt_text = _read_text(prompt, "prompt")

    riplay_pdf: Optional[bytes] = None
    if riplay is not None and (riplay.filename or ""):
        riplay_pdf = _read_riplay_pdf(riplay)

    existing = crud.get_campaign_by_name(db, campaign)
    riplay_fields: Optional[dict] = None
    extraction: Optional[dict] = None

    if riplay_pdf is not None:
        extraction, product_name, similarity = _extract_and_gate_riplay(riplay_pdf, campaign)
        riplay_fields = {
            "filename": riplay.filename,
            "product_name": product_name,
            "similarity": similarity,
            "extraction": extraction,
            "uploaded_at": datetime.utcnow(),
        }
    elif existing is not None and existing.riplay_extraction:
        # Keep the KB dynamic: a config re-upload without a new RIPLAY still gets
        # the stored one re-applied on top of the freshly uploaded KB.
        extraction = existing.riplay_extraction

    kb_text = kb_text_raw
    applied: list[dict] = []
    if extraction:
        kb_text, applied = riplay_lib.apply_riplay_to_kb(kb_text_raw, extraction)
        if riplay_fields is not None:
            riplay_fields["applied"] = applied

    crud.upsert_campaign(
        db,
        name=campaign,
        prompt_text=prompt_text,
        scorecard_text=scorecard_text,
        kb_text=kb_text,
        kb_text_raw=kb_text_raw,
        prompt_filename=prompt.filename,
        scorecard_filename=scorecard.filename,
        kb_filename=knowledge_base.filename,
        riplay=riplay_fields,
    )

    # Archive the raw uploads to MinIO campaigns/{name}/
    settings = get_settings()
    client = get_minio()
    archive = {
        "scorecard.txt": scorecard_text,
        "knowledge_base.txt": kb_text_raw,
        "knowledge_base_applied.txt": kb_text,
        "prompt.txt": prompt_text,
    }
    if extraction:
        archive["riplay_extraction.json"] = json.dumps(extraction, indent=2, ensure_ascii=False)
    for fname, content in archive.items():
        data = content.encode("utf-8")
        client.put_object(
            settings.minio_bucket_campaigns,
            f"{campaign}/{fname}",
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
    if riplay_pdf is not None:
        client.put_object(
            settings.minio_bucket_campaigns,
            f"{campaign}/riplay.pdf",
            io.BytesIO(riplay_pdf),
            length=len(riplay_pdf),
            content_type="application/pdf",
        )

    return CampaignUploadResponse(
        campaign=campaign,
        scorecard_chars=len(scorecard_text),
        kb_chars=len(kb_text),
        prompt_chars=len(prompt_text),
        riplay_filename=riplay_fields["filename"] if riplay_fields else None,
        riplay_product_name=riplay_fields["product_name"] if riplay_fields else None,
        riplay_similarity=riplay_fields["similarity"] if riplay_fields else None,
        riplay_pages=(extraction or {}).get("_pages") if riplay_fields else None,
        riplay_kb_changes=[
            RiplayKbChange(
                kb_code=item["kb_code"],
                aspect=item["aspect"],
                details_before=item["details_before"],
                details_after=item["details_after"],
            )
            for item in applied
        ],
    )


@router.get("/list_campaigns", response_model=CampaignListResponse)
def list_campaigns(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Daftar campaign DALAM CAKUPAN pemanggil (sumber semua dropdown Campaign).

    Dashboard sudah menyaringnya di sisi klien (``utils/campaignScope.js``), tetapi
    penyaringan itu kosmetik — endpoint-nya sendiri dulu selalu mengembalikan seluruh
    tabel, jadi nama campaign lain tetap terbaca dari respons mentahnya."""
    from api.rbac import effective_campaigns_for

    campaigns = crud.list_campaigns(db)
    allowed = effective_campaigns_for(db, current_user)
    if allowed is not None:
        names = {(c or "").strip().casefold() for c in allowed}
        campaigns = [c for c in campaigns if (c.name or "").strip().casefold() in names]
    return CampaignListResponse(
        campaigns=[CampaignItem.model_validate(c) for c in campaigns]
    )


@router.get("/get_campaign", response_model=CampaignDetailResponse)
def get_campaign(
    campaign: str = Query(..., description="Nama campaign"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return a campaign's full config (text content + original upload filenames)
    for the dashboard viewer.

    Dibatasi ke campaign yang menjadi cakupan pemanggil: isinya adalah knowledge
    base, prompt dan scorecard — aturan QC campaign itu seutuhnya — dan dulu terbuka
    untuk SIAPA PUN yang sudah login, cukup dengan menyebut namanya."""
    from api.rbac import effective_campaigns_for

    allowed = effective_campaigns_for(db, current_user)
    if allowed is not None and campaign.strip().casefold() not in {
        (c or "").strip().casefold() for c in allowed
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Campaign ini di luar cakupan Anda",
        )
    c = crud.get_campaign_by_name(db, campaign)
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign '{campaign}' tidak ditemukan",
        )
    return CampaignDetailResponse.model_validate(c)


@router.delete(
    "/delete_campaign",
    response_model=CampaignDeleteResponse,
    dependencies=[Depends(require(ADMIN_CAMPAIGN_WRITE))],
)
def delete_campaign(
    campaign: str = Query(..., description="Nama campaign yang akan dihapus"),
    db: Session = Depends(get_db),
):
    """Delete a campaign config by name (SPQ Head only).

    Removes the DB row and best-effort deletes its MinIO archive under
    ``campaigns/{name}/``. Existing results keep their (string) campaign value.
    """
    deleted = crud.delete_campaign(db, campaign)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign '{campaign}' tidak ditemukan",
        )

    # Best-effort cleanup of the raw archive in MinIO (don't fail the request).
    removed = 0
    try:
        settings = get_settings()
        client = get_minio()
        objects = client.list_objects(
            settings.minio_bucket_campaigns, prefix=f"{campaign}/", recursive=True
        )
        for obj in objects:
            client.remove_object(settings.minio_bucket_campaigns, obj.object_name)
            removed += 1
    except Exception:
        pass

    return CampaignDeleteResponse(
        campaign=campaign, deleted=True, archive_objects_removed=removed
    )


@router.get(
    "/campaign_readiness",
    response_model=CampaignReadinessResponse,
    dependencies=[Depends(require(ADMIN_CAMPAIGN_WRITE))],
)
def campaign_readiness(db: Session = Depends(get_db)):
    """Kesiapan tiap campaign: konfigurasi QC, roster, akun, data TMS, dan tiket.

    Sebuah campaign yang baru dibuat LANGSUNG bisa dipilih di filter Stats/Results dan
    saat membuat role — tetapi itu belum menjamin tiketnya akan terlihat. Tiga syarat
    di bawah gagal secara DIAM-DIAM bila tidak dipenuhi (layar hanya kosong), jadi
    statusnya dikumpulkan di satu tempat:

    * konfigurasi kosong  -> transkrip ditolak worker, tiket berhenti di `failed`;
    * roster kosong       -> role sisi sales tidak punya cakupan (irisan kosong);
    * TMS kosong          -> tiket tidak bisa dipetakan ke agent.

    ``tickets_unmapped`` dihitung dari customer id UNIK, bukan jumlah tiket: beberapa
    tiket bisa berbagi customer id yang sama, jadi membandingkan cacah baris TMS
    dengan cacah tiket akan menyesatkan.
    """
    from sales_lookup import active_sales_map
    from db.models import Result, TmsCashline, User

    sales_map = active_sales_map(db)
    active_usernames = {
        (u.username or "").strip().casefold()
        for u in db.query(User.username).filter(User.is_active.is_(True)).all()
        if (u.username or "").strip()
    }

    # Satu kali lewat roster untuk SEMUA campaign, bukan sekali per campaign.
    roster_count: dict = {}
    account_count: dict = {}
    for e in sales_map.values():
        ded = (e.get("dedicated") or "").strip().casefold()
        if not ded:
            continue
        roster_count[ded] = roster_count.get(ded, 0) + 1
        nip = (e.get("nip_baru") or "").strip().casefold()
        if nip and nip in active_usernames:
            account_count[ded] = account_count.get(ded, 0) + 1

    # Tiket + customer id per campaign, sekali query.
    tickets: dict = {}
    done: dict = {}
    cids_by_campaign: dict = {}
    for camp, status_, sf in db.query(Result.campaign, Result.status, Result.source_files).all():
        key = (camp or "").strip().casefold()
        tickets[key] = tickets.get(key, 0) + 1
        if status_ == "done":
            done[key] = done.get(key, 0) + 1
        if sf and isinstance(sf[0], str) and sf[0]:
            cids_by_campaign.setdefault(key, set()).add(sf[0].split("_", 1)[0].strip())

    all_cids = {c for v in cids_by_campaign.values() for c in v}
    tms_cids = set()
    if all_cids:
        tms_cids = {
            (r or "").strip()
            for (r,) in db.query(func.trim(TmsCashline.result_id))
            .filter(func.trim(TmsCashline.result_id).in_(list(all_cids)))
            .distinct()
            .all()
        }

    items = []
    for c in crud.list_campaigns(db):
        key = (c.name or "").strip().casefold()
        missing = [
            label
            for label, text in (
                ("prompt", c.prompt_text),
                ("scorecard", c.scorecard_text),
                ("KB", c.kb_text),
            )
            if not (text or "").strip()
        ]
        items.append(CampaignReadiness(
            name=c.name,
            is_active=bool(c.is_active),
            has_config=not missing,
            missing_config=missing,
            roster_people=roster_count.get(key, 0),
            accounts=account_count.get(key, 0),
            tickets=tickets.get(key, 0),
            tickets_done=done.get(key, 0),
            tickets_unmapped=len(cids_by_campaign.get(key, set()) - tms_cids),
        ))
    items.sort(key=lambda x: x.name)
    return CampaignReadinessResponse(items=items)
