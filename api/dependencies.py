import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dotenv import load_dotenv

from services.multi_bucket_minio import build_minio_client

logger = logging.getLogger(__name__)

class Settings(BaseSettings):

    # ============================================
    # PostgreSQL Configuration
    # ============================================
    postgres_host: str = "postgres"
    postgres_host: str = os.getenv("POSTGRES_HOST", "postgres")
    postgres_port: int = 5432
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = "bankqa"
    postgres_db: str = os.getenv("POSTGRES_DB", "bankqc")
    postgres_user: str = "bankqa"
    postgres_user: str = os.getenv("POSTGRES_USER", "bankqc")
    postgres_password: str = "changeme"
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "changeme")
    # Schema tujuan semua tabel aplikasi. Kosong = 'public' (DB lokal).
    postgres_schema: str = os.getenv("POSTGRES_SCHEMA", "")
    
    # ============================================
    # Redis Configuration
    # ============================================
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6378/0")
    
    # ============================================
    # MinIO Configuration
    # ============================================
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:4003")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "changeme123")
    minio_bucket_transcripts: str = os.getenv("MINIO_BUCKET_TRANSCRIPTS", "transcripts")
    minio_bucket_results: str = os.getenv("MINIO_BUCKET_RESULTS", "results")
    minio_bucket_campaigns: str = os.getenv("MINIO_BUCKET_CAMPAIGNS", "campaigns")
    minio_bucket_documents: str = os.getenv("MINIO_BUCKET_DOCUMENTS", "documents")
    minio_transcripts_source_prefix: str = ""
    minio_documents_source_prefix: str = ""
    minio_bucket_audio: str = os.getenv("MINIO_BUCKET_AUDIO", "audio")
    minio_bucket_sales_database: str = os.getenv("MINIO_BUCKET_SALES_DATABASE", "sales-database")
    minio_bucket_qc_database: str = os.getenv("MINIO_BUCKET_QC_DATABASE", "qc-database")

    # HTTPS wajib untuk cdn.bankmega.local (beda dari MinIO docker-internal yang
    # http biasa) -- dipakai saat bikin client Minio(). Default False supaya
    # deployment lokal lama tetap jalan tanpa mengisi MINIO_SECURE.
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # --- Kredensial per-bucket (menggantikan 1 admin key global) ---
    # Default KOSONG, bukan nilai asli: kredensial hanya boleh datang dari .env.
    # Semua kosong = mode lama (minio_access_key/minio_secret_key global).
    minio_access_key_transcripts: str = os.getenv("MINIO_ACCESS_KEY_TRANSCRIPTS", "")
    minio_secret_key_transcripts: str = os.getenv("MINIO_SECRET_KEY_TRANSCRIPTS", "")
    minio_access_key_results: str = os.getenv("MINIO_ACCESS_KEY_RESULTS", "")
    minio_secret_key_results: str = os.getenv("MINIO_SECRET_KEY_RESULTS", "")
    minio_access_key_campaigns: str = os.getenv("MINIO_ACCESS_KEY_CAMPAIGNS", "")
    minio_secret_key_campaigns: str = os.getenv("MINIO_SECRET_KEY_CAMPAIGNS", "")
    minio_access_key_documents: str = os.getenv("MINIO_ACCESS_KEY_DOCUMENTS", "")
    minio_secret_key_documents: str = os.getenv("MINIO_SECRET_KEY_DOCUMENTS", "")
    minio_access_key_audio: str = os.getenv("MINIO_ACCESS_KEY_AUDIO", "")
    minio_secret_key_audio: str = os.getenv("MINIO_SECRET_KEY_AUDIO", "")
    minio_access_key_sales_database: str = os.getenv("MINIO_ACCESS_KEY_SALES_DATABASE", "")
    minio_secret_key_sales_database: str = os.getenv("MINIO_SECRET_KEY_SALES_DATABASE", "")
    # qc-database belum punya kredensial sendiri di CDN -- selama kosong, bucket
    # itu dilewati saat mapping dan pemakaiannya error jelas, bukan diam-diam.
    minio_access_key_qc_database: str = os.getenv("MINIO_ACCESS_KEY_QC_DATABASE", "")
    minio_secret_key_qc_database: str = os.getenv("MINIO_SECRET_KEY_QC_DATABASE", "")

    # ============================================
    # LLM Configuration
    # ============================================
    
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-5.4-mini")
    
    # ============================================
    # Celery Configuration
    # ============================================
    celery_concurrency: int = int(os.getenv("CELERY_CONCURRENCY", "8"))
    
    # ============================================
    # API & Security
    # ============================================
    api_key: str = os.getenv("API_KEY", "sk-d37bb40794a34bb1f493ab4 51d3d8057a755433f37cc66057e94c439b0e323b0")
    
    # ============================================
    # JWT Configuration
    # ============================================
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "aQrRq6Zbz0js1EdAX8rHP0h-BUaWfeiXuy2ZamiBFlM")
    jwt_access_token_expire_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    jwt_refresh_token_expire_days: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    
    # ============================================
    # Admin Credentials
    # ============================================
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@bank.local")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


