"""Kosakata permission (capability) dan definisi role bawaan.

Sebelum berkas ini, "role" adalah string yang di-hardcode di ~29 berkas: daftar
literal di `SidebarMenu.vue`, guard di `router/index.js`, dan puluhan
`if current_user.role not in (...)` di `api/`. Akibatnya role baru mustahil dibuat
lewat UI — role yang tidak dikenal tidak lolos satu pun gate.

Di sini role dipisah menjadi tiga hal yang berbeda:

* **capability** — boleh melakukan/melihat APA (daftar string di bawah). Ini yang
  dicek gate, bukan nama role.
* **data_scope** — melihat tiket SIAPA. Tidak bisa jadi capability karena sifatnya
  memilih algoritma penyempitan, bukan ya/tidak. Lihat `api/qc_scope.py`.
* **campaign** — melihat campaign mana. Daftar kosong berarti SEMUA campaign.

Daftar `DEFAULT_ROLES` di bawah adalah hasil penelusuran perilaku yang BERLAKU saat
berkas ini dibuat, bukan rancangan baru — supaya pemasangan capability layer tidak
diam-diam mengubah hak siapa pun. Dua hal yang sengaja dipertahankan meski terlihat
seperti kejanggalan:

* `spq_head` TIDAK punya `results.document.upload`. Pengunggah dokumen hanya Team
  Leader Sales (+ `admin` sebagai superuser) — lihat `get_document_uploader_user`.
* `admin` TIDAK punya satu pun capability aksi QC (`results.manual_status.*`,
  `results.error_code.*`). Menunya hampir sama dengan SPQ Head, tetapi Admin
  mengurus sistem — user, campaign, database — bukan memutus perkara QC.
  Dikonfirmasi sebagai kebijakan, bukan bug (6 Agustus 2026).
* Sisi lain kebijakan yang sama (10 Agustus 2026): menu **Administration**
  (Manage User & Manage Role) hanya milik `admin`. `spq_head` tidak lagi punya
  `menu.manage_user` / `menu.manage_role` / `admin.user.write` / `admin.role.write`.
  Konsekuensinya HANYA `admin` yang bisa mengelola user & role — pastikan selalu ada
  akun Admin aktif.
"""

# --- Menu (menggerakkan sidebar & guard router) ---
MENU_STATS = "menu.stats"
MENU_RESULTS = "menu.results"
MENU_TRANSCRIPTS = "menu.transcripts"
MENU_ASSIGN_TICKET = "menu.assign_ticket"
MENU_MANUAL_CHECK = "menu.manual_check"
MENU_PENDING_CHECK = "menu.pending_check"
MENU_CAMPAIGNS = "menu.campaigns"
MENU_SALES_DATABASE = "menu.sales_database"
MENU_QC_DATABASE = "menu.qc_database"
MENU_UPLOAD_CAMPAIGN = "menu.upload_campaign"
MENU_UPLOAD_AUDIO = "menu.upload_audio"
MENU_UPLOAD_TRANSCRIPT = "menu.upload_transcript"
MENU_GET_RESULT = "menu.get_result"
MENU_UPLOAD_SALES_DATABASE = "menu.upload_sales_database"
MENU_UPLOAD_QC_DATABASE = "menu.upload_qc_database"
MENU_DELETE_CAMPAIGN = "menu.delete_campaign"
MENU_MANAGE_USER = "menu.manage_user"
MENU_MANAGE_ROLE = "menu.manage_role"
MENU_ROLE_HIERARCHY = "menu.role_hierarchy"

