from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from api.dependencies import get_current_user, get_db
from api.permissions import ADMIN_USER_WRITE
from api.rbac import require
from api.schemas.auth import (
    AccessTokenResponse,
    MeResponse,
    UserListItem,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from qc_core.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
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
    from qc_core.db.models import Role

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


@router.get("/users", response_model=list[UserListItem])
def list_users(
    db: Session = Depends(get_db),
    current_user=Depends(require(ADMIN_USER_WRITE)),
):
    """List all users (SPQ Head only), newest first, plus campaign efektif tiap user.

    Campaign dihitung per user lewat ``effective_campaigns_for``; untuk sisi sales itu
    berarti sekali pencarian ke peta roster, yang sudah di-cache per berkas aktif —
    jadi ratusan user tidak berarti ratusan pembacaan XLSX.
    """
    from api import permissions as P
    from api.rbac import data_scope_for, effective_campaigns_for, role_label_for

    users = db.query(User).order_by(User.id.desc()).all()
    out = []
    for u in users:
        item = UserListItem.model_validate(u)
        item.role_label = role_label_for(db, u)
        item.campaigns = effective_campaigns_for(db, u) or []
        item.campaign_from_roster = P.is_sales_scope(data_scope_for(db, u))
        out.append(item)
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
    db.delete(user)
    db.commit()
    return {"deleted": True, "id": user_id, "username": username}


@router.get("/me", response_model=MeResponse)
def me(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from api.rbac import (
        data_scope_for,
        effective_campaigns_for,
        permissions_for,
        role_label_for,
    )

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
        campaigns=effective_campaigns_for(db, current_user) or [],
    )
