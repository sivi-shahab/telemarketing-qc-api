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
* Kelanjutan kebijakan yang sama (14 Agustus 2026): SELURUH pengurusan data —
  Campaigns, Database Sales, Database QC, semua menu Upload Data, dan Delete
  Campaign — juga pindah ke `admin`. Lihat `ADMIN_ONLY_PERMISSIONS` di bawah;
  daftar itu bukan sekadar catatan, ia yang menutup menu-menu tersebut dari role
  mana pun di luar `ADMIN_LIKE_ROLES`, termasuk role buatan operator.
* `demo` menyusul sebagai role admin-like (27 Agustus 2026): izinnya PERSIS sama
  dengan `admin` — satu daftar `_ADMIN_PERMISSIONS` dipakai berdua supaya keduanya
  tidak bisa berbeda diam-diam. Demo bukan lagi showcase read-only; akun demo kini
  bisa melakukan apa pun yang bisa dilakukan Admin, termasuk mengelola user & role
  dan menghapus campaign. Satu-satunya tambahan di luar daftar Admin adalah
  `RESULTS_LAYOUT_DEMO` — varian TAMPILAN kolom Results, bukan hak akses. Diminta eksplisit; kalau demo mau dikembalikan menjadi
  read-only, yang diubah adalah entri `demo` di `DEFAULT_ROLES` DAN keanggotaannya
  di `ADMIN_LIKE_ROLES` / `PROTECTED_ROLES`.
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
MENU_REPROCESS_TICKETS = "menu.reprocess_tickets"
MENU_DELETE_CAMPAIGN = "menu.delete_campaign"
MENU_MANAGE_USER = "menu.manage_user"
MENU_MANAGE_ROLE = "menu.manage_role"
MENU_ROLE_HIERARCHY = "menu.role_hierarchy"

# --- Fitur di dalam halaman Results ---
RESULTS_EVALUATION_DETAIL = "results.evaluation_detail"
RESULTS_CRITICAL_FAILURE = "results.critical_failure"
RESULTS_CATEGORY_SCORE = "results.category_score"
# Keterangan LENGKAP di bawah badge AI Status (28 Agustus 2026). Tanpa capability ini
# sebuah role hanya melihat keterangan "Menunggu dokumen ..." — satu-satunya alasan
# yang memang bisa mereka tindaklanjuti sendiri. Yang disembunyikan:
#   · kekurangan data acuan (Transkrip/TMS/Agent/Ascend Kosong) — urusan operasional
#     data, bukan kinerja agent, dan menyebutkannya di layar sales hanya mengundang
#     salah paham bahwa agent-nya yang keliru;
#   · sebab Not Qualified (Error non-tolerable, Terindikasi Badword) — itu vonis QC,
#     sejalan dengan Critical Failure(s) yang juga tidak dibuka ke sisi sales.
# Disaring di BACKEND, bukan disembunyikan di layar: alasannya tidak ikut terkirim.
RESULTS_STATUS_REASON_FULL = "results.status_reason_full"
# Mengunggah dokumen pendukung untuk tiket yang SUDAH Not Qualified (28 Agustus 2026).
# Tanpa capability ini tombol Upload Document mati begitu AI Status tiket = Not
# Qualified: dokumen susulan tidak lagi mengubah vonis, jadi memintanya dari Team
# Leader hanya memindahkan pekerjaan sia-sia. Admin & Demo tetap memilikinya karena
# kadang perlu melengkapi berkas untuk keperluan arsip / koreksi data.
DOCUMENT_UPLOAD_LOCKED_TICKET = "results.document.upload_locked_ticket"
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
# Export XLSX SEMUA tiket pada rentang tanggal & filter yang sedang dipilih di
# Results — satu baris per tiket, bukan per baris verifikasi. Pengganti tombol
# Export Agregat bagi SPQ Head (14 Agustus 2026): yang dibutuhkan pengawas adalah
# tarikan lengkap sebuah periode, bukan daftar temuan satu kategori.
RESULTS_EXPORT_TICKETS = "results.export.tickets"

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
# Reproses MASSAL seluruh tiket sebuah campaign memakai konfigurasi campaign
# terbaru, lalu membuang row lama sehingga tersisa satu row per ticket id.
# TERPISAH dari ADMIN_TICKET_DELETE: yang ini menghapus tiket lama sebagai efek
# samping dari sebuah reproses, dan biayanya adalah satu panggilan LLM per tiket.
ADMIN_TICKET_REPROCESS = "admin.ticket.reprocess"
# Sakelar kebijakan tenggat H+2 dokumen pendukung (menu Results). MEMBACA status
# sakelarnya tidak butuh capability — indikatornya tampil untuk semua yang bisa
# membuka Results, karena PENDING/FAIL yang mereka lihat bergantung padanya.
ADMIN_DOC_SLA_WRITE = "admin.doc_sla.write"
QC_ASSIGNMENT_WRITE = "qc.assignment.write"
TRANSCRIPT_UPLOAD = "transcript.upload"
AUDIO_UPLOAD = "audio.upload"