# --- Fitur di dalam halaman Results ---
RESULTS_EVALUATION_DETAIL = "results.evaluation_detail"
RESULTS_CRITICAL_FAILURE = "results.critical_failure"
RESULTS_CATEGORY_SCORE = "results.category_score"
# Kolom "Manual Status" di halaman Results. TERPISAH dari MANUAL_STATUS_SET: yang
# ini hanya soal MELIHAT vonis human. Divisi sales (TLO, Team Leader Sales, Area
# Manager, Telesales Head) tidak memilikinya — bagi mereka cukup AI Status
# (permintaan 10 Agustus 2026).
MANUAL_STATUS_COLUMN = "results.manual_status.column"
MANUAL_STATUS_SET = "results.manual_status.set"
MANUAL_STATUS_DIRECT = "results.manual_status.direct"
MANUAL_STATUS_REVIEW_TL = "results.manual_status.review_tl"
MANUAL_STATUS_REVIEW_SPQ = "results.manual_status.review_spq"
ERROR_CODE_APPEAL = "results.error_code.appeal"
ERROR_CODE_DIRECT_EDIT = "results.error_code.direct_edit"
ERROR_CODE_REVIEW_TL = "results.error_code.review_tl"
ERROR_CODE_REVIEW_SPQ = "results.error_code.review_spq"
DOCUMENT_UPLOAD = "results.document.upload"
DOCUMENT_VIEW = "results.document.view"
# Tabel perbandingan hasil OCR dokumen vs acuan TMS/Ascend di modal "View Document".
# TERPISAH dari DOCUMENT_VIEW: melihat dokumennya (KTP/NPWP/KK/buku tabungan) adalah
# satu hal, membaca vonis cocok/tidaknya terhadap data bank adalah pekerjaan QC.
# Sisi sales boleh membuka dokumennya, tetapi bukan penilaiannya.
DOCUMENT_VERIFICATION_TABLE = "results.document.verification"
# Tombol "sudah dicek" lama pada tiket yang di-assign — khusus QC, terpisah dari
# Manual Status (lihat api/routers/qc_manual_check.py).
QC_MANUAL_CHECK_APPROVE = "results.manual_check.approve"
# Filter hierarki di Results menampilkan dropdown QC / QC Support (sisi QC) alih-alih
# AM / TL / Agent (sisi sales) — dipegang pengawas divisi QC.
RESULTS_FILTER_QC_SIDE = "results.filter.qc_side"
# Export XLSX agregat per kategori verifikasi (Verifikasi Statik/Dinamik, Cashline,
# Cardholder) untuk semua tiket Not Qualified & Pending — bukan export satu tiket
# (yang mengikuti RESULTS_EVALUATION_DETAIL), melainkan tarikan lintas tiket.
RESULTS_EXPORT_VERIFICATION = "results.export.verification"

# --- Fitur di dalam halaman Stats ---
STATS_FAILURE_REASON = "stats.failure_reason"
STATS_QC_PERFORMANCE = "stats.qc_performance"
STATS_RISK_BASE = "stats.risk_base"
STATS_RISK_SYSTEM_NEW = "stats.risk_system_new"

# --- Administrasi (tulis) ---
ADMIN_USER_WRITE = "admin.user.write"
ADMIN_ROLE_WRITE = "admin.role.write"
ADMIN_CAMPAIGN_WRITE = "admin.campaign.write"
ADMIN_SALES_DATABASE_WRITE = "admin.sales_database.write"
ADMIN_QC_DATABASE_WRITE = "admin.qc_database.write"
ADMIN_TICKET_DELETE = "admin.ticket.delete"
QC_ASSIGNMENT_WRITE = "qc.assignment.write"
TRANSCRIPT_UPLOAD = "transcript.upload"
AUDIO_UPLOAD = "audio.upload"

ALL_PERMISSIONS = [
    MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
    MENU_MANUAL_CHECK, MENU_PENDING_CHECK, MENU_CAMPAIGNS, MENU_SALES_DATABASE,
    MENU_QC_DATABASE, MENU_UPLOAD_CAMPAIGN, MENU_UPLOAD_AUDIO,
    MENU_UPLOAD_TRANSCRIPT, MENU_GET_RESULT, MENU_UPLOAD_SALES_DATABASE,
    MENU_UPLOAD_QC_DATABASE, MENU_DELETE_CAMPAIGN, MENU_MANAGE_USER,
    MENU_MANAGE_ROLE, MENU_ROLE_HIERARCHY,
    RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE, RESULTS_CATEGORY_SCORE,
    MANUAL_STATUS_COLUMN,
    MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_TL,
    MANUAL_STATUS_REVIEW_SPQ, ERROR_CODE_APPEAL, ERROR_CODE_DIRECT_EDIT,
    ERROR_CODE_REVIEW_TL, ERROR_CODE_REVIEW_SPQ, DOCUMENT_UPLOAD, DOCUMENT_VIEW,
    DOCUMENT_VERIFICATION_TABLE,
    QC_MANUAL_CHECK_APPROVE, RESULTS_FILTER_QC_SIDE, RESULTS_EXPORT_VERIFICATION,
    STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
    STATS_RISK_SYSTEM_NEW,
    ADMIN_USER_WRITE, ADMIN_ROLE_WRITE, ADMIN_CAMPAIGN_WRITE,
    ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE, ADMIN_TICKET_DELETE,
    QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
]

