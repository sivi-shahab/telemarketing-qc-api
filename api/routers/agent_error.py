"""Agent Error Summary — for a single result, the agent (dari baris cashline)
and campaign interest together with that result's error-code table.

``agent_id`` & ``submit_time`` dibaca SNAPSHOT-FIRST: dari
``result_json["reference_data"]["cashline"]`` yang disimpan worker saat evaluasi —
sumber yang SAMA dengan ``crud.cashline_agent_index()`` (hierarki Statistics,
scope Team Leader) dan ``crud.tms_submit_time_map()`` (timer SLA H+2 Pending
Check). Baris cashline DWH live (``crud.get_tms_cashline_by_result_id`` ->
services/data_dwh) cuma fallback untuk result yang dievaluasi sebelum snapshot itu
ada, jadi endpoint ini tidak lagi ikut kosong ketika App A tidak menjawab.

Surfaced inside the Results row dropdown untuk SEMUA role, dengan isi yang identik:
  Agent ID    <- cashline ``agent_id`` (snapshot, fallback DWH live by
                 result_id == customer ID)
  Agent Name  <- NAME from the active sales database, matched by USER ID == agent_id;
                 falls back to the alphabetic chars of agent_id when unmatched.
  New Joiner  <- "NEW JOINER" when the agent joined < 18 days before submit_time,
                 else "-" (Sales Agent column).
  Campaign    <- evaluation ``campaign_interest`` (bullet list)
  Tanggal     <- cashline ``submit_time`` (snapshot, fallback DWH live)
  Ticket ID / Detail Error / Reason  <- per-row from build_error_code_table().

Selain itu, response ini membawa ``badwords``: temuan ucapan agent yang bersentimen
negatif kepada nasabah (Ticket ID / Evidence / Reason), sumber tabel "Badword Summary"
tepat di bawah tabel Agent Error Summary. Lihat ``compliance/badwords.py``.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_agent_error_summary_user
from api.qc_scope import ensure_can_view_result
from sales_lookup import active_sales_map, new_joiner_info
from compliance.badwords import badword_rows
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    apply_added_score_appeals,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    normalize_static_verification,
    build_error_code_table,
    inject_added_rows,
    relabel_error_table,
)
from db import crud

router = APIRouter(dependencies=[Depends(get_agent_error_summary_user)])


def _customer_id(source_files) -> Optional[str]:
    """Customer/session ID = prefix before the first ``_`` of the first source file."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]
def _agent_name(agent_id: Optional[str]) -> Optional[str]:
    """Agent name = alphabetic characters of the agent id (``rizqi801`` -> ``rizqi``)."""
    if not agent_id:
        return None
    letters = "".join(c for c in agent_id if c.isalpha())
    return letters or None
def _campaign_interest(evaluation: dict) -> list:
    """Campaign interest list; fall back to the per-product INTERESTED flags."""
    ci = evaluation.get("campaign_interest")
    if isinstance(ci, list) and ci:
        return [str(c) for c in ci]
    out = []
    if (evaluation.get("cashline_interest") or {}).get("status") == "INTERESTED":
        out.append("Mega Cashline")
    if (evaluation.get("mus_interest") or {}).get("status") == "INTERESTED":
        out.append("Mega Ultima Shield")
    return out
def _snapshot_cashline(result_data) -> dict:
    """Snapshot baris cashline yang disisipkan worker ke ``result_json`` saat
    evaluasi (``reference_data.cashline`` — lihat worker/tasks/process_transcript.py).
    ``{}`` bila belum ada (hasil evaluasi sebelum snapshot itu disimpan)."""
    if result_data is None or not isinstance(result_data.result_json, dict):
        return {}
    ref = result_data.result_json.get("reference_data")
    if not isinstance(ref, dict):
        return {}
    cashline = ref.get("cashline")
    return cashline if isinstance(cashline, dict) else {}
