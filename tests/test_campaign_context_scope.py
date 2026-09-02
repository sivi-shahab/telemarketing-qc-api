"""Pemetaan campaign App B -> ``context`` App C, penyaring baris /tickets-daily.

Regression guard untuk kebocoran RBAC di halaman Recording Tickets & Assign
Ticket: keduanya dulu menembak App C langsung dari browser dan menampilkan
SELURUH baris, sehingga login yang dibatasi ke campaign ``Collection`` tetap
membaca tiket ``ACT02``/``LOC26``. ``campaignsInScope`` di dashboard hanya
menyaring isi dropdown, bukan barisnya, dan ``effective_campaigns_for`` tidak
pernah dilewati sama sekali.

Penyaringan tidak bisa memakai nama campaign apa adanya: nama App B
(``Cashline``/``Collection``) BUKAN kode campaign App C (``ACT02``, ``CLENTB``,
``LOC26``, ``011``, ``MCS``, ``MP01``, ``NTB002``). Yang dipakai adalah field
``context`` (``cashline``/``ntb``/``usage``/``card``/``alloblast``/``tbfu``),
dipetakan lewat env ``CAMPAIGN_CONTEXT_MAP``.
"""
import pytest

from api import campaign_context as cc


# --------------------------------------------------------------------------
# parse_context_map
# --------------------------------------------------------------------------

def test_parse_maps_name_to_context_set():
    m = cc.parse_context_map("Cashline:cashline,Collection:collection")
    assert m == {
        "cashline": frozenset({"cashline"}),
        "collection": frozenset({"collection"}),
    }


def test_parse_accepts_several_contexts_per_campaign():
    m = cc.parse_context_map("Cashline:cashline|usage")
    assert m["cashline"] == frozenset({"cashline", "usage"})


def test_parse_normalises_case_and_spacing():
    m = cc.parse_context_map("  CasHLine : CashLine | USAGE ,  ")
    assert m == {"cashline": frozenset({"cashline", "usage"})}


def test_parse_empty_string_gives_empty_map():
    assert cc.parse_context_map("") == {}
    assert cc.parse_context_map(None) == {}


def test_parse_skips_entries_without_a_context():
    # "Collection:" -> pemetaan tanpa context; dibuang, bukan dijadikan set kosong,
    # supaya tidak ada dua bentuk yang artinya sama.
    assert cc.parse_context_map("Collection:,Cashline:cashline") == {
        "cashline": frozenset({"cashline"})
    }


# --------------------------------------------------------------------------
# contexts_for  -- None berarti TIDAK dibatasi, bukan "tidak melihat apa pun"
# --------------------------------------------------------------------------

MAP = {
    "cashline": frozenset({"cashline"}),
    "collection": frozenset({"collection"}),
}


def test_contexts_for_none_is_unrestricted():
    assert cc.contexts_for(None, MAP) is None


def test_contexts_for_single_campaign():
    assert cc.contexts_for(["Collection"], MAP) == frozenset({"collection"})


def test_contexts_for_unions_several_campaigns():
    assert cc.contexts_for(["Cashline", "Collection"], MAP) == frozenset(
        {"cashline", "collection"}
    )


def test_contexts_for_ignores_case_and_spacing():
    assert cc.contexts_for(["  cOLLection "], MAP) == frozenset({"collection"})


def test_contexts_for_unmapped_campaign_fails_closed():
    """Campaign yang tidak ada di CAMPAIGN_CONTEXT_MAP tidak menyumbang context.

    Hasilnya set KOSONG, dan set kosong berarti "tidak melihat baris apa pun" --
    sengaja BUKAN None. Menyamakan keduanya akan membuat campaign yang belum
    dipetakan justru membuka seluruh data, persis bug yang ditutup di sini.
    """
    assert cc.contexts_for(["NTB"], MAP) == frozenset()


def test_contexts_for_empty_list_sees_nothing():
    # ``effective_campaigns_for`` memakai list kosong untuk "dibatasi ke tidak ada
    # apa pun" (mis. irisan role x assign yang kosong).
    assert cc.contexts_for([], MAP) == frozenset()


# --------------------------------------------------------------------------
# filter_items -- bentuk baris mengikuti payload /tickets-daily App C
# --------------------------------------------------------------------------

ITEMS = [
    {"id": "a", "campaign": "ACT02", "context": "ntb"},
    {"id": "b", "campaign": "CLENTB", "context": "cashline"},
    {"id": "c", "campaign": "LOC26", "context": "usage"},
    {"id": "d", "campaign": "MCS", "context": "CASHLINE"},
    {"id": "e", "campaign": "X", "context": None},
]


