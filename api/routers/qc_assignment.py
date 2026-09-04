"""QC ticket assignment (Team Leader QC assigns a ticket to a QC).

One ticket -> one QC (reassignable). Managed by Team Leader QC (and SPQ Head). A QC
is then scoped to only their assigned tickets for Results / Statistics / appeals.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import QC_ASSIGNMENT_WRITE
from api.qc_scope import scoped_customer_ids
from api.rbac import require
from db import crud
from db.models import QcAssignment, User

router = APIRouter(dependencies=[Depends(get_current_user)])


def _assignment_dict(a) -> dict:
    return {
        "ticket_id": a.ticket_id,
        "qc_username": a.qc_username,
        "assigned_by_username": a.assigned_by_username,
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
    }


def _ensure_ticket_in_scope(db: Session, current_user, ticket_id: str) -> None:
    """403 bila ``ticket_id`` di luar cakupan pemanggil.

    Assignment memakai ticket id (prefix customer), sedangkan cakupan role sudah
    dinyatakan sebagai daftar ticket id yang sama oleh ``scoped_customer_ids`` —
    termasuk pembatasan CAMPAIGN. ``None`` = tanpa batas (SPQ Head / TL QC tanpa tag).
    """
    allowed = scoped_customer_ids(db, current_user)
    if allowed is None:
        return
    if (ticket_id or "").strip() not in set(allowed):
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
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Ticket -> QC assignments (newest first), DALAM CAKUPAN pemanggil.

    Dulu selalu seluruh tabel: seorang pengawas yang dipersempit ke satu campaign
    tetap membaca daftar ticket id campaign lain dari sini, padahal menu Results-nya
    sudah kosong."""
    allowed = scoped_customer_ids(db, current_user)
    rows = crud.list_qc_assignments(db)
    if allowed is not None:
        allowed_set = set(allowed)
        rows = [a for a in rows if (a.ticket_id or "").strip() in allowed_set]
    return [_assignment_dict(a) for a in rows]


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


def split_evenly(ticket_ids, qc_usernames) -> list:
    """Bagi ``ticket_ids`` ke ``qc_usernames``: [(ticket_id, qc_username), ...].

    ``floor(N/K)`` tiket per QC, dan SISANYA (``N mod K``) disebar satu-satu ke QC
    pertama — sehingga selisih beban antar-QC tidak pernah lebih dari satu ticket.
    Potongannya berurutan supaya urutan tabel tetap terbaca: QC pertama memegang
    tiket teratas.

    Aturan pertamanya menumpuk seluruh sisa ke QC TERAKHIR. Itu diganti setelah
    pembagian sungguhan pertama: 281 ticket ke 11 QC membuat satu orang menerima
    31 sementara yang lain 25 — dan karena urutan QC tetap, orang yang sama
    menanggung kelebihannya setiap hari.

    Saat tiket lebih sedikit daripada QC, ``base`` = 0 dan semuanya jadi sisa,
    jadi QC sebanyak jumlah tiket dapat satu-satu dan sisanya tidak kebagian —
    tanpa perlu aturan khusus.
    """
    n, k = len(ticket_ids), len(qc_usernames)
    if not n or not k:
        return []

    base, rem = divmod(n, k)
    pairs, cut = [], 0
    for pos, qc in enumerate(qc_usernames):
        take = base + (1 if pos < rem else 0)
        pairs.extend((tid, qc) for tid in ticket_ids[cut:cut + take])
        cut += take
    return pairs


@router.post("/qc_assignment/auto")
def auto_assign(
    ticket_ids: list = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Bagi rata ticket yang BELUM punya QC ke seluruh QC aktif.

    Satu permintaan, satu transaksi. Alternatifnya — browser mem-POST
    ``/qc_assignment`` sekali per tiket — berarti ratusan request yang bisa putus
    di tengah dan meninggalkan pembagian timpang yang tidak bisa diulang dengan
    aman.
    """
    allowed = scoped_customer_ids(db, current_user)
    allowed_set = None if allowed is None else set(allowed)

    requested = [(t or "").strip() for t in (ticket_ids or [])]
    taken = {
        row.ticket_id
        for row in db.query(QcAssignment.ticket_id)
        .filter(QcAssignment.ticket_id.in_(requested or [""]))
        .all()
    }
    pending = eligible_tickets(requested, allowed_set, taken)

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

    pairs = split_evenly(pending, [u.username for u in qcs])
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
        "per_qc": per_qc,
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