@router.get("/agent_error_summary/{result_id}")
def agent_error_summary(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_agent_error_summary_user),
):
    """Agent + campaign + error-code rows for one result (used in the Results dropdown)."""
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result tidak ditemukan")
    # Isinya adalah tabel Error Code + badword tiket itu — sama sensitifnya dengan
    # halaman detailnya, jadi ikut aturan cakupan tiket dan bukan hanya "sudah login".
    ensure_can_view_result(db, current_user, result)

    # [FIX] agent_id & submit_time (Tanggal) dibaca dari SNAPSHOT
    # ``reference_data.cashline`` di result_json dulu, baru jatuh ke baris DWH
    # live. Sebelumnya HANYA dari DWH live, jadi Agent ID/Name/Tanggal kosong
    # ("—") tiap kali App A tidak menjawab atau field-nya tidak ikut di endpoint
    # cache — padahal hierarki Statistics, scope Team Leader dan timer SLA H+2
    # (crud.cashline_agent_index / tms_submit_time_map) tetap punya nilainya dari
    # snapshot. Sekarang semuanya membaca sumber yang sama.
    data = crud.get_result_data(db, result_id)
    snapshot = _snapshot_cashline(data)
    agent_id = (snapshot.get("agent_id") or "").strip() or None
    submit_time = (snapshot.get("submit_time") or "").strip() or None

    # DWH live cuma disentuh kalau snapshot belum lengkap — dua field itu satu-
    # satunya yang dipakai endpoint ini dari baris cashline, jadi snapshot yang
    # utuh berarti nol panggilan HTTP tiap dropdown dibuka.
    if not (agent_id and submit_time):
        cid = _customer_id(result.source_files)
        ref = (crud.get_tms_cashline_by_result_id(db, cid) if cid else None) or {}
        agent_id = agent_id or (ref.get("agent_id") or "").strip() or None
        submit_time = submit_time or (ref.get("submit_time") or "").strip() or None

    # [FIX] agent_name & nj sebelumnya dipakai di response tanpa pernah di-assign
    # -> NameError setiap kali endpoint ini dipanggil. Keduanya direkonstruksi
    # sesuai docstring modul: NAME dari active sales database (dicocokkan
    # USER ID == agent_id), fallback ke karakter alfabet agent_id kalau tidak
    # ketemu; new_joiner_info() untuk tenure & selisih hari.
    agent_name = None
    if agent_id:
        entry = active_sales_map(db).get(agent_id.casefold())
        if entry:
            agent_name = (entry.get("name") or "").strip() or None
        if not agent_name:
            agent_name = _agent_name(agent_id)
    # Pasangan agent_id/submit_time yang sama dipakai untuk tenure & selisih hari,
    # supaya "Agent ID", "Tanggal", "durasi_bergabung" dan "selisih_hari" tidak
    # pernah bercerita beda sumber (new_joiner_info hanya membaca dua key ini).
    nj = new_joiner_info({"agent_id": agent_id, "submit_time": submit_time}, db)

    evaluation = {}
    if data is not None and isinstance(data.result_json, dict):
        ev = data.result_json.get("evaluation")
        if isinstance(ev, dict):
            evaluation = ev

    # Apply approved bandings so the summary matches the Error Code table: a
    # 'remove' drops the row; a 'change' relabels it and swaps in the QC-approved
    # reason/evidence; an 'add' contributes a NEW row (every source, including
    # 'others'). Mirrors api/routers/transcript.py::_with_error_code_table.
    table = []
    if evaluation:
        appeals = crud.error_code_appeals_for_result(db, result_id)
        approved = approved_appeals_only(appeals)
        # 'add' bandings are handled separately — they must NOT go through the
        # remove/change appliers nor relabel_error_table (which would treat them
        # as removes and drop the very rows they add).
        flip = [a for a in appeals_that_flip(approved) if _appeal_kind(a) != "add"]
        # Zona abu-abu ditegakkan di kode, sebelum banding & skor dihitung.
        evaluation = normalize_static_verification(evaluation)
        evaluation = apply_approved_appeals(evaluation, flip)
        evaluation = apply_approved_card_holder_appeals(evaluation, flip)
        evaluation = apply_approved_cashline_appeals(evaluation, flip)
        evaluation = apply_approved_critical_compliance_appeals(evaluation, flip)
        evaluation = apply_added_score_appeals(evaluation, added_appeals_only(appeals))
        # Only APPROVED adds are listed here: this summary reports an agent's real
        # errors, so a banding still awaiting Team Leader QC / SPQ Head must not
        # surface its QC reason yet (the detail Error Code table shows pending ones
        # so the reviewers can act on them).
        table = inject_added_rows(build_error_code_table(evaluation), added_appeals_only(appeals))
        table = relabel_error_table(table, [a for a in approved if _appeal_kind(a) != "add"])

    # Collapse rows that repeat the SAME FINDING into a single entry (first wins,
    # order preserved) — the summary lists an agent's distinct errors, so an
    # identical value surfacing twice is noise.
    #
    # De-dup key = (details_error, reason, evidence). Sampai 28 Agustus 2026 kuncinya
    # hanya ``details_error``, sehingga satu kode yang dilanggar di beberapa tempat
    # (mis. B17 untuk Tanggal Lahir DAN Nama Ibu Kandung) runtuh jadi satu baris.
    # Sejak kolom Evidence & Reason ditambahkan ke Agent Error Summary hal itu
    # berarti membuang evidence temuan kedua dan seterusnya, jadi kuncinya diperluas:
    # satu baris = satu temuan, dan kode yang sama boleh muncul berkali-kali selama
    # reason/evidence-nya berbeda. Baris yang ketiga nilainya kosong dibiarkan lewat.
    errors = []
    seen_findings: set = set()
    for row in table:
        details = row.get("details_error") or ""
        reason = row.get("reason") or ""
        evidence = row.get("evidence") or ""
        key = (details, reason, evidence)
        if any(key) and key in seen_findings:
            continue
        if any(key):
            seen_findings.add(key)
        errors.append(
            {
                "ticket_id": row.get("ticket_id") or "",
                "details_error": details,
                # Kategori error dari tabel Error Code (mis. "Data Input"). Sejak
                # 28 Agustus 2026 INILAH yang dirender Agent Error Summary di kolom
                # "Failure Category"; ``details_error`` tetap dikirim karena dipakai
                # untuk de-dup di atas dan oleh kolom "Detail Error" yang masih ada
                # di template (nonaktif lewat flag).
                "error_category": row.get("error_category") or "",
                # Kutipan transkrip + timestamp pemicu error code, apa adanya dari
                # ``trigger_source`` evaluasi (sudah ikut banding QC yang disetujui).
                "evidence": evidence,
                "reason": reason,
            }
        )

    # Badword Summary: ucapan agent bersentimen negatif kepada nasabah. Tidak
    # tersentuh banding Error Code (bandingnya menyasar baris error code, bukan
    # temuan ini), jadi cukup dibaca dari evaluasi yang sudah disesuaikan di atas.
    # Kosong untuk hasil lama yang dievaluasi sebelum prompt v53.
    badwords = badword_rows(evaluation) if evaluation else []

    return {
        "result_id": result_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        # Lama bergabung sebagai TLO, dihitung sampai tanggal submit tiket ini
        # (bukan sampai hari ini) — ex: "3 tahun 1 hari".
        "durasi_bergabung": nj["tenure"] or "-",
        "selisih_hari": nj["diff_days"],  # submit_time - JOIN POSISI, in days (None if unknown)
        "campaign": _campaign_interest(evaluation),
        "tanggal": submit_time,
        "errors": errors,
        # [{ticket_id, timestamp, quote, evidence, reason}] — tabel Badword Summary.
        "badwords": badwords,
    }
