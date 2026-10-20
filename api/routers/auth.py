from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from api.dependencies import get_current_user, get_db
from api.permissions import ADMIN_USER_WRITE, QC_USER_ACTIVE_WRITE, QC_USER_EDIT
from api.rbac import require, require_any
from api.schemas.auth import (
    AccessTokenResponse,
    MeResponse,
    UserListItem,
    UserUpdate,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from db import crud
from db.models import User, UserChangeEvent

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if user is not None and not user.is_active and user.inactive_until is not None:
        # Nonaktif sementara dari Kelola QC yang sudah lewat 00.00 WIB — jangan
        # tunggu putaran beat berikutnya.
        crud.reactivate_expired_qc_users(db)
        db.refresh(user)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun tidak aktif",
        )
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    from jose import JWTError

    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token tidak valid atau sudah expired",
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token bukan refresh token",
        )
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan atau tidak aktif",
        )
    access_token = create_access_token({"sub": str(user.id)})
    return AccessTokenResponse(access_token=access_token)


@router.post("/create_user", response_model=UserResponse)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require(ADMIN_USER_WRITE)),
):
    from db.models import Role

    if db.query(Role).filter(Role.key == body.role).first() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Role '{body.role}' tidak dikenal",
        )
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username atau email sudah digunakan",
        )
    created_by_id = current_user.id if current_user.id != 0 else None
    user = User(
        username=body.username,
        name=(body.name or None),
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_active=True,
        created_by=created_by_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


def _can_manage_all_users(db: Session, user) -> bool:
    """Pemegang ADMIN_USER_WRITE (Admin) mengelola semua user. Tanpanya — Team
    Leader QC lewat QC_USER_ACTIVE_WRITE — hanya QC Telemarketing yang terjangkau."""
    from api.rbac import has_perm

    return has_perm(db, user, ADMIN_USER_WRITE)


def _is_telemarketing_qc(db: Session, user, campaigns=None) -> bool:
    """Role ``qc`` yang campaign efektifnya bukan Collection-only — definisi yang
    sama dengan penyesuaian menu Collection (``rbac.is_collection_only``)."""
    from api.rbac import collection_campaigns_from_env, effective_campaigns_for, is_collection_only

    if (getattr(user, "role", None) or "") != "qc":
        return False
    if campaigns is None:
        campaigns = effective_campaigns_for(db, user)
    return not is_collection_only(campaigns, collection_campaigns_from_env())


def _user_list_item(db: Session, u, campaigns=None) -> UserListItem:
    """Satu baris daftar user (role_label, campaign efektif, asal campaign) — dipakai
    ``list_users`` dan ``update_user``. ``campaigns`` boleh diberikan bila sudah
    dihitung pemanggil."""
    from api import permissions as P
    from api.rbac import data_scope_for, effective_campaigns_for, role_label_for

    if campaigns is None:
        campaigns = effective_campaigns_for(db, u)
    item = UserListItem.model_validate(u)
    item.role_label = role_label_for(db, u)
    item.campaigns = campaigns or []
    item.campaign_from_roster = P.is_sales_scope(data_scope_for(db, u))
    return item


@router.get("/users", response_model=list[UserListItem])
def list_users(
    db: Session = Depends(get_db),
    current_user=Depends(require_any(ADMIN_USER_WRITE, QC_USER_ACTIVE_WRITE, QC_USER_EDIT)),
):
    """List users, newest first, plus campaign efektif tiap user.

    Admin melihat semua user. Pemegang QC_USER_ACTIVE_WRITE saja (Team Leader QC,
    menu Kelola QC) hanya melihat QC Telemarketing — yang memang bisa ia
    aktifkan/nonaktifkan.

    Campaign dihitung per user lewat ``effective_campaigns_for``; untuk sisi sales itu
    berarti sekali pencarian ke peta roster, yang sudah di-cache per berkas aktif —
    jadi ratusan user tidak berarti ratusan pembacaan XLSX.
    """
    from api.rbac import effective_campaigns_for

    manage_all = _can_manage_all_users(db, current_user)
    query = db.query(User)
    if not manage_all:
        query = query.filter(User.role == "qc")
    users = query.order_by(User.id.desc()).all()
    out = []
    for u in users:
        campaigns = effective_campaigns_for(db, u)
        if not manage_all and not _is_telemarketing_qc(db, u, campaigns):
            continue
        out.append(_user_list_item(db, u, campaigns))
    return out


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require(ADMIN_USER_WRITE)),
):
    """Delete a user (SPQ Head only). An SPQ Head cannot delete their own account."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak dapat menghapus akun sendiri",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User tidak ditemukan",
        )
    username = user.username
    # Lepas referensi created_by milik user lain agar tidak melanggar FK.
    db.query(User).filter(User.created_by == user_id).update(
        {User.created_by: None}, synchronize_session=False
    )
    # Lepas tiket yang di-assign ke user ini (``qc_username`` tidak ber-FK). Tanpa
    # ini tiketnya tetap tercatat milik QC yang sudah tidak ada: tampil di Assign
    # Ticket, dilewati Auto Assign, dan tidak dikerjakan siapa pun. Riwayat Manual
    # Status-nya tidak ikut terhapus, sama seperti tombol "Lepas".
    crud.unassign_tickets_of_qc(
        db, username, actor_username=current_user.username, source="user_deleted"
    )
    db.delete(user)
    db.commit()
    return {"deleted": True, "id": user_id, "username": username}


@router.patch("/users/{user_id}", response_model=UserListItem)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_any(ADMIN_USER_WRITE, QC_USER_EDIT)),
):
    """Edit User: NIP (username), nama, email, password, dan role (hanya Admin).

    Tanpa ADMIN_USER_WRITE (Team Leader QC lewat QC_USER_EDIT) sasarannya hanya QC
    Telemarketing — user lain dijawab 404 — dan role tidak boleh berubah (mengirim
    role yang sama dengan sekarang tetap diterima, form mengirim semua field).

    Ganti NIP ikut menulis ulang seluruh kolom username teks di tabel lain
    (``crud.rename_username``). Semua perubahan, riwayat per field
    (``user_change_events``, password tanpa nilai), dan penulisan ulang NIP berada
    dalam SATU transaksi: gagal di tengah = rollback, tidak ada setengah jalan."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or (
        not _can_manage_all_users(db, current_user) and not _is_telemarketing_qc(db, user)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")

    new_username = body.username.strip() if body.username is not None else None
    new_email = body.email.strip() if body.email is not None else None
    new_name = body.name.strip() if body.name is not None else None
    if (new_username is not None and not new_username) or (new_email is not None and not new_email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username dan email tidak boleh kosong",
        )
    new_password = body.password or None

    role_changed = body.role is not None and body.role != user.role
    if role_changed:
        from db.models import Role

        if not _can_manage_all_users(db, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hanya Admin yang dapat mengubah role",
            )
        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tidak dapat mengubah role akun sendiri",
            )
        if db.query(Role).filter(Role.key == body.role).first() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Role '{body.role}' tidak dikenal",
            )

    # Bentrok dengan user LAIN, tanpa membedakan huruf besar/kecil. User ini sendiri
    # dikecualikan, jadi mengganti kapitalisasi NIP-nya sendiri bukan bentrok.
    for value, column in ((new_username, User.username), (new_email, User.email)):
        if value is None:
            continue
        clash = db.query(User).filter(User.id != user_id, func.lower(column) == value.lower()).first()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username atau email sudah digunakan",
            )

    # Field yang berubah; nama kosong dan None sama-sama berarti "tanpa nama".
    changes = []  # (field, lama, baru)
    if new_username is not None and new_username != user.username:
        changes.append(("username", user.username, new_username))
    if new_name is not None and (new_name or None) != (user.name or None):
        changes.append(("name", user.name, new_name or None))
    if new_email is not None and new_email != user.email:
        changes.append(("email", user.email, new_email))
    if role_changed:
        changes.append(("role", user.role, body.role))
    if new_password is not None:
        changes.append(("password", None, None))
    if not changes:
        return _user_list_item(db, user)

    actor_id = current_user.id if current_user.id != 0 else None
    try:
        old_username = user.username
        if new_username is not None and new_username != old_username:
            crud.rename_username(db, old_username, new_username)
            user.username = new_username
        for field, _old, new in changes:
            if field == "name":
                user.name = new
            elif field == "email":
                user.email = new
            elif field == "role":
                # Keluar dari QC = catat waktunya; kembali jadi QC = hapus catatannya.
                if user.role == "qc":
                    user.left_qc_at = datetime.utcnow()
                elif new == "qc":
                    user.left_qc_at = None
                user.role = new
            elif field == "password":
                user.hashed_password = hash_password(new_password)
        for field, old, new in changes:
            db.add(UserChangeEvent(
                user_id=user.id,
                target_username=user.username,
                field=field,
                old_value=old,
                new_value=new,
                actor_user_id=actor_id,
                actor_username=getattr(current_user, "username", None),
                actor_role=getattr(current_user, "role", None),
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return _user_list_item(db, user)


@router.patch("/users/{user_id}/active", response_model=UserResponse)
def set_user_active(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    current_user=Depends(require_any(ADMIN_USER_WRITE, QC_USER_ACTIVE_WRITE)),
):
    """Aktifkan/nonaktifkan user — dipakai tombol "Nonaktifkan" QC di menu
    Manage User (Admin) dan Kelola QC (Team Leader QC) supaya pembagian tiket
    otomatis (``api/routers/qc_assignment.py``, filter ``User.is_active``) cuma
    menyasar QC yang aktif. User nonaktif juga otomatis ter-logout (lihat
    pengecekan ``is_active`` di ``login``/``refresh``/``get_current_user``).

    Tanpa ADMIN_USER_WRITE sasarannya hanya QC Telemarketing; user lain dijawab
    404 seperti user yang tidak ada, supaya endpoint ini tidak bisa dipakai
    menebak akun di luar cakupannya.

    Nonaktif dari Kelola QC bersifat sementara: ``inactive_until`` = 00.00 WIB
    berikutnya, lalu ``crud.reactivate_expired_qc_users`` (beat worker + login)
    mengaktifkannya kembali. Nonaktif dari Admin permanen (``inactive_until``
    NULL)."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak dapat menonaktifkan akun sendiri",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or (
        not _can_manage_all_users(db, current_user) and not _is_telemarketing_qc(db, user)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User tidak ditemukan",
        )
    # Waktu nonaktif dicatat saat pindah aktif -> nonaktif (bukan saat dinonaktifkan
    # ulang), supaya batch auto assign membagi ulang tiket hari ini milik QC ini di
    # slot berikutnya (19 Oktober 2026, ``qc_auto_assign.reassign_from_inactive``).
    if is_active:
        user.deactivated_at = None
    elif user.is_active or user.deactivated_at is None:
        user.deactivated_at = datetime.utcnow()
    user.is_active = is_active
    # Nonaktif oleh Team Leader QC (Kelola QC) hanya sampai 00.00 WIB berikutnya;
    # oleh Admin permanen sampai diaktifkan lagi (16 Oktober 2026).
    if is_active or _can_manage_all_users(db, current_user):
        user.inactive_until = None
    else:
        user.inactive_until = crud.next_midnight_wib_utc()
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.get("/me", response_model=MeResponse)
def me(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from api.campaign_groups import collapse
    from api.rbac import (
        collection_campaigns_from_env,
        data_scope_for,
        effective_campaigns_for,
        permissions_for,
        role_label_for,
        stats_views_for,
    )

    campaigns = effective_campaigns_for(db, current_user) or []
    return MeResponse(
        id=current_user.id,
        username=current_user.username,
        name=getattr(current_user, "name", None),
        email=getattr(current_user, "email", ""),
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=getattr(current_user, "created_at", None),
        role_label=role_label_for(db, current_user),
        permissions=sorted(permissions_for(db, current_user)),
        data_scope=data_scope_for(db, current_user),
        # Campaign EFEKTIF (tag roster untuk sisi sales), bukan yang dideklarasikan
        # role — inilah yang benar-benar dilihat user, jadi itu pula yang ditampilkan.
        # ``None`` (tanpa pembatasan) dikirim sebagai list kosong.
        campaigns=campaigns,
        # Bentuk TAMPILAN: anggota yang tercakup grup disembunyikan, jadi login
        # ber-tag Telemarketing tampil sebagai "Telemarketing", bukan
        # "Telemarketing, Cashline" (lihat ``api.campaign_groups.collapse``).
        campaigns_display=collapse(campaigns, collection_campaigns_from_env()),
        stats_views=stats_views_for(db, current_user),
    )
