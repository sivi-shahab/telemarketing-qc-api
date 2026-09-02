"""Menu "Reprocess All Ticket" (grup Upload Data, khusus Admin).

Memproses ULANG seluruh tiket sebuah campaign memakai konfigurasi campaign yang
berlaku SEKARANG — prompt, scorecard, dan KB terbaru di tabel ``campaigns`` — lalu
membuang baris lama tiap ticket id sehingga tersisa tepat satu baris per unique id.

Yang penting dipahami sebelum menyentuh berkas ini:

* **Satu panggilan LLM per unique ticket id.** Tombolnya murah ditekan, jalannya
  mahal. Karena itu endpoint start menolak kalau masih ada job ``running``
  (409), dan layarnya menampilkan ongkos (jumlah tiket) sebelum dijalankan.
* **Penghapusan tidak pernah mendahului keberhasilan.** Baris lama sebuah ticket id
  hanya dihapus setelah baris barunya berstatus ``done`` — lihat
  ``worker.tasks.reprocess_ticket``. Tiket yang gagal ditinggalkan persis seperti
  semula dan dilaporkan pada ringkasan job.
* **Cakupan campaign tetap berlaku.** Sebuah campaign hanya bisa dipilih kalau
  memang masuk cakupan pemanggil (``effective_campaigns_for``), sama seperti seluruh
  dropdown Campaign lainnya.

Berkas ini juga melayani tombol **Reprocess** per tiket di menu Results
(``POST /reprocess_ticket``). Mesinnya sama persis — satu ``ReprocessJob`` berisi
tepat satu item — hanya ``scope``-nya ``"ticket"``, bukan ``"campaign"``. Penandaan
itu yang membuat layar "Reprocess All Ticket" tidak ikut menempel pada job satu-tiket
milik orang lain, sementara pengaman "satu job massal pada satu waktu" tetap melihat
kedua jenis job.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import ADMIN_TICKET_REPROCESS
from api.rbac import effective_campaigns_for, require
from api.schemas.reprocess import (
    ReprocessCampaignOption,
    ReprocessFilterPreviewResponse,
    ReprocessFilterRequest,
    ReprocessJobListResponse,
    ReprocessJobResponse,
    ReprocessPreviewResponse,
    ReprocessStartRequest,
)
from db import crud

router = APIRouter(dependencies=[Depends(require(ADMIN_TICKET_REPROCESS))])


def _allowed_campaign_names(db: Session, current_user) -> list[str]:
    """Nama campaign yang boleh dipilih pemanggil (urut abjad)."""
    allowed = effective_campaigns_for(db, current_user)
    names = [c.name for c in crud.list_campaigns(db)]
    if allowed is not None:
        keys = {(c or "").strip().casefold() for c in allowed}
        names = [n for n in names if (n or "").strip().casefold() in keys]
    return sorted(names, key=lambda n: (n or "").casefold())


def _job_response(db: Session, job, with_items: bool = True) -> ReprocessJobResponse:
    counts = crud.reprocess_job_counts(db, job.id)
    items = []
    if with_items:
        items = [
            {
                "id": it.id,
                "ticket_id": it.ticket_id,
                "campaign": it.campaign,
                "status": it.status,
                "new_result_id": str(it.new_result_id) if it.new_result_id else None,
                "deleted_old": it.deleted_old or 0,
                "error_message": it.error_message,
                "finished_at": it.finished_at,
            }
            for it in crud.reprocess_job_items(db, job.id)
        ]
    return ReprocessJobResponse(
        job_id=str(job.id),
        campaigns=list(job.campaigns or []),
        status=job.status,
        total_tickets=job.total_tickets or 0,
        counts=counts,
        created_by_username=job.created_by_username,
        created_at=job.created_at,
        finished_at=job.finished_at,
        items=items,
    )


def _running_job(db: Session, scope: str = None):
    return crud.running_reprocess_job(db, scope=scope)


# Sebanyak-banyaknya baris yang diambil saat menerjemahkan filter layar menjadi
# daftar tiket. Jauh di atas isi tabel sekarang; ada sebagai rem, bukan paginasi —
# Reprocess All memang harus melihat SELURUH yang cocok, bukan satu halaman.
_FILTER_ROW_CAP = 1_000_000


def _plan_for_filtered(db: Session, current_user, filters: dict):
    """Rencana reproses untuk tiket yang cocok dengan filter menu Results.

    Mengembalikan ``(plan, skipped)``.

    Dua hal yang membuat fungsi ini ada, dan keduanya soal kepercayaan:

    1. **Daftar tiketnya datang dari ``stats._resolve_filtered_results``**, yaitu
       jalur yang SAMA dengan ``/list_results``. Filter ``ai_status`` dan
       ``manual_status`` diturunkan di Python, bukan di SQL, jadi menulis query
       sendiri di sini akan membuat angka di modal konfirmasi berbeda dari tiket
       yang benar-benar dikerjakan. Cakupan campaign & ``data_scope`` role ikut
       terbawa dari sana, jadi tidak ada jalan pintas RBAC.
    2. **Tiket yang sudah punya item reproses aktif DILEWATI**, bukan membuat
       seluruh perintah ditolak. Bahaya sesungguhnya adalah dua job menyentuh row
       tiket yang sama: keduanya membekukan ``old_result_ids`` yang beririsan, dan
       yang kalah cepat mencoba menghapus row yang sudah tidak ada. Itu bisa
       dicegah dengan tepat sasaran, tanpa memblokir tiket lain yang tidak
       bersinggungan sama sekali.

    Dipanggil ULANG oleh endpoint POST, bukan mempercayai angka dari preview: ada
    jeda antara Admin membaca modal dan menekan tombolnya, dan job baru bisa
    muncul di sela itu.
    """
    from api.routers import stats

    rows, _ = stats._resolve_filtered_results(
        db, current_user, page=1, limit=_FILTER_ROW_CAP, **filters
    )
    tids = []
    for row in rows:
        tid = stats._customer_id_from_files(row.source_files)
        if tid and tid not in tids:
            tids.append(tid)
    if not tids:
        return [], 0

    busy = crud.active_reprocess_ticket_ids(db, tids)
    wanted = [t for t in tids if t not in busy]
    plan = crud.reprocess_plan_for_tickets(db, wanted)
    # `skipped` dihitung dari tiket yang bentrok, BUKAN dari selisih panjang
    # rencana: tiket yang barisnya terhapus di sela juga menyusutkan rencana, dan
    # menyebutnya "dilewati karena sedang direproses" akan menyesatkan.
    return plan, len(tids) - len(wanted)


@router.get("/reprocess_preview", response_model=ReprocessPreviewResponse)
def reprocess_preview(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Daftar campaign + ongkosnya, untuk checkbox di layar.

    ``tickets`` adalah jumlah UNIQUE ticket id (= jumlah panggilan LLM), sedangkan
    ``obsolete`` adalah baris berlebih yang akan hilang setelah job selesai. Kedua
    angka itu dihitung dengan pengelompokan yang sama persis dengan job-nya
    (``crud.reprocess_ticket_plan``), jadi apa yang ditawarkan layar adalah apa yang
    benar-benar dikerjakan.
    """
    names = _allowed_campaign_names(db, current_user)
    options = []
    for name in names:
        plan = crud.reprocess_ticket_plan(db, [name])
        results = sum(len(p["old_result_ids"]) for p in plan)
        options.append(
            ReprocessCampaignOption(
                campaign=name,
                tickets=len(plan),
                results=results,
                obsolete=results - len(plan),
            )
        )
    # Sengaja hanya job massal: layar ini tidak punya tempat untuk menampilkan job
    # satu-tiket yang dijalankan dari menu Results, dan menempel padanya hanya akan
    # menampilkan progres milik tiket orang lain.
    running = _running_job(db, scope="campaign")
    return ReprocessPreviewResponse(
        campaigns=options,
        running_job_id=str(running.id) if running else None,
    )