def test_filter_none_passes_everything_through():
    assert cc.filter_items(ITEMS, None) == ITEMS


def test_filter_keeps_only_allowed_contexts():
    kept = cc.filter_items(ITEMS, frozenset({"cashline"}))
    assert [i["id"] for i in kept] == ["b", "d"]


def test_filter_empty_set_keeps_nothing():
    assert cc.filter_items(ITEMS, frozenset()) == []


def test_filter_drops_rows_without_a_context():
    """Baris tanpa ``context`` tidak bisa dibuktikan masuk cakupan, jadi dibuang.

    Membiarkannya lewat berarti satu field kosong di App C cukup untuk menembus
    pembatasan campaign."""
    kept = cc.filter_items(ITEMS, frozenset({"cashline", "ntb", "usage"}))
    assert "e" not in [i["id"] for i in kept]


def test_filter_matches_context_case_insensitively():
    # Baris "d" punya context "CASHLINE" (huruf besar) di data uji.
    assert [i["id"] for i in cc.filter_items(ITEMS, frozenset({"cashline"}))] == ["b", "d"]


# --------------------------------------------------------------------------
# Endpoint /tickets_daily -- gate yang menutup kebocorannya
# --------------------------------------------------------------------------

from api.routers import tickets_daily as td  # noqa: E402
from services import tickets_daily as tms  # noqa: E402


UPSTREAM = {
    "mode": "yesterday",
    "load_date": "2026-08-27",
    "items": [
        {"id": "a", "campaign": "ACT02", "context": "ntb"},
        {"id": "b", "campaign": "CLENTB", "context": "cashline"},
        {"id": "c", "campaign": "LOC26", "context": "usage"},
    ],
    "total": 3,
    "truncated": False,
}


@pytest.fixture
def stub_app_c(monkeypatch):
    """App C dipalsukan; ``calls`` merekam argumen tiap panggilan."""
    calls = []

    def _fake_fetch_all(**kwargs):
        calls.append(kwargs)
        return dict(UPSTREAM, items=list(UPSTREAM["items"]))

    monkeypatch.setattr(td.tms, "fetch_all", _fake_fetch_all)
    monkeypatch.setenv("CAMPAIGN_CONTEXT_MAP", "Cashline:cashline,Collection:collection")
    return calls


def _call(monkeypatch, scope, **kwargs):
    """Panggil endpoint dengan ``effective_campaigns_for`` yang dipatok ``scope``."""
    monkeypatch.setattr(td, "effective_campaigns_for", lambda db, user: scope)
    params = {"tiket_id": None, "load_date": None}
    params.update(kwargs)
    return td.list_tickets_daily(db=object(), current_user=object(), **params)


def test_unrestricted_login_sees_every_row(monkeypatch, stub_app_c):
    out = _call(monkeypatch, None)
    assert [i["id"] for i in out["items"]] == ["a", "b", "c"]
    assert out["total"] == 3


def test_collection_login_does_not_see_act02_or_loc26(monkeypatch, stub_app_c):
    """Bug yang dilaporkan: login campaign Collection membaca tiket ACT02/LOC26."""
    out = _call(monkeypatch, ["Collection"])
    assert [i["id"] for i in out["items"]] == []
    assert out["total"] == 0


def test_cashline_login_sees_only_cashline_context(monkeypatch, stub_app_c):
    out = _call(monkeypatch, ["Cashline"])
    assert [i["id"] for i in out["items"]] == ["b"]


def test_empty_scope_short_circuits_without_calling_app_c(monkeypatch, stub_app_c):
    """Cakupan kosong = nol baris; App C tidak perlu ditembak sama sekali."""
    out = _call(monkeypatch, [])
    assert out["items"] == []
    assert stub_app_c == []


def test_search_uses_the_tighter_page_cap(monkeypatch, stub_app_c):
    _call(monkeypatch, None, tiket_id="050246")
    assert stub_app_c[0]["max_pages"] == td.MAX_PAGES_SEARCH

    stub_app_c.clear()
    _call(monkeypatch, None)
    assert stub_app_c[0]["max_pages"] == td.MAX_PAGES_DEFAULT


def test_app_c_failure_is_502_not_an_empty_table(monkeypatch, stub_app_c):
    """Layar kosong karena galat jaringan tidak boleh tampak sama dengan layar
    kosong karena memang tidak ada tiket."""
    from fastapi import HTTPException

    def _boom(**kwargs):
        raise tms.TicketsDailyError("connection refused")

    monkeypatch.setattr(td.tms, "fetch_all", _boom)
    with pytest.raises(HTTPException) as exc:
        _call(monkeypatch, None)
    assert exc.value.status_code == 502