# Tata letak tabel Results versi Demo (27 Agustus 2026). Bukan hak akses melainkan
# varian TAMPILAN: kolom Number of Calls & Export dilepas, Call Duration dipecah
# per PDF, "Critical Failure(s)" dijuduli SCOREBOMB, dan kolom Passing Grade
# diganti "Grade" (nilai akhir / passing grade). Dibuat sebagai capability, bukan
# perbandingan `role == "demo"` di Vue, supaya tetap satu mekanisme dengan kolom
# lain di halaman itu — dan supaya bisa dipindah ke role lain lewat Manage Role
# tanpa menyentuh kode.
RESULTS_LAYOUT_DEMO = "results.layout.demo"

ALL_PERMISSIONS = [
    MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
    MENU_MANUAL_CHECK, MENU_PENDING_CHECK, MENU_CAMPAIGNS, MENU_SALES_DATABASE,
    MENU_QC_DATABASE, MENU_UPLOAD_CAMPAIGN, MENU_UPLOAD_AUDIO,
    MENU_UPLOAD_TRANSCRIPT, MENU_GET_RESULT, MENU_UPLOAD_SALES_DATABASE,
    MENU_UPLOAD_QC_DATABASE, MENU_REPROCESS_TICKETS, MENU_DELETE_CAMPAIGN,
    MENU_MANAGE_USER,
    MENU_MANAGE_ROLE, MENU_ROLE_HIERARCHY,
    RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE, RESULTS_CATEGORY_SCORE,
    RESULTS_STATUS_REASON_FULL,
    RESULTS_LAYOUT_DEMO,
    MANUAL_STATUS_COLUMN,
    MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_TL,
    MANUAL_STATUS_REVIEW_SPQ, ERROR_CODE_APPEAL, ERROR_CODE_DIRECT_EDIT,
    ERROR_CODE_REVIEW_TL, ERROR_CODE_REVIEW_SPQ, DOCUMENT_UPLOAD,
    DOCUMENT_UPLOAD_LOCKED_TICKET, DOCUMENT_VIEW,
    DOCUMENT_VERIFICATION_TABLE,
    QC_MANUAL_CHECK_APPROVE, RESULTS_FILTER_QC_SIDE, RESULTS_EXPORT_VERIFICATION,
    RESULTS_EXPORT_TICKETS,
    STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
    STATS_RISK_SYSTEM_NEW,
    ADMIN_USER_WRITE, ADMIN_ROLE_WRITE, ADMIN_CAMPAIGN_WRITE,
    ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE, ADMIN_TICKET_DELETE,
    ADMIN_TICKET_REPROCESS, ADMIN_DOC_SLA_WRITE,
    QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
]

# Capability yang HANYA boleh dimiliki role ``admin`` (permintaan 14 Agustus 2026).
# Pengurusan data — campaign, database sales/QC, seluruh Upload Data, Delete
# Campaign — bukan lagi pekerjaan SPQ Head maupun sisi QC.
#
# Ini bukan daftar dokumentasi: `api/routers/role.py` menolak menyimpan capability
# ini pada role di luar ``ADMIN_LIKE_ROLES`` dan menyembunyikannya dari daftar
# checkbox Manage Role, sehingga tidak bisa dihidupkan kembali lewat role buatan
# operator. Menu
# menghilang DAN endpoint-nya ikut tertutup, karena keduanya membaca daftar yang
# sama.
#
# Konsekuensi yang disadari & dikonfirmasi: `qc_support` kehilangan Upload Audio /
# Upload Transcript. Karena cakupan datanya "hanya tiket yang di-upload sendiri",
# role itu praktis tidak lagi punya tiket baru untuk dilihat.
ADMIN_ONLY_PERMISSIONS = {
    MENU_CAMPAIGNS, MENU_SALES_DATABASE, MENU_QC_DATABASE,
    MENU_UPLOAD_CAMPAIGN, MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT,
    MENU_GET_RESULT, MENU_UPLOAD_SALES_DATABASE, MENU_UPLOAD_QC_DATABASE,
    MENU_REPROCESS_TICKETS, MENU_DELETE_CAMPAIGN, MENU_MANAGE_USER,
    MENU_MANAGE_ROLE,
    ADMIN_USER_WRITE, ADMIN_ROLE_WRITE, ADMIN_CAMPAIGN_WRITE,
    ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE, ADMIN_TICKET_REPROCESS,
    ADMIN_DOC_SLA_WRITE,
    TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
}

