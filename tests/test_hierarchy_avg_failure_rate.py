"""Avg Failure Rate untuk tab **Hierarki Failure Rate**.

Sejak 2 September 2026 hierarki menampilkan rasionya sebagai **kelipatan** ("2.8x"),
bukan persen. Alasannya: satu tiket Not Qualified menyumbang SEMUA risk base-nya
(``risk_base_tally``), sehingga pembilangnya rutin melebihi penyebut dan angka
lama melewati 100% — tidak terbaca sebagai persentase.

Penyebutnya **Total Recording** (jumlah rekaman/PDF yang dinilai), yaitu kolom
tepat di sebelah kiri rasionya di tabel AM -> TL -> Agent. Sempat dipindah ke
tiket Not Qualified pada 2 September 2026 pagi lalu dikembalikan sore harinya
bersamaan dengan penggantian nama kolom Submissions -> Total Recording dan
Tiket -> Submission.

Overview per campaign dan tabel Daftar QC SENGAJA tidak ikut berubah — lihat
``_rate_of`` yang tetap dipertahankan untuk keduanya.
"""

from compliance.stats_aggregate import (
    _avg_of,
    _build_hierarchy,
    _rate_of,
    _risk_node,
)


def _acc(**kw):
    """Akumulator satu agent dengan semua kunci yang dibaca hierarki."""
    base = {"submissions": 0, "transcripts": 0, "errors": 0, "approve": 0,
            "pending": 0, "H": 0, "M": 0, "L": 0, "N": 0, "O": 0}
    base.update(kw)
    return base


# ---- _avg_of --------------------------------------------------------------

def test_avg_of_membagi_total_risk_dengan_total_recording():
    """1550 total failure atas 566 rekaman = 2.7 kali lipat."""
    assert _avg_of({"H": 800, "M": 600, "L": 150}, 566) == 2.7


def test_avg_of_nol_recording_tidak_meledak():
    """Belum ada rekaman dinilai: 0.0, bukan ZeroDivisionError."""
    assert _avg_of({"H": 5, "M": 0, "L": 0}, 0) == 0.0


def test_avg_of_mengabaikan_system_dan_new():
    """Sama seperti _rate_of: hanya H/M/L yang dihitung, O dan N tidak."""
    assert _avg_of({"H": 2, "M": 0, "L": 0, "O": 99, "N": 99}, 2) == 1.0


def test_avg_of_bukan_persen():
    """Nilainya rasio, jadi 100x lebih kecil dari _rate_of dengan penyebut sama."""
    risk = {"H": 10, "M": 0, "L": 0}
    assert _avg_of(risk, 5) == 2.0
    assert _rate_of(risk, 5) == 200.0


def test_avg_of_dibulatkan_satu_desimal():
    assert _avg_of({"H": 10, "M": 0, "L": 0}, 3) == 3.3


# ---- _risk_node -----------------------------------------------------------

def test_risk_node_memakai_total_recording_sebagai_penyebut():
    """Penyebutnya ``transcripts``, BUKAN ``errors`` dan bukan jumlah tiket."""
    node = _risk_node(_acc(submissions=334, transcripts=566, errors=280,
                           H=800, M=600, L=150))
    assert node["total_risk"] == 1550
    # Kolom "Total Recording" = transcripts; kolom "Submission" = jumlah tiket.
    assert node["submissions"] == 566
    assert node["ticket_count"] == 334
    assert node["error_rate"] == 2.7  # 1550/566, bukan 1550/280 dan bukan 1550/334


def test_risk_node_tanpa_transcripts_jatuh_ke_submissions():
    """Snapshot lama tanpa kunci ``transcripts``: penyebutnya jumlah tiket.

    Kunci ``transcripts`` sengaja DIHAPUS, bukan disetel 0: ``dict.get`` hanya
    jatuh ke default bila kuncinya tidak ada, dan snapshot lama memang belum
    pernah menuliskannya.
    """
    acc = _acc(submissions=10, errors=4, H=20, M=0, L=0)
    del acc["transcripts"]
    node = _risk_node(acc)
    assert node["error_rate"] == 2.0  # 20/10


def test_risk_node_tanpa_recording():
    node = _risk_node(_acc(submissions=0, transcripts=0, errors=0))
    assert node["error_rate"] == 0.0


# ---- _build_hierarchy -----------------------------------------------------

def test_all_telesales_memakai_total_transcripts():
    """KPI All Telesales dibagi total rekaman milik pemanggil, bukan total_err."""
    acc = {"a1": _acc(submissions=334, transcripts=566, errors=280,
                      H=800, M=600, L=150)}
    meta = {"a1": {"agent_id": "A1", "name": "Agent Satu",
                   "area_manager": "AM1", "team_leader": "TL1"}}
    out = _build_hierarchy(acc, meta, total_eval=334, total_err=280,
                           total_transcripts=566)
    allt = out["all_telesales"]
    assert allt["submissions"] == 566      # Total Recording
    assert allt["ticket_count"] == 334     # Submission
    assert allt["errors"] == 280
    assert allt["error_rate"] == 2.7


def test_all_telesales_tanpa_total_transcripts_jatuh_ke_total_eval():
    """``total_transcripts=None``: penyebutnya total_eval, bukan meledak."""
    acc = {"a1": _acc(submissions=100, transcripts=100, errors=10, H=20, M=10, L=0)}
    meta = {"a1": {"agent_id": "A1", "name": "Agent Satu",
                   "area_manager": "AM1", "team_leader": "TL1"}}
    out = _build_hierarchy(acc, meta, total_eval=100, total_err=10)
    assert out["all_telesales"]["error_rate"] == 0.3  # 30/100


def test_simpul_pohon_ikut_memakai_total_recording():
    """AM / TL / Agent memakai rumus yang sama dengan All Telesales."""
    acc = {"a1": _acc(submissions=50, transcripts=100, errors=10, H=20, M=10, L=0)}
    meta = {"a1": {"agent_id": "A1", "name": "Agent Satu",
                   "area_manager": "AM1", "team_leader": "TL1"}}
    out = _build_hierarchy(acc, meta, total_eval=50, total_err=10,
                           total_transcripts=100)
    am = out["area_managers"][0]
    tl = am["team_leaders"][0]
    agent = tl["agents"][0]
    for node in (am, tl, agent):
        assert node["error_rate"] == 0.3   # 30 risk / 100 recording
        assert node["submissions"] == 100  # Total Recording
        assert node["ticket_count"] == 50  # Submission
