from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

# "demo" = read-only showcase role for demoing the app to non-technical people.
# It mirrors the SPQ-Head *view* (Stats + Results + evaluation detail + Transkrip,
# global read-only) but is excluded from every admin/write dependency, so it cannot
# mutate any data. See api/dependencies.py (view deps opened to demo) and the
# frontend menu/route gates.
VALID_ROLES = {"spq_head", "admin", "telesales_head", "team_leader_qc", "qc", "qc_support", "area_manager", "team_leader", "sales_agent", "demo"}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    username: str  # the person's NIP
    name: Optional[str] = None  # display name (full name)
    email: str
    password: str
    role: str = "sales_agent"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v = v.lower()
        if v not in VALID_ROLES:
            raise ValueError(f"role harus salah satu dari {sorted(VALID_ROLES)}")
        return v


class UserResponse(BaseModel):
    id: int
    username: str
    name: Optional[str] = None
    email: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}