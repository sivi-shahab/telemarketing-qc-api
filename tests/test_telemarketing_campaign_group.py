"""Campaign grup ``Telemarketing``: login ber-tag Telemarketing melihat SELURUH
tiket telemarketing, seperti Admin.

``Telemarketing`` bukan config campaign di tabel ``campaigns`` — ia payung atas
semua campaign NON-Collection (Cashline, NTB, config lain yang kelak di-upload) dan
seluruh produk di tiket App C (``Activation CC New``, ``Megapay``, ``Personal Loan``,
``CashLine NTB``, ``LOC Change Request``, ...). ``Cashline`` tetap nama config
penilaian, bukan tag cakupan orang.

Latar: sejak load_date 2026-09-17 App C mengisi ``context`` dengan KODE campaign
(``CLENTB``, ``011``), sehingga peta lama ``Cashline:cashline`` membuang setiap
baris — menu Transkrip dan Assign Ticket kosong bagi 12 login QC ber-tag Cashline,
dan assign ditolak 403 karena tiket App C belum ada di tabel ``results``.
"""
import pytest
from fastapi import HTTPException

from api import campaign_context as cc
from api import campaign_groups as cg
from api import permissions as P
from api import rbac
from api.routers import qc_assignment as qa
from api.routers import tickets_daily as td

COLLECTION = frozenset({"collection"})


# --- ekspansi grup ---------------------------------------------------------

def test_expand_adds_every_non_collection_campaign():
    out = cg.expand(["Telemarketing"], ["Cashline", "Collection", "NTB"], COLLECTION)
    assert out == ["Telemarketing", "Cashline", "NTB"]


def test_expand_is_noop_without_the_group():
    assert cg.expand(["Collection"], ["Cashline", "Collection"], COLLECTION) == ["Collection"]


def test_expand_matches_group_case_insensitively():
    assert "Cashline" in cg.expand([" telemarketing "], ["Cashline"], COLLECTION)


def test_allows_non_collection_names_not_in_the_config_table():
    """Tag roster (mis. ``NTB``) tidak harus punya config campaign."""
    allowed = cg.allowed_set(["Telemarketing"])
    assert cg.allows(allowed, "NTB", COLLECTION)
    assert not cg.allows(allowed, "Collection", COLLECTION)


def test_with_group_option_puts_telemarketing_first_once():
    assert cg.with_group_option(["Collection", "Cashline", "Telemarketing"]) == [
        "Telemarketing", "Cashline", "Collection",
    ]


# --- effective_campaigns_for -----------------------------------------------

@pytest.fixture
def qc_side(monkeypatch):
    monkeypatch.setenv("COLLECTION_CAMPAIGNS", "Collection")
    monkeypatch.setattr(rbac, "campaigns_for", lambda db, u: [])
    monkeypatch.setattr(rbac, "data_scope_for", lambda db, u: P.SCOPE_ALL)
    monkeypatch.setattr(rbac, "_campaign_names", lambda db: ["Cashline", "Collection"])

    def _tag(*names):
        monkeypatch.setattr(rbac, "user_campaigns_for", lambda db, u: list(names))
        return rbac.effective_campaigns_for(object(), object())
    return _tag


def test_telemarketing_tag_expands_to_cashline(qc_side):
    assert qc_side("Telemarketing") == ["Telemarketing", "Cashline"]


def test_collection_tag_is_unchanged(qc_side):
    assert qc_side("Collection") == ["Collection"]


def test_role_declared_telemarketing_is_narrowed_by_person_tag(monkeypatch, qc_side):
    monkeypatch.setattr(rbac, "campaigns_for", lambda db, u: ["Telemarketing"])
    assert qc_side("Cashline") == ["Cashline"]
    assert qc_side("Collection") == []


# --- peta App C bawaan: Telemarketing = seluruh baris ----------------------

