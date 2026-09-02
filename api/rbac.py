"""Penegakan permission berbasis tabel ``roles``.

Gate di seluruh API dulu berbentuk ``if current_user.role not in (...)``. Bentuk itu
membuat role baru mustahil: apa pun yang dibuat lewat Manage Role otomatis ditolak
semua endpoint. Di sini pengecekannya dipindah ke capability, sehingga role baru
cukup membawa daftar permission-nya sendiri.

Pemakaian di router::

    from api.rbac import require
    from api.permissions import ADMIN_USER_WRITE

    @router.post("/create_user", dependencies=[Depends(require(ADMIN_USER_WRITE))])

atau saat butuh objek user-nya::

    current_user=Depends(require(ADMIN_USER_WRITE))

Definisi role di-cache di proses selama ``_TTL_SECONDS``; tulisan lewat Manage Role
memanggil ``invalidate()`` supaya perubahan langsung terasa. TTL-nya tetap ada
sebagai jaring pengaman kalau API dijalankan lebih dari satu proses — cache basi
paling lama sepuluh detik.
"""
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api import permissions as perms
from compliance.campaign_kind import is_collection, parse_collection_campaigns

_TTL_SECONDS = 10.0
# key -> {"permissions": set, "data_scope": str, "campaigns": [str]}
_cache: dict = {}
_cache_at: float = 0.0


def invalidate() -> None:
    """Buang cache definisi role (dipanggil setelah role ditulis)."""
    global _cache, _cache_at
    _cache = {}
    _cache_at = 0.0


def _load_all(db: Session) -> dict:
    global _cache, _cache_at
    now = time.monotonic()
    if _cache and (now - _cache_at) < _TTL_SECONDS:
        return _cache

    from db.models import Role, RoleCampaign

    out = {}
    by_id = {}
    for r in db.query(Role).all():
        entry = {
            "permissions": set(r.permissions or []),
            "data_scope": r.data_scope or perms.SCOPE_ALL,
            "campaigns": [],
            "label": r.label,
            "is_system": bool(r.is_system),
        }
        out[r.key] = entry
        by_id[r.id] = entry
    for role_id, campaign in db.query(RoleCampaign.role_id, RoleCampaign.campaign).all():
        entry = by_id.get(role_id)
        if entry is not None:
            entry["campaigns"].append(campaign)

    _cache = out
    _cache_at = now
    return out


def _role_def(db: Session, role_key: Optional[str]) -> dict:
    """Definisi satu role. Role yang tidak ada di DB TIDAK diberi hak apa pun —
    gagal tertutup, bukan terbuka."""
    if not role_key:
        return {"permissions": set(), "data_scope": perms.SCOPE_ALL, "campaigns": []}
    defs = _load_all(db)
    found = defs.get(role_key)
    if found is not None:
        return found
    # Jaring pengaman kalau tabel roles belum ter-seed (mis. migrasi belum jalan):
    # pakai definisi bawaan di api/permissions.py agar sistem tidak mati total.
    fallback = perms.DEFAULT_ROLES.get(role_key)
    if fallback:
        return {
            "permissions": set(fallback["permissions"]),
            "data_scope": fallback["data_scope"],
            "campaigns": [],
        }
    return {"permissions": set(), "data_scope": perms.SCOPE_ALL, "campaigns": []}


def collection_campaigns_from_env() -> frozenset:
    """Nama campaign penagihan dari env ``COLLECTION_CAMPAIGNS``, dibaca tiap kali.

    Sengaja tidak di-cache, sama seperti ``api.campaign_context.context_map_from_env``:
    isinya sekecil ini, dan mengubah env lalu me-restart proses harus langsung
    terasa tanpa perlu mengingat ada cache di sini. Kosong = penyesuaian collection
    mati total dan tidak ada perilaku lama yang berubah — itu pula bentuk rollback-nya.
    """
    return parse_collection_campaigns(os.getenv("COLLECTION_CAMPAIGNS", ""))


def collection_adjusted_permissions(permissions, campaigns, collection_campaigns) -> set:
    """Capability setelah disesuaikan untuk login yang HANYA memegang collection.

    ``campaigns`` adalah hasil :func:`effective_campaigns_for`: ``None`` berarti
    tidak dibatasi, list berarti dibatasi. Penyesuaian hanya berlaku bila daftarnya
    TIDAK kosong dan SELURUH isinya campaign collection:

    * ``None`` (Admin, SPQ Head pusat) tidak disentuh — mereka mengurus kedua sisi.
    * list KOSONG berarti "dibatasi ke tidak ada campaign apa pun", bukan
      "dibatasi ke collection"; membedakannya penting, sama seperti di
      ``effective_campaigns_for``.
    * campuran Collection + Cashline tidak disentuh: orangnya masih memegang tiket
      Cashline, jadi alur Assign Ticket / Manual Check-nya masih dipakai.

    Selalu mengembalikan set BARU. Set masukan milik cache role di ``_load_all``
    dan dipakai bersama seluruh user ber-role sama — mengubahnya di tempat akan
    menular ke semua orang sampai cache-nya kedaluwarsa.
    """
    if not collection_campaigns or not campaigns:
        return set(permissions)
    if not all(is_collection(name, collection_campaigns) for name in campaigns):
        return set(permissions)
    return (set(permissions) - perms.COLLECTION_REMOVED_PERMISSIONS) | set(
        perms.COLLECTION_ADDED_PERMISSIONS
    )


