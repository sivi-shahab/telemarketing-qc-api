"""Unit tests untuk compliance.campaign_kind.

Penanda campaign collection dibaca dari satu variabel lingkungan
(COLLECTION_CAMPAIGNS) oleh API maupun worker, jadi aturan normalisasinya harus
persis sama di kedua sisi — itulah yang dijaga test di berkas ini.
"""
from compliance.campaign_kind import is_collection, parse_collection_campaigns


# --------------------------------------------------------------------------
# parse_collection_campaigns
# --------------------------------------------------------------------------

def test_parse_trims_and_casefolds():
    assert parse_collection_campaigns(" Collection_V2 , KOLEKSI ") == frozenset(
        {"collection_v2", "koleksi"}
    )


def test_parse_drops_empty_entries():
    assert parse_collection_campaigns("a,,  ,b,") == frozenset({"a", "b"})


def test_parse_empty_string_returns_empty_set():
    assert parse_collection_campaigns("") == frozenset()
    assert parse_collection_campaigns("   ") == frozenset()


def test_parse_non_string_returns_empty_set():
    assert parse_collection_campaigns(None) == frozenset()
    assert parse_collection_campaigns(["a"]) == frozenset()


# --------------------------------------------------------------------------
# is_collection
# --------------------------------------------------------------------------

def test_is_collection_matches_case_and_space_insensitively():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection("collection_v2", allowed) is True
    assert is_collection("  Collection_V2  ", allowed) is True


def test_is_collection_false_for_other_campaign():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection("cashline_mus_v30", allowed) is False


def test_is_collection_false_when_allowed_empty():
    """Default .env kosong berarti fitur mati: tidak ada yang dianggap collection."""
    assert is_collection("collection_v2", frozenset()) is False


def test_is_collection_false_for_missing_name():
    allowed = parse_collection_campaigns("collection_v2")
    assert is_collection(None, allowed) is False
    assert is_collection("", allowed) is False