def test_default_map_opens_every_app_c_row_for_telemarketing(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    assert cc.contexts_for(["Telemarketing", "Cashline"], cc.context_map_from_env()) is None


def test_default_map_keeps_collection_closed(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    assert cc.contexts_for(["Collection"], cc.context_map_from_env()) == frozenset({"collection"})


WILD = {"telemarketing": frozenset({"*"}), "collection": frozenset({"collection"})}


def test_wildcard_parses():
    assert cc.parse_context_map("Telemarketing:*,Collection:collection") == WILD


def test_wildcard_wins_over_a_narrower_campaign():
    assert cc.contexts_for(["Collection", "Telemarketing"], WILD) is None


def test_unmapped_campaign_still_fails_closed():
    assert cc.contexts_for(["NTB"], WILD) == frozenset()


# --- endpoint /tickets_daily ------------------------------------------------

# Bentuk baris App C sejak load_date 2026-09-17: campaign = nama, context = kode.
NEW_FORMAT = [
    {"id": "a", "campaign": "Activation CC New", "context": "ACT02"},
    {"id": "b", "campaign": "CashLine NTB", "context": "CLENTB"},
    {"id": "c", "campaign": "Personal Loan", "context": "011"},
]


@pytest.fixture
def default_map(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(td.tms, "fetch_all", lambda **kw: {
        "mode": "yesterday", "load_date": "2026-09-22",
        "items": list(NEW_FORMAT), "total": 3, "truncated": False,
    })


def _list(monkeypatch, campaigns):
    monkeypatch.setattr(td, "effective_campaigns_for", lambda db, u: campaigns)
    return td.list_tickets_daily(tiket_id=None, load_date=None, db=object(), current_user=object())


def test_telemarketing_login_sees_every_row_like_admin(monkeypatch, default_map):
    out = _list(monkeypatch, ["Telemarketing", "Cashline"])
    assert out["items"] == _list(monkeypatch, None)["items"]
    assert out["total"] == 3


def test_collection_login_still_sees_no_telemarketing_rows(monkeypatch, default_map):
    assert _list(monkeypatch, ["Collection"])["items"] == []


# --- Assign Ticket: gate & daftar assignment -------------------------------

@pytest.fixture
def telemarketing_supervisor(monkeypatch):
    """SPQ Head / TL QC ber-tag Telemarketing: cakupan ``all``, dan
    ``scoped_customer_ids`` hanya berisi tiket ``results`` (bukan tiket App C)."""
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: ["Telemarketing", "Cashline"])
    monkeypatch.setattr(qa, "data_scope_for", lambda db, u: P.SCOPE_ALL)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: ["resultonly"])


def test_telemarketing_supervisor_can_assign_an_app_c_ticket(telemarketing_supervisor):
    qa._ensure_ticket_in_scope(object(), object(), "220229Qxz5")  # tidak raise


def test_telemarketing_supervisor_lists_assignments_of_app_c_tickets(monkeypatch, telemarketing_supervisor):
    class _A:
        ticket_id, qc_username, assigned_by_username, assigned_at = "220229Qxz5", "qc1", "tl", None

    monkeypatch.setattr(qa.crud, "list_qc_assignments", lambda db: [_A()])
    out = qa.list_assignments(ticket_ids="220229Qxz5", db=object(), current_user=object())
    assert [a["ticket_id"] for a in out] == ["220229Qxz5"]


def test_collection_supervisor_is_still_scoped(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: ["Collection"])
    monkeypatch.setattr(qa, "data_scope_for", lambda db, u: P.SCOPE_ALL)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: ["resultonly"])
    with pytest.raises(HTTPException) as exc:
        qa._ensure_ticket_in_scope(object(), object(), "220229Qxz5")
    assert exc.value.status_code == 403


def test_qc_assigned_scope_is_not_widened(monkeypatch):
    """Pelebaran hanya untuk cakupan ``all``; cakupan ``qc_assigned`` tetap
    ditentukan tiket yang di-assign kepadanya."""
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: ["Telemarketing", "Cashline"])
    monkeypatch.setattr(qa, "data_scope_for", lambda db, u: P.SCOPE_QC_ASSIGNED)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: ["mine"])
    with pytest.raises(HTTPException):
        qa._ensure_ticket_in_scope(object(), object(), "220229Qxz5")


# --- Assign Role: Cashline adalah SUBSET Telemarketing ---------------------

def test_members_are_non_collection_configs_plus_tms_products():
    assert cg.members(
        ["Collection", "Cashline", "Telemarketing"], ["Megapay", "Activation CC New", "megapay"], COLLECTION
    ) == ["Activation CC New", "Cashline", "Megapay"]


def test_tree_for_the_form():
    assert cg.tree(["Cashline", "Collection"], ["Megapay"], COLLECTION) == {
        "Telemarketing": ["Cashline", "Megapay"],
    }


def test_test_campaigns_are_not_products():
    assert cg.clean_products(
        ["Megapay", "campaign test", "LOC Transactor Never Taker test", "Aktivasi CC tes", "", None]
    ) == ["Megapay"]


def test_collapse_shows_only_the_group_for_display():
    """SPQ Head ber-tag Telemarketing tampil sebagai Telemarketing saja."""
    assert cg.collapse(["Telemarketing", "Cashline"], COLLECTION) == ["Telemarketing"]
    assert cg.collapse(["Telemarketing", "Cashline", "Collection"], COLLECTION) == ["Telemarketing", "Collection"]
    assert cg.collapse(["Cashline"], COLLECTION) == ["Cashline"]


# --- produk tunggal: disaring lewat NAMA campaign di baris App C -----------

def test_product_tag_sees_only_its_app_c_rows(monkeypatch, default_map):
    assert [i["id"] for i in _list(monkeypatch, ["Personal Loan"])["items"]] == ["c"]


def test_product_names_match_case_insensitively():
    rows = [{"id": "x", "campaign": "MEGAPAY", "context": "MP01"}]
    assert cc.filter_items(rows, frozenset(), names=frozenset({"megapay"})) == rows


def test_normalize_drops_members_already_covered_by_the_group():
    """Centang Telemarketing + Cashline disimpan sebagai Telemarketing saja."""
    assert cg.normalize(["Cashline", "Telemarketing", "Collection"], COLLECTION) == [
        "Telemarketing", "Collection",
    ]


def test_normalize_keeps_a_lone_member():
    """Cashline tanpa Telemarketing = sengaja dipersempit ke satu produk."""
    assert cg.normalize(["Cashline"], COLLECTION) == ["Cashline"]
