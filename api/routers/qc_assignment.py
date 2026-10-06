"""QC ticket assignment (Team Leader QC assigns a ticket to a QC).

One ticket -> one QC (reassignable). Managed by Team Leader QC (and SPQ Head). A QC
is then scoped to only their assigned tickets for Results / Statistics / appeals.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import campaign_context as cc
from api.dependencies import get_current_user, get_db
from api.permissions import QC_ASSIGNMENT_WRITE, SCOPE_ALL
from api.qc_scope import scoped_customer_ids, split_ticket_ids
from api.rbac import data_scope_for, effective_campaigns_for
from api.rbac import require
import qc_auto_assign as auto
from db import crud
from db.models import QcAssignment, User

router = APIRouter(dependencies=[Depends(get_current_user)])

_WIB = ZoneInfo("Asia/Jakarta")


def _wib_date(dt):
    """WIB calendar date for a naive-UTC ``assigned_at`` (None if missing)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_WIB).date()


def _parse_ymd(value):
    """Parse a 'YYYY-MM-DD' string into a date (None if missing/invalid)."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _assignment_dict(a) -> dict:
    return {
        "ticket_id": a.ticket_id,
        "qc_username": a.qc_username,
        "assigned_by_username": a.assigned_by_username,
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
    }


def _assignment_scope(db: Session, current_user):
    """Ticket id yang boleh di-assign / dibaca assignment-nya; ``None`` = tanpa batas.

    Assignment memakai ticket id (prefix customer), sedangkan cakupan role sudah
    dinyatakan sebagai daftar ticket id yang sama oleh ``scoped_customer_ids`` —
    termasuk pembatasan CAMPAIGN. ``None`` = tanpa batas (SPQ Head / TL QC tanpa tag).

    Pengecualiannya: cakupan ``all`` yang campaign-nya melihat SELURUH baris App C
    (grup ``Telemarketing``, lihat ``api.campaign_groups``) diperlakukan seperti Admin.
    Tiket di menu Assign Ticket berasal dari App C dan biasanya belum ada di tabel
    ``results``, jadi daftar ``scoped_customer_ids`` (yang dibangun dari ``results``)
    menolak setiap tiket yang ditampilkan menu itu sendiri. Cakupan lain
    (``qc_assigned`` dsb.) tidak dilebarkan.
    """
    allowed = scoped_customer_ids(db, current_user)
    if allowed is None:
        return None
    if data_scope_for(db, current_user) == SCOPE_ALL and cc.contexts_for(
        effective_campaigns_for(db, current_user), cc.context_map_from_env()
    ) is None:
        return None
    return set(allowed)


def _ensure_ticket_in_scope(db: Session, current_user, ticket_id: str) -> None:
    """403 bila ``ticket_id`` di luar cakupan pemanggil (``_assignment_scope``)."""
    allowed = _assignment_scope(db, current_user)
    if allowed is None:
        return
    if (ticket_id or "").strip() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini di luar campaign yang menjadi cakupan Anda",
        )


@router.get("/qc_assignment/qc_users")
def list_qc_users(
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """The QC users a ticket can be assigned to (role == qc, active)."""
    rows = (
        db.query(User)
        .filter(User.role == "qc", User.is_active == True)  # noqa: E712
        .order_by(User.name, User.username)
        .all()
    )
    return [{"username": u.username, "name": u.name} for u in rows]


@router.get("/qc_assignments")
def list_assignments(
    ticket_ids: Optional[str] = Query(None, description="Ticket id dipisah koma — hanya assignment ticket itu. Kosong = tidak ada yang diminta, BUKAN semua"),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Ticket -> QC assignments (newest first), DALAM CAKUPAN pemanggil.

    Dulu selalu seluruh tabel: seorang pengawas yang dipersempit ke satu campaign
    tetap membaca daftar ticket id campaign lain dari sini, padahal menu Results-nya
    sudah kosong.

    ``ticket_ids`` mempersempit lagi ke ticket yang benar-benar dibutuhkan pemanggil
    — menu Assign Ticket hanya menampilkan tiket satu hari, jadi tidak ada alasan
    mengirim seluruh riwayat assignment ke browser."""
    allowed = _assignment_scope(db, current_user)
    wanted = split_ticket_ids(ticket_ids)
    if wanted is not None and not wanted:
        return []
    rows = crud.list_qc_assignments(db)
    if allowed is not None:
        rows = [a for a in rows if (a.ticket_id or "").strip() in allowed]
    if wanted is not None:
        wanted_set = set(wanted)
        rows = [a for a in rows if (a.ticket_id or "").strip() in wanted_set]
    return [_assignment_dict(a) for a in rows]


