"""Role jadi data: tabel roles + role_campaigns

Sebelum ini "role" hanyalah string di ``users.role`` yang dicocokkan dengan daftar
literal di ~29 berkas. Role baru mustahil dibuat lewat UI karena tidak akan lolos
satu pun gate.

Migrasi ini memindahkan definisi role ke DB:

* ``roles``          — satu baris per role, membawa ``permissions`` (daftar
                       capability) dan ``data_scope`` (cakupan tiket).
* ``role_campaigns`` — campaign yang boleh dilihat role tersebut. TIDAK ADA baris
                       berarti SEMUA campaign; ini yang membuat role seperti
                       ``tl_ntb`` bisa dibatasi ke campaign NTB saja.

``users.role`` tetap menyimpan KEY role (bukan foreign key integer) supaya kolom
historis yang ikut merekam role — ``results.uploaded_by_role``,
``qc_status_requests.requested_by_role``, ``qc_status_events.actor_role``,
``error_code_appeals.origin`` — tetap terbaca apa adanya dan tidak perlu di-backfill.
Kolomnya diperlebar 20 -> 50 karena nama role turunan seperti
``team_leader_qc_retention`` (24 karakter) tidak muat di String(20).

Seed 10 role bawaan disalin dari ``api/permissions.py`` PADA SAAT migrasi ini
dibuat, sengaja di-inline agar migrasi tetap bisa dijalankan ulang walau kosakata
capability di kode berubah kemudian.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Snapshot DEFAULT_ROLES per 6 Agustus 2026 (label, data_scope, permissions).
_MENU_ALL_ADMIN = [
    "menu.stats", "menu.results", "menu.transcripts", "menu.assign_ticket",
    "menu.manual_check", "menu.pending_check", "menu.campaigns",
    "menu.sales_database", "menu.qc_database", "menu.upload_campaign",
    "menu.upload_audio", "menu.upload_transcript", "menu.get_result",
    "menu.upload_sales_database", "menu.upload_qc_database",
    "menu.delete_campaign", "menu.manage_user", "menu.manage_role",
    "menu.role_hierarchy",
]
_ADMIN_WRITE = [
    "admin.user.write", "admin.role.write", "admin.campaign.write",
    "admin.sales_database.write", "admin.qc_database.write",
    "qc.assignment.write", "transcript.upload", "audio.upload",
]
_STATS_ALL = [
    "stats.failure_reason", "stats.qc_performance", "stats.risk_base",
    "stats.risk_system_new",
]
_QC_SIDE_VIEW = [
    "menu.stats", "menu.results", "menu.transcripts",
    "results.evaluation_detail", "results.critical_failure",
    "results.document.view",
]

SEED = {
    "spq_head": ("SPQ Head", "all", _MENU_ALL_ADMIN + [
        "results.evaluation_detail", "results.critical_failure",
        "results.category_score", "results.manual_status.set",
        "results.manual_status.direct", "results.manual_status.review_spq",
        "results.error_code.direct_edit", "results.error_code.review_spq",
        "results.document.view",
    ] + _STATS_ALL + _ADMIN_WRITE),
    # Menu identik SPQ Head, TANPA aksi QC (kebijakan, dikonfirmasi 6 Agu 2026).
    "admin": ("Admin", "all", _MENU_ALL_ADMIN + [
        "results.evaluation_detail", "results.critical_failure",
        "results.category_score",
        "results.document.upload", "results.document.view",
    ] + _STATS_ALL + _ADMIN_WRITE),
    "telesales_head": ("Telesales Head", "all", [
        "menu.stats", "menu.results", "results.category_score",
        "results.document.view",
    ]),
    "area_manager": ("Area Manager", "sales_am", [
        "menu.stats", "menu.results", "results.category_score",
        "results.document.view",
    ]),
    "team_leader": ("Team Leader Sales", "sales_tl", [
        "menu.stats", "menu.results", "results.category_score",
        "results.document.upload", "results.document.view",
    ]),
    "sales_agent": ("Sales Agent", "sales_agent", [
        "menu.stats", "menu.results", "results.category_score",
        "results.document.view",
    ]),
    "team_leader_qc": ("Team Leader QC", "all", _QC_SIDE_VIEW + [
        "menu.assign_ticket", "menu.manual_check", "menu.pending_check",
        "menu.upload_audio", "menu.upload_transcript",
        "results.category_score",
        "results.manual_status.set", "results.manual_status.direct",
        "results.manual_status.review_tl",
        "results.error_code.direct_edit", "results.error_code.review_tl",
        "stats.qc_performance", "stats.risk_base", "stats.risk_system_new",
        "qc.assignment.write", "transcript.upload", "audio.upload",
    ]),
    "qc": ("QC", "qc_assigned", _QC_SIDE_VIEW + [
        "menu.manual_check", "menu.pending_check",
        "results.manual_status.set", "results.error_code.appeal",
        "stats.risk_base",
    ]),
    "qc_support": ("QC Support", "qc_support_own", [
        "menu.results", "menu.transcripts", "menu.upload_audio",
        "menu.upload_transcript",
        "results.evaluation_detail", "results.critical_failure",
        "results.category_score", "results.document.view",
        "transcript.upload", "audio.upload",
    ]),
    "demo": ("Demo", "all", [
        "menu.stats", "menu.results", "menu.campaigns",
        "menu.upload_transcript",
        "results.evaluation_detail", "results.critical_failure",
        "results.category_score", "results.document.view",
        "stats.risk_base", "stats.risk_system_new",
        "transcript.upload",
    ]),
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        # Role bawaan: tidak bisa dihapus lewat UI.
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Role existing yang dipakai sebagai template saat role ini dibuat.
        sa.Column("base_role", sa.String(50)),
        sa.Column("data_scope", sa.String(30), nullable=False, server_default="all"),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_roles_key"),
    )

    op.create_table(
        "role_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        # Nama campaign (campaigns.name), bukan FK: campaign boleh dihapus tanpa
        # menjatuhkan role, dan nilainya sejajar dengan results.campaign.
        sa.Column("campaign", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "campaign", name="uq_role_campaign"),
    )
    op.create_index("ix_role_campaigns_role_id", "role_campaigns", ["role_id"])

    # 'team_leader_qc' sudah 14 karakter; role turunan per campaign gampang lewat 20.
    op.alter_column(
        "users", "role",
        existing_type=sa.String(20), type_=sa.String(50), existing_nullable=False,
    )

    roles_tbl = sa.table(
        "roles",
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("data_scope", sa.String),
        sa.column("permissions", postgresql.JSONB),
    )
    op.bulk_insert(
        roles_tbl,
        [
            {
                "key": key,
                "label": label,
                "is_system": True,
                "data_scope": scope,
                # Buang duplikat (mis. menu.stats muncul di _QC_SIDE_VIEW dan list
                # tambahan) tanpa mengacak urutan aslinya.
                "permissions": list(dict.fromkeys(perms)),
            }
            for key, (label, scope, perms) in SEED.items()
        ],
    )


def downgrade() -> None:
    op.alter_column(
        "users", "role",
        existing_type=sa.String(50), type_=sa.String(20), existing_nullable=False,
    )
    op.drop_index("ix_role_campaigns_role_id", table_name="role_campaigns")
    op.drop_table("role_campaigns")
    op.drop_table("roles")