def permissions_for(db: Session, user) -> set:
    """Capability efektif user — sumber tunggal untuk menu (``/auth/me``) MAUPUN
    gate endpoint (``require``).

    Penyesuaian collection ditempel di sini, bukan di sidebar, justru karena satu
    fungsi ini memberi makan keduanya: menunya hilang DAN endpoint-nya ikut
    tertutup, sehingga tidak bisa ditembus dengan mengetik URL-nya langsung.

    Harganya satu query berindeks tambahan per pemanggilan (``user_campaigns``
    lewat ``effective_campaigns_for``) — dibayar karena campaign efektif adalah
    properti ORANG, bukan properti role, sehingga tidak bisa ikut cache role.
    """
    base = _role_def(db, getattr(user, "role", None))["permissions"]
    collection = collection_campaigns_from_env()
    if not collection:
        return base
    return collection_adjusted_permissions(
        base, effective_campaigns_for(db, user), collection
    )


def data_scope_for(db: Session, user) -> str:
    return _role_def(db, getattr(user, "role", None))["data_scope"]


def campaigns_for(db: Session, user) -> list:
    """Campaign yang boleh dilihat user. List KOSONG = semua campaign."""
    return list(_role_def(db, getattr(user, "role", None))["campaigns"])


def user_campaigns_for(db: Session, user) -> list:
    """Campaign yang di-assign ke ORANG ini lewat tab "Assign Role" (tabel
    ``user_campaigns``). List KOSONG = tidak dibatasi di tingkat orang.

    Sengaja TIDAK ikut cache role: ini milik user, bukan role, dan jumlahnya kecil
    (satu query berindeks per pemanggilan)."""
    from db.models import UserCampaign

    uid = getattr(user, "id", None)
    if uid is None:
        return []
    rows = db.query(UserCampaign.campaign).filter(UserCampaign.user_id == uid).all()
    return [r[0] for r in rows]


def effective_campaigns_for(db: Session, user):
    """Campaign yang BENAR-BENAR dilihat user — inilah yang dipakai semua gate.

    Mengembalikan ``None`` bila TIDAK dibatasi, atau sebuah list bila dibatasi.
    Bedanya penting: list KOSONG berarti "dibatasi ke tidak ada apa pun" (tolak
    semuanya), bukan "semua campaign". Kalau keduanya disamakan, role yang
    seharusnya menyempitkan malah membuka segalanya.

    Bedanya dengan ``campaigns_for``: fungsi itu mengembalikan apa yang
    DIDEKLARASIKAN role, sedangkan ini menggabungkannya dengan tag campaign milik
    orangnya di Sales Database.

    Untuk cakupan sales, campaign adalah properti ORANG (kolom DEDICATED di roster),
    bukan properti role. Karena itu tidak perlu ada role terpisah per campaign:
    ``sales_agent`` yang sama melayani agent Cashline maupun NTB, dan cakupannya
    dibedakan oleh baris roster masing-masing. Lihat
    ``sales_lookup.roster_campaigns_for`` untuk alasan berbasis datanya.
    Pembatasan roster SELALU berlaku untuk cakupan sales — orang yang tidak ada di
    roster mendapat list kosong, artinya tidak melihat apa pun.

    Campaign pada role tetap dihormati, tetapi hanya sebagai BATAS ATAS: role boleh
    mempersempit di bawah tag roster (mis. role bespoke ``tl_ntb`` untuk membatasi
    seseorang), tidak pernah memperlebar. Role ``tl_ntb`` yang diberikan ke TL
    Cashline menghasilkan irisan kosong — dan itu berarti nol tiket.

    Untuk cakupan non-sales (``all`` / ``qc_assigned`` / ``qc_support_own``) roster
    tidak relevan: yang berlaku hanya deklarasi role, dan role tanpa deklarasi
    mendapat ``None``. Itulah sebabnya QC secara bawaan bisa di-assign tiket
    campaign mana pun.
    """
    declared = campaigns_for(db, user)
    scope = data_scope_for(db, user)
    assigned = user_campaigns_for(db, user)

    def _narrow(current):
        """Iris dengan assign per ORANG (tab "Assign Role"). Assign hanya boleh
        MEMPERSEMPIT: tanpa irisan ini, meng-assign campaign yang tidak dipegang
        role-nya justru akan memberi akses baru."""
        if not assigned:
            return current
        if current is None:
            return list(assigned)
        allowed = {(c or "").strip().casefold() for c in assigned}
        return [c for c in current if (c or "").strip().casefold() in allowed]

    if not perms.is_sales_scope(scope):
        return _narrow(declared or None)

    from sales_lookup import roster_campaigns_for

    roster = roster_campaigns_for(db, getattr(user, "username", "") or "", scope)
    if not declared:
        return _narrow(roster)
    allowed = {(c or "").strip().casefold() for c in declared}
    return _narrow([c for c in roster if c in allowed])


def role_label_for(db: Session, user) -> str:
    """Nama tampilan role (mis. "Team Leader QC"), untuk badge di dashboard."""
    key = getattr(user, "role", None) or ""
    return _role_def(db, key).get("label") or key


def has_perm(db: Session, user, permission: str) -> bool:
    return permission in permissions_for(db, user)


def require(*needed: str):
    """Dependency: tolak 403 kecuali user punya SEMUA permission ``needed``."""
    def _dep(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
        granted = permissions_for(db, current_user)
        missing = [p for p in needed if p not in granted]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: role Anda tidak memiliki izin untuk tindakan ini",
            )
        return current_user
    return _dep


def require_any(*needed: str):
    """Dependency: cukup punya SALAH SATU permission ``needed``."""
    def _dep(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
        granted = permissions_for(db, current_user)
        if not any(p in granted for p in needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: role Anda tidak memiliki izin untuk tindakan ini",
            )
        return current_user
    return _dep