@router.get("/qc_assignment/log")
def qc_assignment_log(
    date_start: Optional[str] = Query(None, description="Batas bawah tanggal assign (YYYY-MM-DD, WIB)"),
    date_end: Optional[str] = Query(None, description="Batas atas tanggal assign (YYYY-MM-DD, WIB)"),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Log assign QC per hari (WIB): tiket apa saja yang (saat ini) dipegang tiap
    QC, dikelompokkan berdasarkan tanggal assign/re-assign TERAKHIRnya.

    ``qc_assignments`` adalah tabel STATE (satu baris per tiket, di-UPSERT saat
    re-assign — lihat ``crud.assign_ticket_to_qc``), bukan tabel event. Jadi log ini
    menunjukkan kepemilikan tiket saat ini dikelompokkan menurut hari assign-nya,
    BUKAN riwayat lengkap setiap kali sebuah tiket berpindah tangan — re-assign
    sebelumnya tertimpa dan tidak lagi punya baris sendiri di sini.

    Cakupannya sama dengan ``GET /qc_assignments`` (``_assignment_scope``).
    """
    d_start = _parse_ymd(date_start)
    d_end = _parse_ymd(date_end)
    allowed = _assignment_scope(db, current_user)
    rows = crud.list_qc_assignments(db)
    if allowed is not None:
        rows = [a for a in rows if (a.ticket_id or "").strip() in allowed]

    usernames = {(a.qc_username or "").strip() for a in rows if (a.qc_username or "").strip()}
    names = {}
    if usernames:
        for u in db.query(User).filter(User.username.in_(list(usernames))).all():
            names[u.username] = u.name

    by_date: dict = {}
    for a in rows:
        d = _wib_date(a.assigned_at)
        if d is None:
            continue
        if d_start and d < d_start:
            continue
        if d_end and d > d_end:
            continue
        qc = (a.qc_username or "").strip()
        by_date.setdefault(d, {}).setdefault(qc, []).append(a.ticket_id)

    days = []
    for d in sorted(by_date.keys(), reverse=True):
        qc_list = [
            {
                "qc_username": u,
                "qc_name": names.get(u) or u,
                "count": len(tids),
                "ticket_ids": sorted(tids),
            }
            for u, tids in by_date[d].items()
        ]
        qc_list.sort(key=lambda x: (x["qc_name"] or "").lower())
        days.append({
            "date": d.isoformat(),
            "total": sum(x["count"] for x in qc_list),
            "qc": qc_list,
        })

    return {
        "date_start": d_start.isoformat() if d_start else None,
        "date_end": d_end.isoformat() if d_end else None,
        "days": days,
    }


@router.post("/qc_assignment")
def assign_ticket(
    ticket_id: str = Form(...),
    qc_username: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Assign (or reassign) a ticket to a QC user."""
    ticket_id = (ticket_id or "").strip()
    qc_username = (qc_username or "").strip()
    if not ticket_id or not qc_username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ticket_id dan qc_username wajib diisi")
    _ensure_ticket_in_scope(db, current_user, ticket_id)
    qc = db.query(User).filter(User.username == qc_username, User.role == "qc").first()
    if qc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User QC tidak ditemukan")
    a = crud.assign_ticket_to_qc(db, ticket_id, qc_username, assigned_by_username=current_user.username)
    return _assignment_dict(a)


def eligible_tickets(requested, allowed, already_assigned) -> list:
    """Ticket id yang boleh ikut dibagi, urutannya dipertahankan.

    ``allowed`` = cakupan campaign pemanggil (``None`` = tanpa batas, set KOSONG =
    tidak boleh apa pun — bedanya dijaga sampai di sini). Daftar yang dikirim
    browser tidak dipercaya: halaman bisa saja menampilkan baris lama, dan
    permintaan bisa dikarang sendiri.

    Yang SUDAH punya QC dibuang, bukan ditimpa. Tombol ini membagi sisa pekerjaan;
    mengacak ulang tiket yang sedang atau sudah diperiksa orang bukan tugasnya.
    """
    out, seen = [], set()
    for raw in requested or []:
        tid = (raw or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        if allowed is not None and tid not in allowed:
            continue
        if tid in already_assigned:
            continue
        out.append(tid)
    return out


_active_qc_usernames = auto.active_qc_usernames


def _auto_assign_pool(db, current_user):
    """``(ticket_ids, pool)`` untuk auto assign, DALAM CAKUPAN pemanggil.

    Dipakai bersama oleh hitungan pratinjau (``GET /qc_assignment/unassigned``) dan
    pembagian sebenarnya — sengaja satu fungsi, karena angka "sekian ticket belum
    di-assign" yang dibaca orang sebelum menekan tombol HARUS berasal dari himpunan
    yang sama dengan yang nanti dibagikan. Menghitungnya dua kali dengan dua definisi
    adalah cara paling mudah membuat layar berbohong.

    Populasinya = daftar Results dalam cakupan pemanggil, sama dengan yang ditampilkan
    menu Assign Ticket (upload QC Support dikecualikan di sana juga). ``limit`` sengaja
    dibuka lebar: yang perlu dibagi adalah SELURUH antrean, bukan satu halaman — dan
    itulah bedanya dengan daftar ~100 baris yang termuat di layar.

    Definisinya tinggal di ``qc_auto_assign.unassigned_pool`` supaya batch terjadwal
    di worker memakai himpunan yang sama (termasuk pengecualian Collection).
    """
    return auto.unassigned_pool(
        db,
        campaigns=effective_campaigns_for(db, current_user),
        customer_ids=scoped_customer_ids(db, current_user),
    )


@router.get("/qc_assignment/unassigned")
def unassigned_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Berapa ticket yang BELUM di-assign dalam cakupan pemanggil (pratinjau tombol).

    Angka ini beda dengan hitungan "x / y ticket" di toolbar menu Assign Ticket: yang
    di sana hanya ticket yang termuat di tabel, sedangkan yang di sini — dan yang
    dibagikan Auto Assign tanpa ``ticket_ids`` — adalah SELURUH antrean dalam cakupan.
    Tanpa endpoint ini layarnya tidak punya cara menyebut angka yang benar sebelum
    tombolnya ditekan.

    Bacaan murni; tidak mengubah apa pun.
    """
    ticket_ids, pool = _auto_assign_pool(db, current_user)
    return {
        "unassigned": len(pool),
        "assigned": len(ticket_ids) - len(pool),
        "total": len(ticket_ids),
        "qc_count": len(_active_qc_usernames(db)),
    }


@router.get("/qc_assignment/schedule")
def auto_assign_schedule(current_user=Depends(require(QC_ASSIGNMENT_WRITE))):
    """Jadwal batch auto assign otomatis + batch berikutnya (untuk countdown di layar).

    ``enabled`` mengikuti ``QC_AUTO_ASSIGN_ENABLED`` di env API — isi sama dengan env
    worker, kalau tidak layar menghitung mundur ke batch yang tidak akan jalan.
    ``now`` ikut dikirim supaya countdown memakai jam server, bukan jam browser.
    """
    now = datetime.now(timezone.utc)
    nxt = auto.next_run(now)
    return {
        "enabled": auto.schedule_enabled(),
        "timezone": "Asia/Jakarta",
        "slots": auto.schedule_labels(),
        "now": now.isoformat(),
        "next_run_at": nxt.isoformat(),
        "seconds_until_next": max(0, int((nxt - now).total_seconds())),
    }


@router.post("/qc_assignment/auto")
def auto_assign(
    ticket_ids: list | None = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Bagikan ticket yang BELUM punya QC ke seluruh QC aktif, acak dan merata.

    Merata per MOMEN tombol ditekan, di antara QC yang aktif saat itu (2 Oktober
    2026, mengganti aturan "merata atas total beban" 4 September) — lihat
    ``qc_auto_assign.distribute_evenly``. Aturan yang sama dipakai batch terjadwal.

    Satu permintaan, satu transaksi. Alternatifnya — browser mem-POST
    ``/qc_assignment`` sekali per tiket — berarti ratusan request yang bisa putus
    di tengah dan meninggalkan pembagian timpang yang tidak bisa diulang dengan
    aman.
    """
    # ``ticket_ids`` OPSIONAL. Dikirim -> hanya itu yang dibagi (daftar yang termuat
    # layar; jalur yang dipakai dashboard hari ini). Tidak dikirim -> server memakai
    # SELURUH antrean dalam cakupan pemanggil, lewat himpunan yang sama dengan
    # pratinjau ``GET /qc_assignment/unassigned``.
    scope_ticket_ids = None
    if ticket_ids:
        allowed_set = _assignment_scope(db, current_user)
        requested = [(t or "").strip() for t in ticket_ids]
        taken = {
            row.ticket_id
            for row in db.query(QcAssignment.ticket_id)
            .filter(QcAssignment.ticket_id.in_(requested or [""]))
            .all()
        }
        pending = eligible_tickets(requested, allowed_set, taken)
    else:
        scope_ticket_ids, pending = _auto_assign_pool(db, current_user)
        requested = list(pending)

    qcs = (
        db.query(User)
        .filter(User.role == "qc", User.is_active == True)  # noqa: E712
        .order_by(User.name, User.username)
        .all()
    )
    if not qcs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tidak ada user QC aktif untuk dibagikan.",
        )

    # Rata di antara QC aktif SAAT INI; beban lama tidak dihitung (2 Oktober 2026).
    usernames = [u.username for u in qcs]
    pairs = auto.distribute_evenly(pending, usernames)
    assigned_at = datetime.utcnow()
    for tid, qc_username in pairs:
        db.add(QcAssignment(
            ticket_id=tid,
            qc_username=qc_username,
            assigned_by_username=current_user.username,
            assigned_at=assigned_at,
        ))
    try:
        db.commit()
    except IntegrityError:
        # ``ticket_id`` unik: orang lain meng-assign salah satunya di sela
        # pembacaan dan penulisan ini. Batalkan seluruhnya — pembagian setengah
        # jadi lebih sulit dibereskan daripada mengulang dari awal.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ada ticket yang baru saja di-assign orang lain. Muat ulang, lalu coba lagi.",
        )

    per_qc: dict = {}
    for tid, qc_username in pairs:
        per_qc.setdefault(qc_username, []).append(tid)
    return {
        "assigned": len(pairs),
        "skipped": len(set(requested) - set(pending)),
        "qc_count": len(qcs),
        "assigned_at": assigned_at.isoformat(),
        # ``{qc_username: [ticket_id, ...]}`` — daftar id, BUKAN jumlah. Layar memakai
        # ini untuk memperbarui baris yang benar-benar berpindah tanpa memuat ulang.
        "per_qc": per_qc,
        # Tiga angka tambahan untuk layar yang memanggil TANPA ticket_ids; pemanggil
        # lama boleh mengabaikannya.
        "pool": len(pending),
        "unassigned_left": len(pending) - len(pairs),
        "total": len(scope_ticket_ids) if scope_ticket_ids is not None else len(requested),
    }