# --- Database ---

def _make_engine(settings: Settings):
    connect_args = {}
    if settings.postgres_schema:
        # Model tidak menyebut schema sama sekali, jadi search_path yang
        # mengarahkan semua query ke schema aplikasi.
        connect_args["options"] = f"-csearch_path={settings.postgres_schema},public"
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        connect_args=connect_args,
    )


_engine = None
_SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _make_engine(get_settings())
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- MinIO ---

_minio_client = None


def get_minio():
    """Client MinIO milik API (lazy, satu instance per proses).

    Bisa berupa ``Minio`` biasa (mode admin key global) atau
    ``MultiBucketMinioClient`` (mode kredensial per-bucket / CDN) — API-nya sama
    sehingga semua pemanggil di routers tidak perlu berubah.
    """
    global _minio_client
    if _minio_client is None:
        _minio_client = build_minio_client(get_settings())
    return _minio_client


def ensure_buckets():
    settings = get_settings()
    client = get_minio()
    for bucket in [
        settings.minio_bucket_transcripts,
        settings.minio_bucket_results,
        settings.minio_bucket_campaigns,
        settings.minio_bucket_documents,
        settings.minio_bucket_audio,
        settings.minio_bucket_sales_database,
        settings.minio_bucket_qc_database,
    ]:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
        except Exception as exc:
            # Di mode per-bucket (CDN) bucket sudah disiapkan tim infra dan
            # kredensialnya TIDAK punya hak makeBucket; qc-database malah belum
            # punya kredensial sama sekali. Startup API tidak boleh mati karena
            # itu -- kalau bucket-nya memang bermasalah, error-nya muncul jelas
            # saat bucket itu dipakai.
            logger.warning("[minio] Lewati ensure bucket '%s': %s", bucket, exc)


# --- API Key Authentication (legacy, kept for backward compat) ---

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(api_key_header)):
    settings = get_settings()
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key",
        )
    return api_key


# --- JWT / Dual Auth ---

@dataclass
class SystemUser:
    """Synthetic user returned when authenticating via X-API-Key."""
    id: int = 0
    username: str = "system"
    role: str = "spq_head"
    is_active: bool = True


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> "SystemUser | db_User":
    from db.models import User as db_User
    from api.auth import decode_token
    from jose import JWTError

    settings = get_settings()

    # 1. Try X-API-Key first
    api_key = request.headers.get("X-API-Key")
    if api_key is not None:
        if api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing API Key",
            )
        return SystemUser()

    # 2. Try JWT Bearer — from the Authorization header, or a ``?token=`` query param.
    # Browsers can't set headers on <iframe>/direct-navigation requests (e.g. the
    # transcript PDF viewer, which must be a real URL so the native viewer shows the
    # filename), so those pass the access token in the URL.
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
    elif request.query_params.get("token"):
        token = request.query_params.get("token")
    if token:
        try:
            payload = decode_token(token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid atau sudah expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = db.query(db_User).filter(db_User.id == int(user_id)).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User tidak ditemukan atau tidak aktif",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentikasi diperlukan",
        headers={"WWW-Authenticate": "Bearer"},
    )