# Label Indonesia untuk UI Manage Role, dikelompokkan agar daftar checkbox terbaca.
PERMISSION_GROUPS = [
    ("Menu", [
        (MENU_STATS, "Stats"),
        (MENU_RESULTS, "Results"),
        (MENU_TRANSCRIPTS, "Transkrip"),
        (MENU_ASSIGN_TICKET, "Assign Ticket"),
        (MENU_MANUAL_CHECK, "Manual Check"),
        (MENU_PENDING_CHECK, "Pending Check"),
        (MENU_CAMPAIGNS, "Campaigns"),
        (MENU_SALES_DATABASE, "Database Sales"),
        (MENU_QC_DATABASE, "Database QC"),
        (MENU_UPLOAD_CAMPAIGN, "Upload Campaign"),
        (MENU_UPLOAD_AUDIO, "Upload Audio"),
        (MENU_UPLOAD_TRANSCRIPT, "Upload Transcript"),
        (MENU_GET_RESULT, "Get Result"),
        (MENU_UPLOAD_SALES_DATABASE, "Upload Database Sales"),
        (MENU_UPLOAD_QC_DATABASE, "Upload Database QC"),
        (MENU_DELETE_CAMPAIGN, "Delete Campaign"),
        (MENU_MANAGE_USER, "Manage User"),
        (MENU_MANAGE_ROLE, "Manage Role"),
        (MENU_ROLE_HIERARCHY, "Hierarki Role & Menu"),
    ]),
    ("Results", [
        (RESULTS_EVALUATION_DETAIL, "Detail evaluasi (Executive Summary & skor)"),
        (RESULTS_CRITICAL_FAILURE, "Critical Failure(s)"),
        (RESULTS_CATEGORY_SCORE, "Kolom Bobot & Skor pada Ringkasan Kategori"),
        (MANUAL_STATUS_COLUMN, "Kolom Manual Status"),
        (MANUAL_STATUS_SET, "Manual Status — Set / Ubah"),
        (MANUAL_STATUS_DIRECT, "Manual Status — tetapkan langsung (tanpa approval)"),
        (MANUAL_STATUS_REVIEW_TL, "Manual Status — review tahap Team Leader QC"),
        (MANUAL_STATUS_REVIEW_SPQ, "Manual Status — approval final SPQ Head"),
        (ERROR_CODE_APPEAL, "Error Code — ajukan banding"),
        (ERROR_CODE_DIRECT_EDIT, "Error Code — edit langsung"),
        (ERROR_CODE_REVIEW_TL, "Error Code — review banding tahap TL QC"),
        (ERROR_CODE_REVIEW_SPQ, "Error Code — approval banding SPQ Head"),
        (DOCUMENT_UPLOAD, "Upload dokumen pendukung"),
        (DOCUMENT_VIEW, "Lihat dokumen pendukung"),
        (DOCUMENT_VERIFICATION_TABLE, "Tabel perbandingan OCR dokumen vs TMS/Ascend"),
        (QC_MANUAL_CHECK_APPROVE, "Tandai tiket sudah dicek (QC)"),
        (RESULTS_FILTER_QC_SIDE, "Filter hierarki memakai dropdown QC / QC Support"),
        (RESULTS_EXPORT_VERIFICATION, "Export XLSX agregat per kategori verifikasi"),
    ]),
    ("Stats", [
        (STATS_FAILURE_REASON, "Tab Failure Reason"),
        (STATS_QC_PERFORMANCE, "Tabel Hierarki Error Rate QC"),
        (STATS_RISK_BASE, "Kolom Risk Base"),
        (STATS_RISK_SYSTEM_NEW, "Kolom Risk System & Risk New"),
    ]),
    ("Administrasi", [
        (ADMIN_USER_WRITE, "Kelola user"),
        (ADMIN_ROLE_WRITE, "Kelola role"),
        (ADMIN_CAMPAIGN_WRITE, "Upload / hapus campaign"),
        (ADMIN_SALES_DATABASE_WRITE, "Kelola Database Sales"),
        (ADMIN_QC_DATABASE_WRITE, "Kelola Database QC"),
        (ADMIN_TICKET_DELETE, "Hapus tiket"),
        (QC_ASSIGNMENT_WRITE, "Assign ticket QC"),
        (TRANSCRIPT_UPLOAD, "Upload transcript"),
        (AUDIO_UPLOAD, "Upload audio"),
    ]),
]

