"""PPT Error Rate: pengelompokan campaign + bentuk data deck (diport dari
4-service@dcc15d3/3d6a3de, 6 Oktober 2026).

Tanpa DB. Smoke test di bawah merakit deck dari data berbentuk persis keluaran
``export_error_rate_pptx`` — tanpa itu perubahan kontrak field antara router dan
``compliance.ppt_error_rate`` baru ketahuan saat user menekan tombolnya.
"""
from compliance.ppt_error_rate import build_error_rate_pptx

from api.routers import stats as st


def test_grup_mengikuti_ppt_acuan_dan_activation_dibuang(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "")
    groups = st._ppt_group_campaigns(
        ["NTB", "Cashline", "Activation", "Retention", "MegaBill", "Lain"]
    )
    assert groups == [
        ("USAGE", ["Cashline", "MegaBill"]),
        ("CARD", ["NTB"]),
        ("RETENTION", ["Retention"]),
        ("LAINNYA", ["Lain"]),
    ]


def test_campaign_collection_tidak_masuk_deck(monkeypatch):
    """Keputusan 6 Oktober 2026: Collection-kind dikeluarkan seperti Activation,
    bukan ditumpuk di grup LAINNYA."""
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection,Complaint Handling")
    groups = st._ppt_group_campaigns(["Cashline", "Collection", "complaint handling "])
    assert groups == [("USAGE", ["Cashline"])]


def _node(name, sub, h, m, l, appr, **extra):
    total = h + m + l
    return {"name": name, "ticket_count": sub, "risk_high": h, "risk_medium": m,
            "risk_low": l, "approve": appr,
            "error_rate": round(total / sub * 100, 2) if sub else 0.0, **extra}


def test_total_am_dijumlah_dari_campaign_yang_tampil(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    snap = {"hierarchy_by_campaign": {
        "Cashline": {"area_managers": [_node("AM1", 10, 1, 1, 0, 1, team_leaders=[])]},
        "NTB": {"area_managers": [_node("AM1", 10, 0, 0, 2, 0, team_leaders=[])]},
        "Activation": {"area_managers": [_node("AM1", 50, 9, 9, 9, 0, team_leaders=[])]},
        "Collection": {"area_managers": [_node("AM1", 50, 9, 9, 9, 0, team_leaders=[])]},
    }}
    am, spv = st._am_spv_tables(snap)
    total = [r for r in am if r[9]]
    assert total == [["AM1", "TOTAL", 20, 4, 20.0, 1, 1, 2, 1, True]]
    assert {r[1] for r in am if not r[9]} == {st._campaign_label("Cashline"), st._campaign_label("NTB")}
    assert spv == []


def _tlo(i):
    return {"agent_id": f"A{i}", "name": f"Agent {i}", "dedicate": "-", "spv": "SPV",
            "aging": "0-6 Bulan", "ticket_count": 10, "error_count": 2, "error_rate": 20.0,
            "risk_high": 1, "risk_medium": 1, "risk_low": 0, "approved": 0}


def test_deck_bisa_dirakit_dari_bentuk_data_router():
    stat = {"submission": 10, "error": 2, "h": 1, "m": 1, "l": 0, "approved": 1, "error_rate": 20.0}
    data = {
        "period_previous": {"label": "September 2026", "key": "2026-09"},
        "period_current": {"label": "Oktober 2026", "key": "2026-10"},
        "trend_rows": [
            {"label": "USAGE", "is_group": True},
            {"label": "Cashline", "prev": dict(stat), "curr": dict(stat)},
            {"label": "TOTAL USAGE", "is_total": True, "prev": dict(stat), "curr": dict(stat)},
            {"label": "GRAND TOTAL", "is_total": True, "prev": dict(stat), "curr": dict(stat)},
        ],
        "am_table": [["AM1", "Cashline", 10, 2, 20.0, 1, 1, 0, 1, False],
                     ["AM1", "TOTAL", 10, 2, 20.0, 1, 1, 0, 1, True]],
        "spv_table": [["SPV", "Cashline", 10, 2, 20.0, 1, 1, 0, 1, False],
                      ["SPV", "TOTAL", 10, 2, 20.0, 1, 1, 0, 1, True]],
        "top_tlo": {
            "0-6 Bulan": {"rows": [_tlo(i) for i in range(3)], "total_tlo": 3, "over_6": 3,
                          "reasons": ["Agent tidak menyebutkan nama agent"]},
            "6-12 Bulan": {"rows": [], "total_tlo": 0, "over_6": 0, "reasons": []},
            "> 12 Bulan": {"rows": [], "total_tlo": 0, "over_6": 0, "reasons": []},
        },
        "error_reason": [{
            "group": "USAGE", "label": "Cashline",
            "categories": [{"category": "Pembukaan", "example": "Agent tidak menyapa", "fail_count": 3}],
            "top_agents": [_tlo(0)],
        }],
    }
    buf = build_error_rate_pptx(data)
    assert buf.getvalue()[:2] == b"PK", "file .pptx = arsip zip"
