"""Proxy ber-RBAC untuk ``/tickets-daily`` App C (Recording Tickets & Assign Ticket).

Kedua halaman itu dulu menembak App C langsung dari browser, jadi barisnya tidak
pernah melewati App B dan pembatasan campaign (``rbac.effective_campaigns_for``)
sama sekali tidak berlaku: login yang dibatasi ke campaign ``Collection`` tetap
melihat tiket ``ACT02`` dan ``LOC26``. Yang menyaring dulu hanyalah
``utils/campaignScope.js`` di dashboard, dan itu cuma mengisi DROPDOWN-nya —
barisnya lolos apa adanya.

Di sini permintaannya ikut sesi login, lalu barisnya disaring memakai peta
campaign->context (lihat ``api.campaign_context`` untuk alasan memakai ``context``
alih-alih kode campaign App C).

Endpoint ini TIDAK mengembalikan halaman App C apa adanya: penyaringan membuat
``total``/``page`` App C tidak lagi cocok dengan yang ditampilkan, jadi seluruh
baris dikumpulkan di ``services.tickets_daily.fetch_all`` lebih dulu dan dikirim
sekaligus. Pemanggil cukup satu request, tidak perlu paginasi sendiri.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import campaign_context as cc
from api.dependencies import get_current_user, get_db
from api.rbac import effective_campaigns_for
from qc_core.services import tickets_daily as tms

router = APIRouter(dependencies=[Depends(get_current_user)])

# Batas paginasi ke App C, dipisah per mode pemakaian.
#
# Tanpa filter pencarian, /tickets-daily memakai mode "yesterday" — ratusan baris,
# beberapa halaman saja; batas 100 hanya pengaman loop.
#
# Dengan filter ``tiket_id`` App C mencari di SEMUA tanggal dan bisa
# mengembalikan puluhan ribu baris. Batas
# ketat di sini menjaga satu request layar tidak berubah jadi 200+ panggilan HTTP
# beruntun; hasil yang terpotong ditandai ``truncated`` supaya layar bisa meminta
# pemakainya mempersempit pencarian, bukan diam-diam menampilkan sebagian.
MAX_PAGES_DEFAULT = 100
MAX_PAGES_SEARCH = 10


@router.get("/tickets_daily")
def list_tickets_daily(
    tiket_id: Optional[str] = Query(None, description="Substring tiket_id / id"),
    load_date: Optional[str] = Query(None, description="YYYY-MM-DD; kosong = H-1"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Baris /tickets-daily DALAM CAKUPAN campaign pemanggil.

    Balasan: ``{mode, load_date, items, total, truncated}``. ``total`` adalah
    jumlah baris SETELAH disaring — bukan ``total`` App C.

    Sengaja TIDAK ada parameter campaign. Cakupan campaign bukan pilihan pemakai,
    dan filter campaign pilihan-sendiri mustahil dinyatakan di sini: App C
    mencocokkannya dengan KODE (``ACT02``/``LOC26``/``CLENTB``), sedangkan yang
    dikenal pemakai App B adalah NAMA campaign (``Cashline``/``Collection``).
    """
    tiket_id = (tiket_id or "").strip() or None
    load_date = (load_date or "").strip() or None

    allowed = cc.contexts_for(
        effective_campaigns_for(db, current_user), cc.context_map_from_env()
    )
    # Cakupan kosong: tidak ada baris yang bisa lolos, jadi App C tidak perlu
    # ditembak sama sekali.
    if allowed is not None and not allowed:
        return {"mode": None, "load_date": load_date, "items": [], "total": 0, "truncated": False}

    max_pages = MAX_PAGES_SEARCH if tiket_id else MAX_PAGES_DEFAULT
    try:
        payload = tms.fetch_all(
            tiket_id=tiket_id, load_date=load_date, max_pages=max_pages
        )
    except tms.TicketsDailyError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal memuat data tiket dari App C: {exc}",
        ) from exc

    items = cc.filter_items(payload["items"], allowed)
    return {
        "mode": payload["mode"],
        "load_date": payload["load_date"],
        "items": items,
        "total": len(items),
        "truncated": payload["truncated"],
    }
