"""JWT helpers and password hashing. No imports from api.dependencies to avoid circular refs."""
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    from api.dependencies import get_settings
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    return jwt.encode(
        {**data, "exp": expire, "type": "access"},
        settings.jwt_secret_key,
        algorithm=ALGORITHM,
    )


def create_refresh_token(data: dict) -> str:
    from api.dependencies import get_settings
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    return jwt.encode(
        {**data, "exp": expire, "type": "refresh"},
        settings.jwt_secret_key,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode and return payload. Raises jose.JWTError if invalid/expired."""
    from api.dependencies import get_settings
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
