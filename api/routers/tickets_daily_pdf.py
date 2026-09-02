"""Proxy ber-RBAC untuk PDF transkrip App C (halaman detail transkrip).

Pasangan ``api/routers/tickets_daily.py``: yang itu menjaga DAFTAR barisnya, yang
ini menjaga BERKAS-nya. Keduanya menutup lubang yang sama — halaman yang menembak
App C langsung dari browser tidak pernah melewati ``rbac.effective_campaigns_for``,
dan membawa ``X-API-Key`` App C di dalam bundle JS-nya.

Cakupan campaign dicek lewat baris ``/tickets-daily`` milik tiket itu: field
``context``-nya dipetakan ke nama campaign App B (lihat ``api.campaign_context``
untuk alasan tidak memakai kode campaign App C). Pencarian itu hanya dilakukan
bila pemanggil MEMANG dibatasi — login tanpa batas (SPQ/admin, jalur paling
sering) tidak perlu membayar belasan request ke App C hanya untuk menyimpulkan
"boleh".

GAGAL TERTUTUP: tiket yang barisnya tidak ditemukan ditolak, bukan diloloskan.
Satu pencarian yang meleset tidak boleh cukup untuk menembus pembatasan campaign.
Yang dikembalikan 404, bukan 403, supaya jawabannya tidak sekaligus mengonfirmasi
bahwa tiket di luar cakupan itu ada.

Namanya ``/tickets_daily_pdf/``, BUKAN ``/transcript_pdf/``: nama kedua sudah
dipakai ``api/routers/transcript.py`` untuk hal yang sama sekali berbeda — PDF
transkrip milik App B sendiri, diambil dari MinIO per ``result_id``. Dua rute
dengan prefix yang sama membuat yang terdaftar belakangan tidak pernah
terjangkau, dan yang terdaftar belakangan adalah modul ini.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from api import campaign_context as cc
from api.dependencies import get_current_user, get_db
from api.rbac import effective_campaigns_for
from services import tickets_daily as tms
from services import view_streams as vs

router = APIRouter(dependencies=[Depends(get_current_user)])

# Batas paginasi saat mencari satu tiket di App C. Sama ketatnya dengan
# ``tickets_daily.MAX_PAGES_SEARCH``: pencarian tanpa tanggal menyapu SEMUA
# tanggal, dan satu permintaan layar tidak boleh berubah jadi ratusan request.
MAX_PAGES_LOOKUP = 10

_NOT_FOUND = "Transkrip tidak ditemukan atau di luar cakupan campaign Anda."


def _in_scope(tiket_id: str, allowed: frozenset) -> bool:
    """True bila baris App C milik ``tiket_id`` ber-context di dalam ``allowed``.

    ``allowed`` di sini SELALU sebuah set (pemanggil menangani kasus "tidak
    dibatasi" lebih dulu), termasuk set kosong yang berarti "tidak melihat apa
    pun".
    """
    if not allowed:
        return False
    try:
        payload = tms.fetch_all(tiket_id=tiket_id, max_pages=MAX_PAGES_LOOKUP)
    except tms.TicketsDailyError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal memeriksa cakupan tiket ke App C: {exc}",
        ) from exc

    # App C mencocokkan ``tiket_id`` sebagai SUBSTRING, jadi hasilnya bisa memuat
    # tiket lain. Yang dipakai hanya baris yang tiket_id-nya sama persis —
    # pencocokan longgar di sini akan meloloskan PDF milik tiket bertetangga.
    rows = [it for it in payload["items"] if str(it.get("tiket_id") or "") == tiket_id]
    return bool(cc.filter_items(rows, allowed))


@router.get("/tickets_daily_pdf/{tiket_id}")
def get_tickets_daily_pdf(
    tiket_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Response:
    """PDF transkrip ``tiket_id``, bila tiket itu ada di cakupan campaign pemanggil."""
    allowed = cc.contexts_for(
        effective_campaigns_for(db, current_user), cc.context_map_from_env()
    )
    if allowed is not None and not _in_scope(tiket_id, allowed):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)

    try:
        body = vs.fetch_pdf(tiket_id)
    except vs.ViewStreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal memuat PDF transkrip dari App C: {exc}",
        ) from exc

    return Response(
        content=body,
        media_type="application/pdf",
        # inline: berkasnya dirender pdf.js di dalam halaman, bukan diunduh.
        headers={"Content-Disposition": f'inline; filename="{tiket_id}.pdf"'},
    )
