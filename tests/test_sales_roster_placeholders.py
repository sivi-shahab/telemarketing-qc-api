"""Baris placeholder di roster sales tidak boleh jadi "orang".

Regresi yang dijaga: dropdown **Semua AM** dan **Semua TL** di halaman Results
memunculkan satu opsi bernama ``-``. Sumbernya spreadsheet roster itu sendiri —
kolom hierarkinya tidak dikosongkan melainkan diisi placeholder:

* 12 baris padding di akhir sheet: ``USER ID`` = ``0``, ``NIP BARU`` =
  ``00000000``, ``NAMA TL`` / ``NAMA AM`` = ``-``, ``NIP TL`` / ``NIP TLM`` = ``0``
* agen berstatus MUTASI (mis. EKO YULIONO, DINI HANDINI): USER ID & namanya asli,
  tapi TL/AM-nya diisi ``-`` / ``0`` karena sudah tidak punya atasan

``hierarchy_filter_options`` menganggap setiap ``nip_am``/``nip_tl`` tak kosong
sebagai orang sungguhan, jadi NIP ``0`` + nama ``-`` menjadi satu opsi ``-``.
"""
import io

import pytest
from openpyxl import Workbook

import sales_lookup
from sales_lookup import active_sales_map, hierarchy_filter_options

HEADER = [
    "USER ID", "NIP LAMA", "NIP BARU", "NAME", "NAME ONLINE", "DEDICATED",
    "LEVEL", "NIP TL", "NAMA TL", "NIP TLM", "NAMA AM", "STATUS PKWT",
    "START PKWT", "END PKWT", "JOIN POSISI (DD/MM/YYYY)", "STATUS",
    "TGL RESIGN", "KETERANGAN",
]

# Baris asli dari "Update Sales Telemarketing 10 Agustus 2026.xlsx".
ROW_NORMAL = ["budi801", "1234", "23010111", "BUDI SANTOSO", "BUDI", "CASHLINE",
              "REGULER", "24071073", "MOCHAMAD IRFAN", "16043457", "JEFRI ANSYAH",
              "PKWT", "", "", "", "AKTIF", "", ""]
ROW_MUTASI = ["eko801", "1235", "10030065", "EKO YULIONO", "EKO", "-",
              "REGULER", "0", "-", "0", "-", "", "", "", "", "MUTASI", "", ""]
ROW_PADDING = ["0", "", "00000000", "", "", "-",
               "0", "0", "-", "0", "-", "", "", "", "", "0", "", ""]


class _FakeRow:
    object_path = "test/roster.xlsx"


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


@pytest.fixture
def roster(monkeypatch):
    """Bangun xlsx roster in-memory dan sajikan lewat active_sales_map()."""
    def _build(rows):
        wb = Workbook()
        ws = wb.active
        ws.append(HEADER)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)

        class _FakeMinio:
            def get_object(self, bucket, path):
                return _FakeResponse(buf.getvalue())

        monkeypatch.setattr(sales_lookup.crud, "get_active_sales_database",
                            lambda db: _FakeRow())
        monkeypatch.setattr(sales_lookup, "get_minio", lambda: _FakeMinio())
        # Sesudah pemisahan repo, sales_lookup milik core dan mengambil settings
        # dari core_config.get_core_settings() -- bukan lagi api.dependencies.get_settings.
        monkeypatch.setattr(sales_lookup, "get_core_settings",
                            lambda: type("S", (), {"minio_bucket_sales_database": "b"})())
        sales_lookup._cache["key"] = None
        sales_lookup._cache["map"] = {}
        return active_sales_map(db=None)

    yield _build
    sales_lookup._cache["key"] = None
    sales_lookup._cache["map"] = {}


def test_padding_row_is_not_a_roster_entry(roster):
    """Baris padding ber-USER ID "0" bukan agent — jangan masuk peta roster."""
    mapping = roster([ROW_NORMAL, ROW_PADDING])
    assert set(mapping) == {"budi801"}


def test_mutasi_row_keeps_identity_but_drops_placeholder_hierarchy(roster):
    """Agen MUTASI tetap ada, tapi TL/AM placeholder-nya dibaca sebagai kosong."""
    entry = roster([ROW_NORMAL, ROW_MUTASI])["eko801"]
    assert entry["name"] == "EKO YULIONO"
    assert entry["nip_baru"] == "10030065"
    assert entry["team_leader"] is None
    assert entry["area_manager"] is None
    assert entry["nip_tl"] is None
    assert entry["nip_am"] is None
    assert entry["dedicated"] is None


def test_normal_row_survives_untouched(roster):
    entry = roster([ROW_NORMAL])["budi801"]
    assert entry["team_leader"] == "MOCHAMAD IRFAN"
    assert entry["nip_tl"] == "24071073"
    assert entry["area_manager"] == "JEFRI ANSYAH"
    assert entry["nip_am"] == "16043457"
    assert entry["dedicated"] == "CASHLINE"


def test_am_and_tl_dropdowns_list_names_only(roster, monkeypatch):
    """Dropdown Semua AM / Semua TL hanya berisi nama orang, bukan "-"."""
    mapping = roster([ROW_NORMAL, ROW_MUTASI, ROW_PADDING])
    monkeypatch.setattr(sales_lookup, "active_sales_map", lambda db: mapping)

    opts = hierarchy_filter_options(db=None, data_scope="all", username="spq",
                                    campaigns=None)

    assert [a["name"] for a in opts["area_managers"]] == ["JEFRI ANSYAH"]
    assert [t["name"] for t in opts["team_leaders"]] == ["MOCHAMAD IRFAN"]
    # Agent MUTASI tetap bisa dipilih di dropdown TLO; baris padding tidak.
    assert [g["name"] for g in opts["agents"]] == ["BUDI SANTOSO", "EKO YULIONO"]
