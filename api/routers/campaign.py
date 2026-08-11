import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from api.dependencies import get_spq_head_user, get_current_user, get_db, get_minio, get_settings
from api.schemas.campaign import (
    CampaignDeleteResponse,
    CampaignDetailResponse,
    CampaignItem,
    CampaignListResponse,
    CampaignUploadResponse,
)
from db import crud

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


@router.post("/upload_detail_campaign", response_model=CampaignUploadResponse)
def upload_detail_campaign(
    scorecard: UploadFile = File(...),
    knowledge_base: UploadFile = File(...),
    prompt: UploadFile = File(...),
    campaign: str = Form(...),
    db: Session = Depends(get_db),
):
    # All three are raw TXT — no JSON parsing/validation; they feed the LLM as-is.
    scorecard_text = _read_text(scorecard, "scorecard")
    kb_text = _read_text(knowledge_base, "knowledge_base")
    prompt_text = _read_text(prompt, "prompt")

    crud.upsert_campaign(
        db,
        name=campaign,
        prompt_text=prompt_text,
        scorecard_text=scorecard_text,
        kb_text=kb_text,
        prompt_filename=prompt.filename,
        scorecard_filename=scorecard.filename,
        kb_filename=knowledge_base.filename,
    )

    # Archive the raw uploads to MinIO campaigns/{name}/
    settings = get_settings()
    client = get_minio()
    archive = {
        "scorecard.txt": scorecard_text,
        "knowledge_base.txt": kb_text,
        "prompt.txt": prompt_text,
    }
    for fname, content in archive.items():
        data = content.encode("utf-8")
        client.put_object(
            settings.minio_bucket_campaigns,
            f"{campaign}/{fname}",
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )

    return CampaignUploadResponse(
        campaign=campaign,
        scorecard_chars=len(scorecard_text),
        kb_chars=len(kb_text),
        prompt_chars=len(prompt_text),
    )


@router.get("/list_campaigns", response_model=CampaignListResponse)
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = crud.list_campaigns(db)
    return CampaignListResponse(
        campaigns=[CampaignItem.model_validate(c) for c in campaigns]
    )


@router.get("/get_campaign", response_model=CampaignDetailResponse)
def get_campaign(
    campaign: str = Query(..., description="Nama campaign"),
    db: Session = Depends(get_db),
):
    """Return a campaign's full config (text content + original upload filenames)
    for the dashboard viewer."""
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
    dependencies=[Depends(get_spq_head_user)],
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