"""Menu Manage Role — buat / ubah / hapus role dan batasi campaign-nya.

Endpoint di sini yang membuat "role" bisa dikelola operator, bukan lagi konstanta
di kode. Aturan pengamannya:

* Role sistem (``is_system``) tidak bisa dihapus dan ``key``-nya tidak bisa diubah,
  karena kolom historis (``results.uploaded_by_role``, ``qc_status_events.actor_role``)
  sudah menyimpan key tersebut.
* Role yang masih dipakai user tidak bisa dihapus — user-nya harus dipindah dulu.
* Pemegang ADMIN_ROLE_WRITE tidak bisa mencabut ADMIN_ROLE_WRITE dari role dirinya
  sendiri; tanpa itu tidak ada seorang pun yang bisa mengelola role lagi.
* Campaign KOSONG = semua campaign. Ini bawaan setiap role, termasuk ``qc``.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import permissions as P
from api.dependencies import get_db
from api.rbac import invalidate, require
from sales_lookup import roster_campaign_index
from api.schemas.role import (
    RoleCreate,
    UserCampaignItem,
    UserCampaignListResponse,
    UserCampaignUpdate,
    RoleDetail,
    RoleListResponse,
    RoleUpdate,
    PermissionCatalog,
    RosterPerson,
    RosterTag,
)
from db.models import Campaign, Role, RoleCampaign, User, UserCampaign

router = APIRouter(prefix="/roles", tags=["roles"])

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")

# Di bawah ambang ini, rincian per ORANG lebih informatif daripada tally per campaign.
# Area Manager (5 orang) masuk; Team Leader (15) dan Sales Agent (379) tidak.
_PEOPLE_LIST_MAX = 10


def _detail(db: Session, role: Role, index_cache: dict = None) -> RoleDetail:
    campaigns = [
        rc.campaign
        for rc in db.query(RoleCampaign).filter(RoleCampaign.role_id == role.id).all()
    ]
    people = db.query(User.username, User.name).filter(User.role == role.key).all()
    usernames = [u.username for u in people]

    # Untuk cakupan sales, campaign datang dari tag roster tiap ORANG — bukan dari
    # role. Merangkumnya di sini membuat keterangan "ikut tag roster" jadi konkret:
    # terlihat satu role sales_agent memang melayani tujuh campaign sekaligus, dan
    # terlihat pula berapa user yang NIP-nya tidak ada di roster (tidak melihat
    # tiket apa pun).
    roster_tags: list = []
    roster_people: list = []
    without_tag = 0
    if P.is_sales_scope(role.data_scope):
        if index_cache is None:
            index_cache = {}
        if role.data_scope not in index_cache:
            index_cache[role.data_scope] = roster_campaign_index(db, role.data_scope)
        index = index_cache[role.data_scope]
        # Batas atas dari role tetap dihormati: kalau role membatasi campaign,
        # ringkasannya harus mencerminkan yang benar-benar berlaku, bukan tag mentah.
        allowed = {(c or "").strip().casefold() for c in campaigns} if campaigns else None
        tally: dict = {}
        for un in usernames:
            tags = index.get((un or "").strip().casefold(), [])
            if allowed is not None:
                tags = [t for t in tags if t in allowed]
            if not tags:
                without_tag += 1
                continue
            for t in tags:
                tally[t] = tally.get(t, 0) + 1
        roster_tags = [
            RosterTag(campaign=c, users=n)
            for c, n in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        if 0 < len(people) <= _PEOPLE_LIST_MAX:
            for un, nm in people:
                tags = index.get((un or "").strip().casefold(), [])
                if allowed is not None:
                    tags = [t for t in tags if t in allowed]
                roster_people.append(RosterPerson(
                    username=un, name=(nm or un), campaigns=tags))
            roster_people.sort(key=lambda x: x.name.casefold())

    return RoleDetail(
        id=role.id,
        key=role.key,
        label=role.label,
        is_system=bool(role.is_system),
        base_role=role.base_role,
        data_scope=role.data_scope,
        permissions=list(role.permissions or []),
        campaigns=sorted(campaigns),
        user_count=len(usernames),
        roster_tags=roster_tags,
        users_without_tag=without_tag,
        roster_people=roster_people,
    )


def _validate_permissions(perms: list) -> list:
    known = set(P.ALL_PERMISSIONS)
    unknown = [p for p in perms if p not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Permission tidak dikenal: {', '.join(sorted(unknown))}",
        )
    # dict.fromkeys: buang duplikat tanpa mengacak urutan
    return list(dict.fromkeys(perms))


def _validate_scope(scope: str) -> str:
    valid = {key for key, _ in P.DATA_SCOPES}
    if scope not in valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cakupan data '{scope}' tidak dikenal",
        )
    return scope


def _validate_campaigns(db: Session, campaigns: list) -> list:
    """Campaign harus ada di tabel ``campaigns`` — daftar itulah yang terkendali,
    karena hanya SPQ Head / Admin yang bisa meng-upload campaign."""
    campaigns = [c.strip() for c in campaigns if (c or "").strip()]
    if not campaigns:
        return []
    known = {c.name for c in db.query(Campaign).all()}
    unknown = [c for c in campaigns if c not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign tidak ditemukan: {', '.join(sorted(unknown))}",
        )
    return list(dict.fromkeys(campaigns))


def _set_campaigns(db: Session, role: Role, campaigns: list) -> None:
    db.query(RoleCampaign).filter(RoleCampaign.role_id == role.id).delete()
    for c in campaigns:
        db.add(RoleCampaign(role_id=role.id, campaign=c))


@router.get("/catalog", response_model=PermissionCatalog)
def permission_catalog(_=Depends(require(P.ADMIN_ROLE_WRITE)), db: Session = Depends(get_db)):
    """Kosakata untuk form Manage Role: daftar permission berkelompok, pilihan
    cakupan data, dan campaign yang tersedia untuk di-assign."""
    return PermissionCatalog(
        groups=[
            {"title": title, "items": [{"key": k, "label": lbl} for k, lbl in items]}
            for title, items in P.PERMISSION_GROUPS
        ],
        data_scopes=[{"key": k, "label": lbl} for k, lbl in P.DATA_SCOPES],
        campaigns=sorted(c.name for c in db.query(Campaign).all()),
        campaigns_with_roster=sorted({
            c for idx in (
                roster_campaign_index(db, scope)
                for scope in ("sales_agent", "sales_tl", "sales_am")
            )
            for tags in idx.values()
            for c in tags
        }),
    )


@router.get("", response_model=RoleListResponse)
def list_roles(_=Depends(require(P.ADMIN_ROLE_WRITE)), db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.is_system.desc(), Role.id).all()
    # Satu cache untuk semua role: index roster dibangun paling banyak sekali per
    # tingkat hierarki, bukan sekali per role.
    index_cache: dict = {}
    return RoleListResponse(roles=[_detail(db, r, index_cache) for r in roles])


@router.post("", response_model=RoleDetail, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleCreate,
    current_user=Depends(require(P.ADMIN_ROLE_WRITE)),
    db: Session = Depends(get_db),
):
    key = (body.key or "").strip().lower()
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Key role harus 2-50 karakter, diawali huruf kecil, hanya huruf/angka/underscore",
        )
    if db.query(Role).filter(Role.key == key).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Role '{key}' sudah ada"
        )

    permissions = _validate_permissions(body.permissions)
    scope = _validate_scope(body.data_scope)
    campaigns = _validate_campaigns(db, body.campaigns)

    role = Role(
        key=key,
        label=(body.label or key).strip(),
        is_system=False,
        base_role=(body.base_role or None),
        data_scope=scope,
        permissions=permissions,
        created_by=getattr(current_user, "id", None) or None,
    )
    db.add(role)
    db.flush()
    _set_campaigns(db, role, campaigns)
    db.commit()
    db.refresh(role)
    invalidate()
    return _detail(db, role)


@router.put("/{role_id}", response_model=RoleDetail)
def update_role(
    role_id: int,
    body: RoleUpdate,
    current_user=Depends(require(P.ADMIN_ROLE_WRITE)),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role tidak ditemukan")

    permissions = _validate_permissions(body.permissions)
    scope = _validate_scope(body.data_scope)
    campaigns = _validate_campaigns(db, body.campaigns)

    # Jangan biarkan seseorang mengunci dirinya sendiri keluar dari Manage Role.
    if (
        role.key == getattr(current_user, "role", None)
        and P.ADMIN_ROLE_WRITE not in permissions
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak dapat mencabut izin 'Kelola role' dari role Anda sendiri",
        )
    if role.key in P.PROTECTED_ROLES and P.ADMIN_ROLE_WRITE not in permissions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{role.key}' harus tetap memiliki izin 'Kelola role'",
        )

    if body.label and body.label.strip():
        role.label = body.label.strip()
    role.data_scope = scope
    role.permissions = permissions
    _set_campaigns(db, role, campaigns)
    db.commit()
    db.refresh(role)
    invalidate()
    return _detail(db, role)


@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    _=Depends(require(P.ADMIN_ROLE_WRITE)),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role tidak ditemukan")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role bawaan sistem tidak dapat dihapus",
        )
    used = db.query(User).filter(User.role == role.key).count()
    if used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role masih dipakai {used} user — pindahkan user tersebut dulu",
        )
    key = role.key
    db.query(RoleCampaign).filter(RoleCampaign.role_id == role.id).delete()
    db.delete(role)
    db.commit()
    invalidate()
    return {"deleted": True, "id": role_id, "key": key}


# --- Tab "Assign Role": campaign per USERNAME ------------------------------
# Sampai sekarang campaign hanya bisa dibatasi per ROLE, atau — untuk sisi sales —
# lewat kolom Dedicated di Sales Database. Membatasi SATU orang saja karenanya
# menuntut pembuatan role bespoke. Di sini batas itu dipasang langsung pada orangnya.
#
# Assign hanya MEMPERSEMPIT: campaign efektif = irisan (role ∩ roster ∩ assign),
# lihat ``api.rbac.effective_campaigns_for``. Meng-assign campaign yang tidak dipegang
# role-nya menghasilkan irisan kosong — user itu tidak melihat tiket apa pun, dan
# itulah yang ditampilkan kolom "campaign efektif" supaya kekeliruannya kelihatan.


def _user_campaign_item(db: Session, user: User, assigned: list) -> UserCampaignItem:
    from api.rbac import data_scope_for, effective_campaigns_for, role_label_for

    effective = effective_campaigns_for(db, user)
    return UserCampaignItem(
        user_id=user.id,
        username=user.username,
        name=user.name or "",
        role=user.role or "",
        role_label=role_label_for(db, user),
        campaigns=sorted(assigned),
        effective_campaigns=effective or [],
        effective_all=effective is None,
        campaign_from_roster=P.is_sales_scope(data_scope_for(db, user)),
    )


@router.get("/user_campaigns", response_model=UserCampaignListResponse)
def list_user_campaigns(
    _=Depends(require(P.ADMIN_ROLE_WRITE)),
    db: Session = Depends(get_db),
):
    """Daftar user beserta campaign yang di-assign khusus untuknya."""
    rows = db.query(UserCampaign).all()
    by_user: dict = {}
    for r in rows:
        by_user.setdefault(r.user_id, []).append(r.campaign)
    users = db.query(User).order_by(User.username).all()
    return UserCampaignListResponse(
        users=[_user_campaign_item(db, u, by_user.get(u.id, [])) for u in users],
        campaigns=[c.name for c in db.query(Campaign).order_by(Campaign.name).all()],
    )


@router.put("/user_campaigns/{username}", response_model=UserCampaignItem)
def set_user_campaigns(
    username: str,
    body: UserCampaignUpdate,
    _=Depends(require(P.ADMIN_ROLE_WRITE)),
    db: Session = Depends(get_db),
):
    """Ganti daftar campaign seorang user. Daftar KOSONG = hapus pembatasannya."""
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")

    known = {c.name for c in db.query(Campaign).all()}
    wanted, seen = [], set()
    for raw in body.campaigns or []:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        if name not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Campaign '{name}' tidak dikenal",
            )
        seen.add(name)
        wanted.append(name)

    db.query(UserCampaign).filter(UserCampaign.user_id == user.id).delete()
    for name in wanted:
        db.add(UserCampaign(user_id=user.id, campaign=name))
    db.commit()
    return _user_campaign_item(db, user, wanted)