@router.post("/reprocess_tickets", response_model=ReprocessJobResponse)
def reprocess_tickets(
    body: ReprocessStartRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mulai satu job reproses untuk campaign yang dipilih."""
    picked = [c.strip() for c in (body.campaigns or []) if (c or "").strip()]
    if not picked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pilih minimal satu campaign",
        )

    allowed = {n.casefold() for n in _allowed_campaign_names(db, current_user)}
    outside = [c for c in picked if c.casefold() not in allowed]
    if outside:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Campaign di luar cakupan Anda: " + ", ".join(sorted(outside)),
        )

    # Satu job berjalan pada satu waktu: dua job paralel pada campaign yang sama
    # akan membekukan daftar row lama yang saling tumpang tindih, dan yang kalah
    # cepat akan mencoba menghapus row yang sudah tidak ada. Biayanya pun berlipat.
    running = _running_job(db)
    if running is not None:
        kind = (
            "reproses satu tiket" if running.scope == "ticket" else "reproses massal"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Masih ada job {kind} yang berjalan (job {running.id}).",
        )

    plan = crud.reprocess_ticket_plan(db, picked)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada tiket pada campaign yang dipilih",
        )

    job = crud.create_reprocess_job(
        db, picked, plan, getattr(current_user, "username", None)
    )

    from api.celery_client import celery_app

    for item in crud.reprocess_job_items(db, job.id):
        celery_app.send_task(
            "worker.tasks.reprocess_ticket.reprocess_ticket", args=[item.id]
        )

    return _job_response(db, job)


@router.post("/reprocess_ticket", response_model=ReprocessJobResponse)
def reprocess_single_ticket(
    ticket_id: str = Query(..., description="Ticket id (prefix sebelum '_' pada nama file) yang akan diproses ulang"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Proses ulang SATU ticket id (tombol Reprocess di menu Results).

    Membuat job ber-``scope="ticket"`` dengan tepat satu item, lalu mengirim task
    Celery yang sama dengan job massal. Urutannya karena itu identik: row baru
    dievaluasi dulu dengan konfigurasi campaign yang berlaku sekarang, dan SELURUH
    row lama tiket itu baru dihapus setelah row barunya berstatus ``done`` —
    menyisakan tepat satu row. Kalau gagal, row baru dibuang dan row lama tetap utuh.

    Respons kembali SEGERA (job masih ``running``); layar memantaunya lewat
    ``GET /reprocess_job/{job_id}``.
    """
    plan = crud.reprocess_plan_for_ticket(db, ticket_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tidak ada entry untuk ticket '{(ticket_id or '').strip()}'",
        )

    # Cakupan campaign: tiket di luar campaign pemanggil tidak boleh disentuh, sama
    # seperti pada job massal. Row tanpa campaign tidak bisa direproses — konfigurasi
    # prompt/scorecard-nya tidak diketahui.
    campaign = (plan.get("campaign") or "").strip()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ticket ini tidak punya campaign, jadi tidak bisa diproses ulang.",
        )
    allowed = {n.casefold() for n in _allowed_campaign_names(db, current_user)}
    if campaign.casefold() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Campaign di luar cakupan Anda: {campaign}",
        )

    # Tiket yang sama tidak boleh diantre dua kali: row lama yang dibekukan pada job
    # pertama akan sudah terhapus saat job kedua mencoba menghapusnya, dan tiket itu
    # berakhir dengan dua row baru.
    active = crud.active_reprocess_item_for_ticket(db, plan["ticket_id"])
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ticket '{plan['ticket_id']}' sedang diproses ulang.",
        )

    # Job massal pada campaign yang sama sudah membekukan row lama tiket ini; jangan
    # bertabrakan dengannya. Job satu-tiket lain (tiket berbeda) dibiarkan jalan
    # berbarengan — ongkosnya satu panggilan LLM dan tidak ada row yang beririsan.
    bulk = _running_job(db, scope="campaign")
    if bulk is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Masih ada job reproses massal yang berjalan (job {bulk.id}).",
        )

    job = crud.create_reprocess_job(
        db, [campaign], [plan], getattr(current_user, "username", None), scope="ticket"
    )

    from api.celery_client import celery_app

    for item in crud.reprocess_job_items(db, job.id):
        celery_app.send_task(
            "worker.tasks.reprocess_ticket.reprocess_ticket", args=[item.id]
        )

    return _job_response(db, job)


