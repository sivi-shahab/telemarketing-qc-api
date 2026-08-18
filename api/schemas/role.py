from typing import List, Optional

from pydantic import BaseModel


class RosterTag(BaseModel):
    """Satu tag campaign yang benar-benar dipegang user sebuah role, + jumlahnya."""
    campaign: str
    users: int


class RosterPerson(BaseModel):
    """Satu orang beserta tag campaign-nya, untuk role yang jumlah user-nya sedikit."""
    username: str
    name: str
    campaigns: List[str] = []


class RoleDetail(BaseModel):
    id: int
    key: str
    label: str
    is_system: bool = False
    base_role: Optional[str] = None
    data_scope: str = "all"
    permissions: List[str] = []
    # Kosong = SEMUA campaign.
    campaigns: List[str] = []
    # Berapa user yang memakai role ini — dipakai UI untuk memblokir hapus.
    user_count: int = 0
    # Untuk role bercakupan sales: variasi tag `Dedicated` yang benar-benar dipegang
    # user role ini. Membuat "ikut tag roster" jadi konkret — terlihat satu role
    # sales_agent memang melayani banyak campaign sekaligus.
    roster_tags: List[RosterTag] = []
    # User sisi sales yang NIP-nya tidak ada di roster: mereka tidak melihat tiket
    # apa pun, jadi jumlahnya perlu terlihat.
    users_without_tag: int = 0
    # Rincian per ORANG, hanya diisi saat user-nya sedikit (lihat _PEOPLE_LIST_MAX).
    # Untuk Area Manager yang cuma 5 orang, menyebut namanya jauh lebih berguna
    # daripada tally per campaign — apalagi karena satu AM memegang beberapa campaign
    # sehingga tally-nya berjumlah lebih besar dari jumlah orangnya.
    roster_people: List[RosterPerson] = []

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    key: str
    label: str = ""
    # Role existing yang dipakai sebagai template (hanya dicatat, penyalinan
    # daftar permission-nya dilakukan di sisi UI sebelum submit).
    base_role: Optional[str] = None
    data_scope: str = "all"
    permissions: List[str] = []
    campaigns: List[str] = []


class RoleUpdate(BaseModel):
    label: str = ""
    data_scope: str = "all"
    permissions: List[str] = []
    campaigns: List[str] = []


class RoleListResponse(BaseModel):
    roles: List[RoleDetail]


class PermissionItem(BaseModel):
    key: str
    label: str


class PermissionGroup(BaseModel):
    title: str
    items: List[PermissionItem]


class DataScopeItem(BaseModel):
    key: str
    label: str


class PermissionCatalog(BaseModel):
    groups: List[PermissionGroup]
    data_scopes: List[DataScopeItem]
    campaigns: List[str]
    # Campaign yang BENAR-BENAR ada di kolom Dedicated Sales Database. Membatasi role
    # bercakupan sales ke campaign di luar daftar ini membuat user-nya tidak melihat
    # tiket apa pun (campaign efektif = roster ∩ role), jadi UI perlu memperingatkan.
    campaigns_with_roster: List[str] = []


class UserCampaignItem(BaseModel):
    """Satu baris pada tab "Assign Role" di menu Manage Role."""
    user_id: int
    username: str
    name: str = ""
    role: str = ""
    role_label: str = ""
    # Campaign yang di-assign KHUSUS ke orang ini (tabel user_campaigns).
    # Kosong = tidak dibatasi di tingkat orang.
    campaigns: List[str] = []
    # Campaign yang BENAR-BENAR berlaku sesudah irisan role & roster — inilah yang
    # menentukan tiket mana yang dilihat, dan bisa lebih sempit dari `campaigns`.
    effective_campaigns: List[str] = []
    # True bila user TIDAK dibatasi campaign sama sekali. Perlu terpisah karena
    # `effective_campaigns` kosong punya DUA arti yang berlawanan: "tidak dibatasi"
    # dan "dibatasi ke tidak ada apa pun" (irisan kosong = tidak melihat tiket apa
    # pun). UI harus bisa membedakannya.
    effective_all: bool = False
    # True bila cakupan datanya sisi sales: campaign-nya juga dibatasi tag Dedicated
    # di Sales Database, jadi assign di sini hanya mempersempit lebih jauh.
    campaign_from_roster: bool = False


class UserCampaignListResponse(BaseModel):
    users: List[UserCampaignItem]
    campaigns: List[str]


class UserCampaignUpdate(BaseModel):
    campaigns: List[str] = []