# --- Cakupan data (memilih algoritma penyempitan di api/qc_scope.py) ---
SCOPE_ALL = "all"                    # tidak dipersempit
SCOPE_QC_ASSIGNED = "qc_assigned"    # hanya tiket yang di-assign ke user ini
SCOPE_QC_SUPPORT_OWN = "qc_support_own"  # hanya tiket yang di-upload QC Support
SCOPE_SALES_AM = "sales_am"          # agent di bawah satu Area Manager
SCOPE_SALES_TL = "sales_tl"          # agent di bawah satu Team Leader
SCOPE_SALES_AGENT = "sales_agent"    # tiket milik agent itu sendiri

DATA_SCOPES = [
    (SCOPE_ALL, "Semua tiket"),
    (SCOPE_QC_ASSIGNED, "Hanya tiket yang di-assign kepadanya (QC)"),
    (SCOPE_QC_SUPPORT_OWN, "Hanya tiket yang di-upload sendiri (QC Support)"),
    (SCOPE_SALES_AM, "Area: semua TL & agent di bawahnya"),
    (SCOPE_SALES_TL, "Tim: agent di bawahnya"),
    (SCOPE_SALES_AGENT, "Tiket miliknya sendiri"),
]

_SALES_SCOPES = {SCOPE_SALES_AM, SCOPE_SALES_TL, SCOPE_SALES_AGENT}


def is_sales_scope(scope: str) -> bool:
    return scope in _SALES_SCOPES


# --- Role bawaan (is_system=True: tidak bisa dihapus) ---
# Setiap entri: (label, data_scope, [permissions])

_QC_SIDE_VIEW = [
    MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS,
    RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE, DOCUMENT_VIEW,
    DOCUMENT_VERIFICATION_TABLE, MANUAL_STATUS_COLUMN,
]