@router.post("/reprocess_filter_preview", response_model=ReprocessFilterPreviewResponse)
def reprocess_filter_preview(
    body: ReprocessFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ongkos tombol Reprocess All SEBELUM dijalankan — tanpa efek samping apa pun.

    POST, bukan GET, semata karena filternya sebuah objek: layar mengirim
    ``buildParams()`` apa adanya sehingga tidak ada pemetaan nama yang bisa
    diam-diam menjatuhkan satu filter.

    Angka di sini dihitung dengan ``_plan_for_filtered`` yang sama persis dengan
    endpoint POST-nya, jadi yang dibaca Admin di modal adalah yang dikerjakan.
    """
    plan, skipped = _plan_for_filtered(db, current_user, body.model_dump(exclude_none=True))
    campaigns = sorted({(p.get("campaign") or "").strip() for p in plan} - {""})
    running = _running_job(db, scope="campaign")
    return ReprocessFilterPreviewResponse(
        matched=len(plan) + skipped,
        skipped=skipped,
        will_process=len(plan),
        campaigns=campaigns,
        running_job_id=str(running.id) if running else None,
    )


@router.post("/reprocess_filtered", response_model=ReprocessJobResponse)
def reprocess_filtered(
    body: ReprocessFilterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Proses ulang SELURUH tiket yang cocok dengan filter menu Results.

    Satu panggilan LLM per tiket, jadi tombolnya murah ditekan dan jalannya mahal —
    layar wajib menampilkan ``/reprocess_filter_preview`` lebih dulu.

    Rencananya dihitung ULANG di sini, bukan diambil dari preview: ada jeda antara
    Admin membaca modal dan menekan tombolnya, dan job baru bisa muncul di sela itu.
    """
    plan, _skipped = _plan_for_filtered(db, current_user, body.model_dump(exclude_none=True))
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada tiket yang cocok dengan filter (atau semuanya sedang diproses ulang).",
        )

    # Job massal lain yang berjalan tetap ditolak. Yang DILEWATI per tiket hanyalah
    # bentrokan row (lihat _plan_for_filtered); dua perintah massal sekaligus soal
    # lain: tiketnya beririsan berat dan ongkos LLM-nya berlipat.
    bulk = _running_job(db, scope="campaign")
    if bulk is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Masih ada job reproses massal yang berjalan (job {bulk.id}).",
        )

    # ``campaigns`` job diisi campaign yang benar-benar tersentuh, bukan filter yang
    # diketik: filter campaign boleh kosong (= semua), dan ringkasan job tetap harus
    # bisa menjawab "ini menyentuh apa saja".
    campaigns = sorted({(p.get("campaign") or "").strip() for p in plan} - {""})
    job = crud.create_reprocess_job(
        db, campaigns, plan, getattr(current_user, "username", None), scope="campaign"
    )

    from api.celery_client import celery_app

    for item in crud.reprocess_job_items(db, job.id):
        celery_app.send_task(
            "worker.tasks.reprocess_ticket.reprocess_ticket", args=[item.id]
        )

    return _job_response(db, job)


