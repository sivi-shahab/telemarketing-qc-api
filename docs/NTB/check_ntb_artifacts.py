#!/usr/bin/env python3
"""Cek konsistensi artefak campaign NTB (Fase 1): scorecard, KB, prompt.

Pakai:  python3 docs/NTB/check_ntb_artifacts.py [--xlsx]
        --xlsx  juga membandingkan total tiap varian dengan sheet "Total Score" pada
                Score Card NTB_Supplement_MUS 05102026.xlsx (butuh openpyxl).
Keluar dengan kode != 0 bila ada pemeriksaan yang gagal.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, "ntb_scorecard_v1.txt")
KB = os.path.join(HERE, "ntb_kb_v1.txt")
PROMPT = os.path.join(HERE, "prompt_ntb_v1.txt")

VARIANTS = {  # nama: (set add-on aktif, total, passing 90%)
    "BASIC": (set(), 100, 90),
    "BASIC+SUPL": ({"SUPL"}, 125, 112.5),
    "BASIC+MUS": ({"MUS"}, 150, 135),
    "BASIC+MUS+SUPL": ({"SUPL", "MUS"}, 175, 157.5),
}
CATEGORY_SUBTOTAL = {
    "Greeting": 10, "Probing": 5, "Pengisian Data Basic": 64, "Pengisian Data Supplement": 11,
    "Penjelasan Mega Ultima Shield": 24.5, "Final Konfirmasi Basic": 12, "Final Konfirmasi Supplement": 9,
    "Final Konfirmasi Mega Ultima Shield": 20.5, "Legal Statement Basic": 5, "Legal Statement Supplement": 5,
    "Legal Statement Mega Ultima Shield": 5, "Closing": 4,
}
CRITICAL = ["SC_NTB_4", "SC_NTB_46", "SC_NTB_50", "SC_NTB_71", "SC_NTB_72", "SC_NTB_73"]
FORBIDDEN = re.compile(r"SC_CL_|KB_CL_|Cashline|cashline|Ascend|ascend|card_holder|tms_|verifikasi dinamis", re.I)

fails = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


sc = load(SC)
kb_all = load(KB)
kb_phases = kb_all[0]["conversation_phases"]
kb = kb_all[1:]

# 1. struktur dasar
check(len({i["item_code"] for i in sc}) == len(sc), f"item_code scorecard unik ({len(sc)} item)")
check({i["kb_reference"] for i in sc} == {k["kb_code"] for k in kb}, "kb_reference scorecard == kb_code KB (1:1)")
check(all(i["item_code"].replace("SC_", "KB_") == i["kb_reference"] for i in sc), "pasangan SC_NTB_n <-> KB_NTB_n sama nomor")
check(all(i["tolerable"] in ("YES", "NO") for i in sc), "tolerable hanya YES/NO")
check(all(i.get("applies_to") in (None, "SUPL", "MUS") for i in sc), "applies_to hanya SUPL/MUS/kosong")
check({i["category"] for i in sc} == set(kb_phases), "kategori scorecard == kunci conversation_phases")
check({k["category"] for k in kb} == set(kb_phases), "kategori KB == kunci conversation_phases")
kb_by = {k["kb_code"]: k for k in kb}
check(all(kb_by[i["kb_reference"]]["category"] == i["category"] and kb_by[i["kb_reference"]]["requirement"] == i["requirement"] for i in sc),
      "category & requirement KB sama dengan scorecard")

# 2. subtotal kategori
sub = {}
for i in sc:
    sub[i["category"]] = sub.get(i["category"], 0) + i["weight"]
for cat, want in CATEGORY_SUBTOTAL.items():
    check(abs(sub.get(cat, -1) - want) < 1e-9, f"subtotal '{cat}' = {sub.get(cat)} (xlsx {want})")

# 3. total per varian
totals = {}
for name, (active, want, passing) in VARIANTS.items():
    tot = sum(i["weight"] for i in sc if i.get("applies_to") in (None, *active))
    totals[name] = tot
    check(abs(tot - want) < 1e-9, f"total varian {name} = {tot} (target {want}); lulus 90% = {tot * 0.9:g} (target {passing:g})")
    check(abs(tot * 0.9 - passing) < 1e-9, f"passing grade {name}")

# 4. item kritis
codes = {i["item_code"] for i in sc}
check(all(c in codes for c in CRITICAL), f"item kritis ada di scorecard: {', '.join(CRITICAL)}")

# 5. bebas rujukan Cashline/Ascend (KB, prompt)
for label, path in (("KB", KB), ("prompt", PROMPT)):
    if not os.path.exists(path):
        check(False, f"{label} belum ada: {os.path.basename(path)}")
        continue
    txt = open(path, encoding="utf-8").read()
    hits = [(n, l.strip()[:110]) for n, l in enumerate(txt.splitlines(), 1) if FORBIDDEN.search(l)]
    check(not hits, f"{label}: bebas SC_CL_/KB_CL_/Cashline/Ascend/card_holder/tms_/verifikasi dinamis ({len(hits)} temuan)")
    for h in hits[:15]:
        print("       ", h)

# 6. kode yang dirujuk prompt harus ada
if os.path.exists(PROMPT):
    ptxt = open(PROMPT, encoding="utf-8").read()
    refs = set(re.findall(r"\b(?:SC|KB)_NTB_\d+\b", ptxt))
    unknown = sorted(r for r in refs if r.replace("KB_", "SC_") not in codes)
    check(not unknown, f"prompt hanya merujuk kode NTB yang ada (menemukan {len(refs)} rujukan unik; tak dikenal: {unknown})")
    for c in CRITICAL:
        check(c in ptxt, f"prompt menyebut item kritis {c}")

# 7. (opsional) bandingkan dengan xlsx
if "--xlsx" in sys.argv:
    try:
        import openpyxl
        path = glob.glob(os.path.join(HERE, "Score Card NTB_Supplement_MUS 05102026.xlsx"))[0]
        wb = openpyxl.load_workbook(path, data_only=True)
        sheet_of = {"BASIC": "NTB Only", "BASIC+SUPL": "NTB + Suplement", "BASIC+MUS": "NTB + MUS", "BASIC+MUS+SUPL": "NTB + MUS + Suplement"}
        for name, sname in sheet_of.items():
            ws = [w for w in wb.worksheets if w.title.strip() == sname][0]
            x_total = next(r[5] for r in ws.iter_rows(values_only=True) if r[0] == "Total Score")
            check(abs(x_total - totals[name]) < 1e-9, f"xlsx '{sname}' Total Score {x_total} == scorecard {totals[name]}")
            # baris item = kolom C (kategori kegagalan) terisi dan kolom F (bobot) numerik;
            # baris subtotal/total tidak punya kolom C, jadi tidak ikut terjumlah
            items_sum = sum(r[5] for r in ws.iter_rows(values_only=True) if r[2] and isinstance(r[5], (int, float)))
            check(abs(items_sum - x_total) < 1e-9, f"xlsx '{sname}': jumlah bobot baris item {items_sum} == Total Score {x_total}")
    except Exception as e:  # noqa: BLE001
        check(False, f"pembandingan xlsx gagal: {e}")

print()
if fails:
    print(f"{len(fails)} pemeriksaan GAGAL")
    sys.exit(1)
print("Semua pemeriksaan lulus")
