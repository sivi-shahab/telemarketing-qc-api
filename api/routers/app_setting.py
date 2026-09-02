"""Kebijakan tingkat aplikasi yang bisa diubah operator saat sistem berjalan.

Saat ini berisi satu sakelar: **kebijakan tenggat H+2 dokumen pendukung**.

H+2 = 48 jam sejak ``tms_cashline.submit_time``. Selama tenggat belum lewat dan
dokumen yang diminta belum diunggah, tiket berstatus ``PENDING``; begitu lewat tanpa
unggah, tiket menjadi ``FAIL`` (Not Qualified) dan error code B09 terbit.

Sebelum 24 Agustus 2026 sakelarnya adalah konstanta
``compliance.stats_aggregate.DOC_SLA_ENABLED`` — mengubahnya berarti edit file plus
restart container, dan statusnya tidak terlihat di layar sama sekali.

Dua endpoint, KEDUANYA digerbangi ``admin.doc_sla.write`` — dipegang role ``admin``
dan ``demo``:

* ``GET /doc_sla_policy``  — membaca status kebijakan.
* ``PUT /doc_sla_policy`` — mengubahnya.

Sampai 27 Agustus 2026 GET-nya terbuka untuk siapa pun yang sudah login, dengan
alasan status PENDING/FAIL yang mereka lihat bergantung pada sakelar ini. Sejak
28 Agustus 2026 kebijakannya diubah atas permintaan bisnis: sakelar tingkat sistem
bukan informasi yang perlu dibaca sisi sales maupun QC, dan indikatornya di menu
Results ikut disembunyikan dari mereka. Layar tetap bekerja tanpa data ini — lihat
``loadDocSla`` di ``ResultsView.vue``, yang bahkan tidak memanggil endpoint-nya
untuk role tanpa capability tersebut.

PERINGATAN YANG DISENGAJA: sakelar ini dibaca saat MEMBACA data, bukan saat evaluasi
tiket. Mengubahnya karena itu menilai ulang SELURUH tiket yang sudah ada seketika —
tiket kekurangan dokumen yang tenggatnya sudah lewat berpindah FAIL <-> PENDING tanpa
perlu reproses. Itu memang perilaku konstanta lama; yang berubah hanya cara
mengubahnya. Snapshot Statistics ikut ditandai basi lewat ``_stats_signature``
sehingga angka di Statistics tidak bertentangan dengan status di Results.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from api.permissions import ADMIN_DOC_SLA_WRITE
from api.rbac import permissions_for, require
from compliance.stats_aggregate import SLA_HOURS, refresh_doc_sla_cache
from db import crud

router = APIRouter()


class DocSlaPolicyResponse(BaseModel):
    """Status kebijakan H+2 + apakah pemanggil boleh mengubahnya.

    ``can_edit`` dikirim supaya layar tidak perlu menebak dari daftar permission:
    tombolnya muncul HANYA bila field ini true, indikatornya selalu muncul.
    """

    enabled: bool = Field(..., description="True = kebijakan tenggat H+2 AKTIF")
    sla_hours: int = Field(..., description="Panjang tenggat dalam jam (48 = H+2)")
    can_edit: bool = Field(..., description="Pemanggil boleh mengubah sakelarnya")
    updated_at: str | None = None
    updated_by_username: str | None = None


class DocSlaPolicyUpdate(BaseModel):
    enabled: bool


def _payload(db: Session, can_edit: bool) -> DocSlaPolicyResponse:
    row = crud.get_app_setting_row(db, crud.DOC_SLA_SETTING_KEY)
    return DocSlaPolicyResponse(
        enabled=crud.get_doc_sla_enabled(db),
        sla_hours=SLA_HOURS,
        can_edit=can_edit,
        updated_at=row.updated_at.isoformat() if row is not None and row.updated_at else None,
        updated_by_username=row.updated_by_username if row is not None else None,
    )


@router.get(
    "/doc_sla_policy",
    response_model=DocSlaPolicyResponse,
    dependencies=[Depends(require(ADMIN_DOC_SLA_WRITE))],
)
def get_doc_sla_policy(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Status kebijakan tenggat H+2 (untuk indikator di menu Results)."""
    granted = permissions_for(db, current_user)
    return _payload(db, ADMIN_DOC_SLA_WRITE in granted)


@router.put(
    "/doc_sla_policy",
    response_model=DocSlaPolicyResponse,
    dependencies=[Depends(require(ADMIN_DOC_SLA_WRITE))],
)
def set_doc_sla_policy(
    body: DocSlaPolicyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Hidupkan/matikan kebijakan tenggat H+2 (khusus role ``admin``)."""
    crud.set_doc_sla_enabled(db, body.enabled, getattr(current_user, "username", None))
    # Cache modul disegarkan SEKARANG, bukan menunggu request berikutnya, supaya
    # respons yang dikembalikan sudah mencerminkan nilai barunya.
    refresh_doc_sla_cache(db)
    return _payload(db, True)