@router.get("/reprocess_jobs", response_model=ReprocessJobListResponse)
def list_reprocess_jobs(
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Job terakhir (tanpa daftar item) — dipakai layar untuk menyambung kembali
    job yang masih berjalan setelah halaman di-refresh."""
    jobs = crud.list_reprocess_jobs(db, limit=limit, scope="campaign")
    return ReprocessJobListResponse(
        jobs=[_job_response(db, j, with_items=False) for j in jobs]
    )


@router.get("/reprocess_job/{job_id}", response_model=ReprocessJobResponse)
def get_reprocess_job(job_id: str, db: Session = Depends(get_db)):
    job = crud.get_reprocess_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan")
    return _job_response(db, job)


@router.post("/reprocess_job/{job_id}/cancel", response_model=ReprocessJobResponse)
def cancel_reprocess_job(job_id: str, db: Session = Depends(get_db)):
    """Batalkan job: tiket yang BELUM mulai dilewati.

    Tiket yang sedang diproses dibiarkan selesai — panggilan LLM-nya sudah terlanjur
    dibayar, dan menghentikannya di tengah jalan hanya membuang hasilnya.
    """
    job = crud.get_reprocess_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job tidak ditemukan")
    job = crud.cancel_reprocess_job(db, job_id)
    return _job_response(db, job)
