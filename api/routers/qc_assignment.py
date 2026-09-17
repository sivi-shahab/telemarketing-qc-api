"""QC ticket assignment (Team Leader QC assigns a ticket to a QC).

One ticket -> one QC (reassignable). Managed by Team Leader QC (and SPQ Head). A QC
is then scoped to only their assigned tickets for Results / Statistics / appeals.
"""
import random
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import QC_ASSIGNMENT_WRITE
from api.qc_scope import scoped_customer_ids, ticket_id_for_result
from api.rbac import collection_campaigns_from_env, effective_campaigns_for
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


def split_by_load(ticket_ids, qc_usernames, current_load=None, rnd=None) -> list:
    """Bagi ``ticket_ids`` ke ``qc_usernames`` MERATA ATAS TOTAL BEBAN:
    ``[(ticket_id, qc_username), ...]``.

    ``current_load`` = ``{qc_username: jumlah tiket yang SUDAH dipegang}``. Jatah
    dihitung dari angka itu, bukan dari nol: yang paling sedikit dapat lebih dulu,
    terus begitu sampai antreannya habis.

    Aturan sebelumnya (``split_evenly``) membagi rata PER BATCH — ``floor(N/K)`` per
    orang, sisa disebar satu-satu. Itu memang membuat selisih dalam satu batch tidak
    pernah lebih dari satu tiket, tetapi ia MENGAWETKAN ketimpangan yang sudah ada:
    QC yang memegang 40 dan QC yang memegang 10 tetap menerima jumlah yang sama pada
    batch berikutnya, jadi selisih 30 itu tidak pernah mengecil. Aturan bisnis
    4 September 2026 menutup celah itu dengan menghitung dari beban total.

    Urutan antreannya DIKOCOK dan seri diundi, supaya tidak ada QC yang selalu
    kebagian tiket tertua atau termuda, dan supaya nama pertama secara alfabetis
    tidak selalu unggul saat bebannya sama. ``rnd`` bisa diisi ``random.Random(seed)``
    agar hasilnya bisa diuji.

    QC yang tidak ada di ``current_load`` dianggap berbeban nol. Tanpa tiket atau
    tanpa QC hasilnya kosong.
    """
    if not ticket_ids or not qc_usernames:
        return []
    rnd = rnd or random.Random()
    load = {u: int((current_load or {}).get(u, 0)) for u in qc_usernames}
    pool = list(ticket_ids)
    rnd.shuffle(pool)
    pairs = []
    for tid in pool:
        low = min(load.values())
        candidates = [u for u, c in load.items() if c == low]
        owner = rnd.choice(candidates)
        load[owner] += 1
        pairs.append((tid, owner))
    return pairs


def current_assignment_load(db, qc_usernames) -> dict:
    """``{qc_username: jumlah tiket yang sedang dipegang}`` untuk ``split_by_load``.

    Dicocokkan case-insensitive, sama seperti ``assigned_ticket_ids_for_qc``.
    Assignment milik akun QC yang sudah nonaktif atau terhapus TIDAK dihitung —
    orangnya memang tidak ikut dibagi, jadi bebannya tidak boleh mempengaruhi jatah
    orang lain.
    """
    by_key = {u.casefold(): u for u in qc_usernames}
    load = {u: 0 for u in qc_usernames}
    for (owner,) in db.query(QcAssignment.qc_username).all():
        u = by_key.get((owner or "").strip().casefold())
        if u:
            load[u] += 1
    return load


def _active_qc_usernames(db) -> list:
    """Username QC aktif, urut nama — populasi penerima auto assign."""
    rows = (
        db.query(User)
        .filter(User.role == "qc", User.is_active == True)  # noqa: E712
        .order_by(User.name, User.username)
        .all()
    )
    return [(u.username or "").strip() for u in rows if (u.username or "").strip()]


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
    """
    results, _total = crud.list_results(
        db,
        campaigns=effective_campaigns_for(db, current_user),
        customer_ids=scoped_customer_ids(db, current_user),
        page=1,
        limit=1_000_000,
        exclude_uploaded_by_role="qc_support",
        # Campaign Collection tidak mengenal Assign Ticket (lihat
        # COLLECTION_REMOVED_PERMISSIONS) — tiketnya tidak boleh ikut dibagikan.
        exclude_campaigns=sorted(collection_campaigns_from_env()) or None,
    )
    # Satu ticket id bisa punya lebih dari satu baris Result (tiket dua-agent), dan
    # assignment-nya per TIKET — jadi di-unique-kan dulu, kalau tidak tiket yang sama
    # akan terhitung (dan menghabiskan jatah) dua kali.
    seen, ticket_ids = set(), []
    for r in results:
        tid = (ticket_id_for_result(r) or "").strip()
        if tid and tid not in seen:
            seen.add(tid)
            ticket_ids.append(tid)
    assigned_ids = {(a.ticket_id or "").strip() for a in crud.list_qc_assignments(db)}
    return ticket_ids, [t for t in ticket_ids if t not in assigned_ids]


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


@router.post("/qc_assignment/auto")
def auto_assign(
    ticket_ids: list | None = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require(QC_ASSIGNMENT_WRITE)),
):
    """Bagikan ticket yang BELUM punya QC ke seluruh QC aktif, acak dan merata.

    Merata atas TOTAL beban, bukan per batch: jatah dihitung dari jumlah tiket yang
    sudah dipegang tiap QC (aturan bisnis 4 September 2026 — lihat ``split_by_load``).

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
        allowed = scoped_customer_ids(db, current_user)
        allowed_set = None if allowed is None else set(allowed)
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

    # Jatah dihitung dari beban yang SUDAH dipegang tiap QC, bukan dibagi rata per
    # batch — lihat ``split_by_load``. Tanpa ini ketimpangan yang sudah ada tidak
    # pernah mengecil, berapa kali pun tombol ini ditekan.
    usernames = [u.username for u in qcs]
    pairs = split_by_load(pending, usernames, current_assignment_load(db, usernames))
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
