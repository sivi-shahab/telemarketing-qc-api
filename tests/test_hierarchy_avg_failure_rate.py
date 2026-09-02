"""Avg Failure Rate untuk tab **Hierarki Failure Rate**.

Sejak 2 September 2026 hierarki memakai ``Total Failure ÷ Not Qualified`` dan
menampilkannya sebagai kelipatan ("4.5x"), bukan ``÷ Submissions`` dalam persen.
Alasannya: satu tiket Not Qualified bisa membawa banyak risk base, sehingga angka
lama rutin melewati 100% dan tidak terbaca sebagai persentase.

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
    base = {"submissions": 0, "errors": 0, "approve": 0, "pending": 0,
            "H": 0, "M": 0, "L": 0, "N": 0, "O": 0}
    base.update(kw)
    return base


# ---- _avg_of --------------------------------------------------------------

def test_avg_of_membagi_total_risk_dengan_not_qualified():
    """1116 total failure atas 248 tiket Not Qualified = 4.5 kali lipat."""
    assert _avg_of({"H": 600, "M": 400, "L": 116}, 248) == 4.5


def test_avg_of_nol_not_qualified_tidak_meledak():
    """Belum ada tiket Not Qualified: 0.0, bukan ZeroDivisionError."""
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

def test_risk_node_memakai_not_qualified_sebagai_penyebut():
    """Penyebutnya ``errors``, bukan ``submissions``."""
    node = _risk_node(_acc(submissions=1000, errors=248, H=600, M=400, L=116))
    assert node["total_risk"] == 1116
    assert node["error_rate"] == 4.5  # 1116/248, bukan 1116/1000


def test_risk_node_tanpa_not_qualified():
    node = _risk_node(_acc(submissions=50, errors=0))
    assert node["error_rate"] == 0.0


# ---- _build_hierarchy -----------------------------------------------------

def test_all_telesales_memakai_total_err():
    """KPI All Telesales dibagi total tiket Not Qualified milik pemanggil."""
    acc = {"a1": _acc(submissions=1000, errors=248, H=600, M=400, L=116)}
    meta = {"a1": {"agent_id": "A1", "name": "Agent Satu",
                   "area_manager": "AM1", "team_leader": "TL1"}}
    out = _build_hierarchy(acc, meta, total_eval=1000, total_err=248)
    allt = out["all_telesales"]
    assert allt["submissions"] == 1000
    assert allt["errors"] == 248
    assert allt["error_rate"] == 4.5


def test_simpul_pohon_ikut_memakai_not_qualified():
    """AM / TL / Agent memakai rumus yang sama dengan All Telesales."""
    acc = {"a1": _acc(submissions=100, errors=10, H=20, M=5, L=0)}
    meta = {"a1": {"agent_id": "A1", "name": "Agent Satu",
                   "area_manager": "AM1", "team_leader": "TL1"}}
    out = _build_hierarchy(acc, meta, total_eval=100, total_err=10)
    am = out["area_managers"][0]
    tl = am["team_leaders"][0]
    agent = tl["agents"][0]
    for node in (am, tl, agent):
        assert node["error_rate"] == 2.5  # 25 risk / 10 not qualified