@router.delete("/qc_assignment/{ticket_id}")
def remove_assignment(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Unassign a ticket (QC then no longer sees it)."""
    _ensure_ticket_in_scope(db, current_user, ticket_id)
    removed = crud.unassign_ticket(db, ticket_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment tidak ditemukan")
    return {"ticket_id": ticket_id.strip(), "removed": True}


@router.delete("/qc_assignment")
def remove_all_assignments(
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Lepas SEMUA assignment QC sekaligus, dalam cakupan pemanggil (tombol "Lepas
    Semua" di menu Assign Ticket, 25 September 2026).

    Cakupannya SAMA persis dengan ``_ensure_ticket_in_scope``/daftar Results yang
    tampil di menu ini — ``scoped_customer_ids`` (sudah memasukkan pembatasan
    CAMPAIGN role), jadi pengawas yang dipersempit ke satu campaign tidak bisa
    ikut melepas assignment campaign lain lewat tombol ini. ``None`` (tanpa
    pembatasan role) berarti benar-benar SEMUA baris di tabel.

    Hanya menghapus kepemilikan tiket, BUKAN riwayat Manual Status yang sudah
    di-submit QC — sama seperti melepas satu tiket lewat endpoint di atas, hanya
    dikerjakan sekaligus dan dalam satu commit.
    """
    allowed = scoped_customer_ids(db, current_user)
    removed = crud.bulk_unassign_tickets(db, allowed)
    return {"removed": removed}