DEFAULT_ROLES = {
    "spq_head": {
        "label": "SPQ Head",
        "data_scope": SCOPE_ALL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
            MENU_MANUAL_CHECK, MENU_PENDING_CHECK, MENU_CAMPAIGNS,
            MENU_SALES_DATABASE, MENU_QC_DATABASE, MENU_UPLOAD_CAMPAIGN,
            MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT, MENU_GET_RESULT,
            MENU_UPLOAD_SALES_DATABASE, MENU_UPLOAD_QC_DATABASE,
            MENU_DELETE_CAMPAIGN,
            MENU_ROLE_HIERARCHY,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_CATEGORY_SCORE,
            MANUAL_STATUS_COLUMN,
            MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_SPQ,
            ERROR_CODE_DIRECT_EDIT, ERROR_CODE_REVIEW_SPQ,
            DOCUMENT_VIEW, DOCUMENT_VERIFICATION_TABLE, RESULTS_EXPORT_VERIFICATION,
            STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
            STATS_RISK_SYSTEM_NEW,
            # Tanpa MENU_MANAGE_USER / MENU_MANAGE_ROLE / ADMIN_USER_WRITE /
            # ADMIN_ROLE_WRITE: menu Administration khusus Admin (10 Agustus 2026).
            ADMIN_CAMPAIGN_WRITE,
            ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE,
            ADMIN_TICKET_DELETE,
            QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
        ],
    },
    # Menu identik dengan SPQ Head, TANPA capability aksi QC — lihat docstring.
    "admin": {
        "label": "Admin",
        "data_scope": SCOPE_ALL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
            MENU_MANUAL_CHECK, MENU_PENDING_CHECK, MENU_CAMPAIGNS,
            MENU_SALES_DATABASE, MENU_QC_DATABASE, MENU_UPLOAD_CAMPAIGN,
            MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT, MENU_GET_RESULT,
            MENU_UPLOAD_SALES_DATABASE, MENU_UPLOAD_QC_DATABASE,
            MENU_DELETE_CAMPAIGN, MENU_MANAGE_USER, MENU_MANAGE_ROLE,
            MENU_ROLE_HIERARCHY,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_CATEGORY_SCORE, MANUAL_STATUS_COLUMN,
            DOCUMENT_UPLOAD, DOCUMENT_VIEW, RESULTS_EXPORT_VERIFICATION,
            STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
            STATS_RISK_SYSTEM_NEW,
            ADMIN_USER_WRITE, ADMIN_ROLE_WRITE, ADMIN_CAMPAIGN_WRITE,
            ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE,
            ADMIN_TICKET_DELETE,
            QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
        ],
    },
    "telesales_head": {
        "label": "Telesales Head",
        "data_scope": SCOPE_ALL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW,
        ],
    },
    "area_manager": {
        "label": "Area Manager",
        "data_scope": SCOPE_SALES_AM,
        "permissions": [
            MENU_STATS, MENU_RESULTS, RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW,
        ],
    },
    "team_leader": {
        "label": "Team Leader Sales",
        "data_scope": SCOPE_SALES_TL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, RESULTS_CATEGORY_SCORE,
            DOCUMENT_UPLOAD, DOCUMENT_VIEW,
        ],
    },
    "sales_agent": {
        "label": "Sales Agent",
        "data_scope": SCOPE_SALES_AGENT,
        "permissions": [
            MENU_STATS, MENU_RESULTS, RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW,
        ],
    },
    "team_leader_qc": {
        "label": "Team Leader QC",
        "data_scope": SCOPE_ALL,
        "permissions": _QC_SIDE_VIEW + [
            MENU_ASSIGN_TICKET, MENU_MANUAL_CHECK, MENU_PENDING_CHECK,
            MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT,
            RESULTS_CATEGORY_SCORE,
            MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_TL,
            ERROR_CODE_DIRECT_EDIT, ERROR_CODE_REVIEW_TL, RESULTS_FILTER_QC_SIDE,
            STATS_QC_PERFORMANCE, STATS_RISK_BASE, STATS_RISK_SYSTEM_NEW,
            QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
        ],
    },
    # RESULTS_CATEGORY_SCORE sengaja TIDAK diberikan: QC menilai lolos/tidaknya
    # kategori, bukan angka bobot & skornya (showCategoryScore = !isQc).
    "qc": {
        "label": "QC",
        "data_scope": SCOPE_QC_ASSIGNED,
        "permissions": _QC_SIDE_VIEW + [
            MENU_MANUAL_CHECK, MENU_PENDING_CHECK,
            MANUAL_STATUS_SET, ERROR_CODE_APPEAL, STATS_RISK_BASE,
            QC_MANUAL_CHECK_APPROVE,
        ],
    },
    # Tanpa MENU_STATS — QC Support memang tidak punya Statistics.
    "qc_support": {
        "label": "QC Support",
        "data_scope": SCOPE_QC_SUPPORT_OWN,
        "permissions": [
            MENU_RESULTS, MENU_TRANSCRIPTS, MENU_UPLOAD_AUDIO,
            MENU_UPLOAD_TRANSCRIPT,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW, MANUAL_STATUS_COLUMN,
            TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
        ],
    },
    # Showcase read-only: tidak punya satu pun capability tulis kecuali upload
    # transcript (supaya demo end-to-end bisa diperagakan).
    "demo": {
        "label": "Demo",
        "data_scope": SCOPE_ALL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, MENU_CAMPAIGNS, MENU_UPLOAD_TRANSCRIPT,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW, MANUAL_STATUS_COLUMN,
            STATS_RISK_BASE, STATS_RISK_SYSTEM_NEW,
            TRANSCRIPT_UPLOAD,
        ],
    },
}

# Role yang tidak boleh kehilangan kendali atas sistem: UI Manage Role menolak
# menghapusnya dan menolak mencabut ADMIN_ROLE_WRITE dari dirinya sendiri.
PROTECTED_ROLES = {"spq_head", "admin"}