# "admin" has the exact same permissions as "spq_head" (Fase 7), so it is accepted
# everywhere SPQ Head is.
async def get_spq_head_user(
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("spq_head", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk SPQ Head",
        )
    return current_user


async def get_agent_error_summary_user(
    current_user=Depends(get_current_user),
):
    # Agent Error Summary terbuka untuk SEMUA role yang sudah login — isinya
    # sengaja identik di setiap role (lihat AgentErrorTable.vue). Dependency ini
    # dipertahankan (alih-alih memakai get_current_user langsung) sebagai satu
    # titik pasang kalau nanti perlu dibatasi lagi.
    return current_user


async def get_evaluation_detail_user( 
    current_user=Depends(get_current_user),
):
    # Detail penilaian (Executive Summary + verifikasi Ascend/TMS) hanya untuk
    # sisi QC. Sisi sales — sales_agent, team_leader, area_manager, telesales_head
    # — cukup Agent Error Summary; mereka tidak boleh membuka detail penilaian
    # tiket agent di bawah mereka.
    #
    # qc_support ikut boleh, tapi tetap stand alone: scoping-nya di
    # _scoped_customer_ids/list_results membatasi dia hanya ke upload-annya sendiri.
    # "demo" (read-only showcase) may open evaluation detail, mirroring the SPQ view.
    if current_user.role not in (
        "qc", "team_leader_qc", "qc_support", "spq_head", "admin", "demo",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Detail penilaian hanya untuk QC, TL QC, QC Support, SPQ Head, atau Admin",
        )
    return current_user


async def get_qc_user(
    current_user=Depends(get_current_user),
):
    if current_user.role != "qc":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk QC",
        )
    return current_user


async def get_sales_agent_user(
    current_user=Depends(get_current_user),
):
    if current_user.role != "sales_agent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk Sales Agent",
        )
    return current_user


async def get_team_leader_qc_user(
    current_user=Depends(get_current_user),
):
    if current_user.role != "team_leader_qc":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk Team Leader QC",
        )
    return current_user


async def get_tl_qc_or_spq_head_user(
    current_user=Depends(get_current_user),
):
    # Ticket assignment (QC division) is managed by Team Leader QC; SPQ Head (top of
    # the whole org) may also manage it.
    if current_user.role not in ("team_leader_qc", "spq_head", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk Team Leader QC atau SPQ Head",
        )
    return current_user


async def get_qc_or_spq_head_user(
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("qc", "spq_head", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses hanya untuk QC atau SPQ Head",
        )
    return current_user


# Supporting-document access (KTP/KK/NPWP/cover buku tabungan):
# - UPLOAD: HANYA Team Leader Sales yang menyuplai dokumen (+ admin superuser). QC,
#   TL QC, SPQ Head, QC Support TIDAK boleh upload (view-only), begitu pula sales
#   agent / AM / telesales.
# - VIEW: hanya sisi QC — QC, TL QC, SPQ Head, plus QC Support (dokumen komplainnya
#   sendiri). Team Leader sales boleh upload tapi TIDAK boleh melihat.
async def get_document_uploader_user(
    current_user=Depends(get_current_user),
):
    # Only Team Leader Sales uploads customer documents (KTP/KK/NPWP/cover buku
    # tabungan) on the Results menu. The QC side (QC, TL QC, SPQ Head, QC Support)
    # is view-only — see get_document_viewer_user. ``admin`` retained as superuser.
    if current_user.role not in ("team_leader", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload dokumen hanya untuk Team Leader Sales",
        )
    return current_user


async def get_document_viewer_user(
    current_user=Depends(get_current_user),
):
    # "demo" (read-only showcase) may view supporting documents, mirroring the SPQ view.
    if current_user.role not in (
        "qc", "team_leader_qc", "spq_head", "admin", "qc_support", "demo",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lihat dokumen hanya untuk QC, Team Leader QC, SPQ Head, atau QC Support",
        )
    return current_user