# --- Penyesuaian untuk login campaign COLLECTION (2 September 2026) ---
#
# Campaign penagihan tidak mengenal alur Assign Ticket -> Manual Check -> Pending
# Check: tiketnya tidak dibagi ke QC perorangan dan tidak ada banding error code.
# Sebaliknya sisi collection justru harus memasukkan bahannya sendiri, jadi Upload
# Audio & Upload Transcript dikembalikan untuknya.
#
# Ini BUKAN role baru dan bukan pencabutan capability dari role. Role ``qc``,
# ``spq_head`` dan ``team_leader_qc`` dipakai BERSAMA oleh login Cashline maupun
# Collection (lihat tabel ``user_campaigns``); mencabutnya dari role akan
# mematikan menu itu untuk Cashline juga. Yang membedakan adalah campaign efektif
# si ORANG — penerapannya di ``api.rbac.collection_adjusted_permissions``, satu
# tempat yang sekaligus menutup menu DAN endpoint-nya.
COLLECTION_REMOVED_PERMISSIONS = frozenset({
    MENU_ASSIGN_TICKET, MENU_MANUAL_CHECK, MENU_PENDING_CHECK,
    # Aksi di balik menu yang dicabut. Kalau ditinggal, halamannya tertutup tapi
    # endpoint-nya masih bisa dipanggil langsung — gate yang bisa ditembus dengan
    # mengetik URL, persis celah yang pernah ditutup di sisi /tickets-daily.
    QC_ASSIGNMENT_WRITE, QC_MANUAL_CHECK_APPROVE,
})

# Keempatnya ada di ``ADMIN_ONLY_PERMISSIONS`` (kebijakan 14 Agustus 2026: seluruh
# Upload Data milik Admin). Pemberian di sini SENGAJA menembus daftar itu: penjaga
# ADMIN_ONLY berlaku saat role DISIMPAN lewat Manage Role, sedangkan yang ini
# dihitung saat request — jadi capability-nya tidak pernah tersimpan di tabel
# ``roles`` dan tidak bisa dipinjam role lain. Diminta eksplisit untuk campaign
# Collection; kalau kebijakannya dikembalikan, yang dikosongkan adalah daftar ini.
#
# Dropdown campaign di halaman Upload sudah menyempit sendiri mengikuti campaign
# efektif user (``campaignObjectsInScope``), jadi login Collection hanya bisa
# mengunggah ke campaign Collection.
COLLECTION_ADDED_PERMISSIONS = frozenset({
    MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT, AUDIO_UPLOAD, TRANSCRIPT_UPLOAD,
})

