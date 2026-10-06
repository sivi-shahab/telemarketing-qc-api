"""Roster format 30 September 2026: ``USER ID LAMA`` + ``USER ID BARU``.

Regresi yang dijaga (6 Oktober 2026): roster "Update Sales Telemarketing
30 September 2026 - Final.xlsx" mengganti kolom ``USER ID`` dengan dua kolom dan
``JOIN POSISI`` dengan ``JOIN ONLINE``. Parser hanya mengenal ``user id``, jadi
roster terbaca 0 agent dan SETIAP tiket menjadi "Agent Tidak Terpetakan".

``agent_id`` di TMS masih memakai ID LAMA (sama dengan kolom ``USER ID`` roster
sebelumnya), jadi LAMA menjadi kunci; BARU hanya alias pencarian supaya agent
tidak muncul dua kali saat roster di-iterasi.
"""
import io
from datetime import date, datetime

from openpyxl import Workbook

import sales_lookup
from compliance.sales_roster import parse_roster

# Tata letak asli file 30 September 2026 (16 kolom pertama).
HEADER = [
    "USER ID LAMA", "USER ID BARU", "NIP LAMA", "NIP BARU", "NAME", "NAME ONLINE",
    "DEDICATED", "LEVEL", "NIP TL", "NAMA TL", "NIP TLM", "NAMA AM",
    "STATUS PKWT", "START PKWT", "END PKWT", "JOIN ONLINE (DD/MM/YYYY)",
]
ROW_SRI = ["sri801", "TM0801", "1234", "23010111", "SRI WAHYUNI", "SRI", "CASHLINE",
           "REGULER", "24071073", "MOCHAMAD IRFAN", "16043457", "JEFRI ANSYAH",
           "PKWT", "", "", datetime(2025, 3, 1)]
# Agent baru: belum punya ID lama.
ROW_BARU_SAJA = ["-", "TM0999", "", "23019999", "NINA", "NINA", "CASHLINE",
                 "REGULER", "24071073", "MOCHAMAD IRFAN", "16043457", "JEFRI ANSYAH",
                 "PKWT", "", "", "01/09/2026"]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_lama_is_key_and_hierarchy_is_read():
    m = parse_roster(_xlsx([ROW_SRI]))
    assert list(m) == ["sri801"]
    e = m["sri801"]
    assert e["name"] == "SRI WAHYUNI"
    assert e["name_online"] == "SRI"
    assert e["nip_baru"] == "23010111"
    assert e["team_leader"] == "MOCHAMAD IRFAN"
    assert e["nip_am"] == "16043457"
    assert e["dedicated"] == "CASHLINE"
    assert e["join_date"] == date(2025, 3, 1)


def test_baru_is_lookup_alias_not_a_second_entry():
    m = parse_roster(_xlsx([ROW_SRI]))
    assert "tm0801" in m
    assert m.get("tm0801") is m["sri801"]
    assert m["tm0801"]["name"] == "SRI WAHYUNI"
    assert len(m) == 1
    assert [e["name"] for e in m.values()] == ["SRI WAHYUNI"]


def test_agent_without_lama_uses_baru_as_key():
    m = parse_roster(_xlsx([ROW_SRI, ROW_BARU_SAJA]))
    assert set(m) == {"sri801", "tm0999"}
    assert m["tm0999"]["join_date"] == date(2026, 9, 1)


def test_tl_scoping_includes_both_ids(monkeypatch):
    m = parse_roster(_xlsx([ROW_SRI]))
    monkeypatch.setattr(sales_lookup, "active_sales_map", lambda db: m)
    assert sales_lookup.agent_ids_for_tl(None, "24071073") == {"sri801", "tm0801"}


def test_old_single_user_id_layout_unchanged():
    wb = Workbook()
    ws = wb.active
    ws.append(["USER ID", "NIP LAMA", "NIP BARU", "NAME", "NAME ONLINE", "DEDICATED",
               "LEVEL", "NIP TL", "NAMA TL", "NIP TLM", "NAMA AM", "STATUS PKWT",
               "START PKWT", "END PKWT", "JOIN POSISI (DD/MM/YYYY)"])
    ws.append(["budi801", "1", "23010111", "BUDI", "BUDI", "CASHLINE", "REGULER",
               "24071073", "MOCHAMAD IRFAN", "16043457", "JEFRI ANSYAH", "", "", "",
               "31/10/2017"])
    buf = io.BytesIO()
    wb.save(buf)
    m = parse_roster(buf.getvalue())
    assert list(m) == ["budi801"]
    assert m["budi801"]["join_date"] == date(2017, 10, 31)