# Role yang BOLEH memegang ADMIN_ONLY_PERMISSIONS. Daftar ini yang dipakai
# `api/routers/role.py`, bukan literal ``"admin"``, karena sejak 27 Agustus 2026
# ``demo`` punya izin yang sama persis dengan Admin. Capability-nya tetap tidak
# muncul di form Manage Role (satu-satunya sumbernya adalah `DEFAULT_ROLES` di
# bawah); saat role admin-like disimpan ulang lewat UI, capability tersebut dibawa
# apa adanya dari DB agar tidak diam-diam tercabut.
ADMIN_LIKE_ROLES = {"admin", "demo"}

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
        (MENU_REPROCESS_TICKETS, "Reprocess All Ticket"),
        (MENU_DELETE_CAMPAIGN, "Delete Campaign"),
        (MENU_MANAGE_USER, "Manage User"),
        (MENU_MANAGE_ROLE, "Manage Role"),
        (MENU_ROLE_HIERARCHY, "Hierarki Role & Menu"),
    ]),
    ("Results", [
        (RESULTS_EVALUATION_DETAIL, "Detail evaluasi (Executive Summary & skor)"),
        (RESULTS_CRITICAL_FAILURE, "Critical Failure(s)"),
        (RESULTS_STATUS_REASON_FULL, "Keterangan lengkap di kolom AI Status"),
        (DOCUMENT_UPLOAD_LOCKED_TICKET, "Upload dokumen walau tiket sudah Not Qualified"),
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
        (RESULTS_EXPORT_TICKETS, "Export XLSX semua tiket pada rentang yang dipilih"),
        (RESULTS_LAYOUT_DEMO, "Tata letak kolom versi Demo (Scorebomb & Grade)"),
    ]),
    ("Stats", [
        (STATS_FAILURE_REASON, "Tab Failure Reason"),
        (STATS_QC_PERFORMANCE, "Tabel Hierarki Failure Rate QC"),
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
        (ADMIN_TICKET_REPROCESS, "Reproses tiket (satu tiket / satu campaign)"),
        (ADMIN_DOC_SLA_WRITE, "Ubah kebijakan SLA H+2 dokumen pendukung"),
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
    RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE, RESULTS_STATUS_REASON_FULL,
    DOCUMENT_VIEW, DOCUMENT_VERIFICATION_TABLE, MANUAL_STATUS_COLUMN,
]

# Izin role Admin. Dipakai `admin` DAN `demo` (27 Agustus 2026) — satu sumber
# supaya keduanya tidak pernah berbeda.
_ADMIN_PERMISSIONS = [
        MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
        MENU_MANUAL_CHECK, MENU_PENDING_CHECK, MENU_CAMPAIGNS,
        MENU_SALES_DATABASE, MENU_QC_DATABASE, MENU_UPLOAD_CAMPAIGN,
        MENU_UPLOAD_AUDIO, MENU_UPLOAD_TRANSCRIPT, MENU_GET_RESULT,
        MENU_UPLOAD_SALES_DATABASE, MENU_UPLOAD_QC_DATABASE,
        MENU_REPROCESS_TICKETS,
        MENU_DELETE_CAMPAIGN, MENU_MANAGE_USER, MENU_MANAGE_ROLE,
        MENU_ROLE_HIERARCHY,
        RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
        RESULTS_STATUS_REASON_FULL,
        RESULTS_CATEGORY_SCORE, MANUAL_STATUS_COLUMN,
        DOCUMENT_UPLOAD, DOCUMENT_UPLOAD_LOCKED_TICKET, DOCUMENT_VIEW,
        RESULTS_EXPORT_VERIFICATION, RESULTS_EXPORT_TICKETS,
        STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
        STATS_RISK_SYSTEM_NEW,
        ADMIN_USER_WRITE, ADMIN_ROLE_WRITE, ADMIN_CAMPAIGN_WRITE,
        ADMIN_SALES_DATABASE_WRITE, ADMIN_QC_DATABASE_WRITE,
        ADMIN_TICKET_DELETE, ADMIN_TICKET_REPROCESS,
        QC_ASSIGNMENT_WRITE, TRANSCRIPT_UPLOAD, AUDIO_UPLOAD,
]

DEFAULT_ROLES = {
    "spq_head": {
        "label": "SPQ Head",
        "data_scope": SCOPE_ALL,
        "permissions": [
            MENU_STATS, MENU_RESULTS, MENU_TRANSCRIPTS, MENU_ASSIGN_TICKET,
            MENU_MANUAL_CHECK, MENU_PENDING_CHECK,
            MENU_ROLE_HIERARCHY,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_STATUS_REASON_FULL,
            RESULTS_CATEGORY_SCORE,
            MANUAL_STATUS_COLUMN,
            MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_SPQ,
            ERROR_CODE_DIRECT_EDIT, ERROR_CODE_REVIEW_SPQ,
            DOCUMENT_VIEW, DOCUMENT_VERIFICATION_TABLE,
            RESULTS_EXPORT_TICKETS,
            STATS_FAILURE_REASON, STATS_QC_PERFORMANCE, STATS_RISK_BASE,
            STATS_RISK_SYSTEM_NEW,
            # Tanpa MENU_MANAGE_USER / MENU_MANAGE_ROLE / ADMIN_USER_WRITE /
            # ADMIN_ROLE_WRITE: menu Administration khusus Admin (10 Agustus 2026).
            # Tanpa seluruh ADMIN_ONLY_PERMISSIONS (Campaigns, Database Sales &
            # QC, Upload Data, Delete Campaign): pengurusan data pindah ke Admin
            # (14 Agustus 2026).
            # Tanpa ADMIN_TICKET_DELETE: tombol Delete di Results dicabut dari SPQ
            # Head pada tanggal yang sama; menghapus tiket tinggal milik Admin.
            # Tanpa RESULTS_EXPORT_VERIFICATION: export agregat per kategori
            # verifikasi juga pindah ke Admin. Gantinya RESULTS_EXPORT_TICKETS —
            # export SEMUA tiket pada rentang tanggal yang sedang dipilih.
            QC_ASSIGNMENT_WRITE,
        ],
    },
    # Menu identik dengan SPQ Head, TANPA capability aksi QC — lihat docstring.
    "admin": {
        "label": "Admin",
        "data_scope": SCOPE_ALL,
        "permissions": list(_ADMIN_PERMISSIONS),
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
    # Tanpa DOCUMENT_VIEW (14 Agustus 2026): sales agent tidak boleh membuka
    # dokumen pendukung tiketnya sendiri. Atasannya (TL Sales sebagai pengunggah,
    # Area Manager, Telesales Head) tetap bisa.
    "sales_agent": {
        "label": "Sales Agent",
        "data_scope": SCOPE_SALES_AGENT,
        "permissions": [
            MENU_STATS, MENU_RESULTS, RESULTS_CATEGORY_SCORE,
        ],
    },
    "team_leader_qc": {
        "label": "Team Leader QC",
        "data_scope": SCOPE_ALL,
        # Tanpa MENU_UPLOAD_AUDIO / MENU_UPLOAD_TRANSCRIPT / TRANSCRIPT_UPLOAD /
        # AUDIO_UPLOAD: seluruh Upload Data pindah ke Admin (14 Agustus 2026).
        "permissions": _QC_SIDE_VIEW + [
            MENU_ASSIGN_TICKET, MENU_MANUAL_CHECK, MENU_PENDING_CHECK,
            RESULTS_CATEGORY_SCORE,
            MANUAL_STATUS_SET, MANUAL_STATUS_DIRECT, MANUAL_STATUS_REVIEW_TL,
            ERROR_CODE_DIRECT_EDIT, ERROR_CODE_REVIEW_TL, RESULTS_FILTER_QC_SIDE,
            STATS_QC_PERFORMANCE, STATS_RISK_BASE, STATS_RISK_SYSTEM_NEW,
            QC_ASSIGNMENT_WRITE,
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
    #
    # Sejak 14 Agustus 2026 juga tanpa Upload Audio / Upload Transcript. Ini
    # melumpuhkan role tersebut dan itu disengaja: cakupan datanya
    # ``qc_support_own`` (hanya tiket yang ia upload sendiri), jadi tanpa hak
    # upload ia tidak akan pernah punya tiket baru. Dikonfirmasi sebagai
    # kebijakan; kalau role ini mau dihidupkan lagi, yang dikembalikan adalah
    # keempat capability upload-nya, bukan cakupan datanya.
    "qc_support": {
        "label": "QC Support",
        "data_scope": SCOPE_QC_SUPPORT_OWN,
        "permissions": [
            MENU_RESULTS, MENU_TRANSCRIPTS,
            RESULTS_EVALUATION_DETAIL, RESULTS_CRITICAL_FAILURE,
            RESULTS_STATUS_REASON_FULL,
            RESULTS_CATEGORY_SCORE, DOCUMENT_VIEW, MANUAL_STATUS_COLUMN,
        ],
    },
    # Showcase. Sampai 14 Agustus 2026 read-only; sejak 27 Agustus 2026 izinnya
    # PERSIS sama dengan Admin (`_ADMIN_PERMISSIONS`) supaya demo end-to-end —
    # upload campaign, upload audio/transkrip, sampai kelola user — bisa dijalankan
    # dari akun demo itu sendiri. Konsekuensinya akun demo TIDAK lagi aman untuk
    # dipinjamkan: ia bisa menghapus campaign dan mengubah role.
    "demo": {
        "label": "Demo",
        "data_scope": SCOPE_ALL,
        # Izin Admin, MINUS kolom Manual Status, PLUS varian tampilan Results.
        # Keduanya soal tampilan, bukan kewenangan: demo tidak pernah bisa MENGUBAH
        # Manual Status (MANUAL_STATUS_SET memang tidak dimiliki Admin maupun demo),
        # jadi mencabut kolomnya hanya menyembunyikan vonis QC dari layar demo —
        # berikut dropdown filternya, yang memang ikut gate yang sama.
        "permissions": (
            [p for p in _ADMIN_PERMISSIONS if p != MANUAL_STATUS_COLUMN]
            + [RESULTS_LAYOUT_DEMO]
        ),
    },
}

# Role yang tidak boleh kehilangan kendali atas sistem: UI Manage Role menolak
# menghapusnya dan menolak mencabut ADMIN_ROLE_WRITE darinya. ``demo`` ikut sejak
# 27 Agustus 2026 karena izinnya kini setara Admin.
PROTECTED_ROLES = {"spq_head", "admin", "demo"}
