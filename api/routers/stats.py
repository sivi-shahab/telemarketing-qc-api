import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_spq_head_user,
    get_tl_qc_or_spq_head_user,
)
from sales_lookup import (
    agent_ids_for_hierarchy_filter,
    cashline_agent_ids_for_agent,
    cashline_agent_ids_for_am,
    cashline_agent_ids_for_tl,
    hierarchy_filter_options,
)
from api.schemas.result import (
    DailyStatsResponse,
    ResultListItem,
    ResultListResponse,
    StatsResponse,
    TicketDeleteResponse,
)
from db import crud
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    apply_added_score_appeals,
    inject_added_rows,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    CARD_HOLDER_DYNAMIC_FIELDS,
    build_error_code_table,
    card_holder_two_match_satisfied,
    code_for_cashline_field,
    effective_appeal_status,
    not_fulfilled_reason,
)
from compliance.reference_data import get_credit_limit, get_customer_info, npwp_required_by_limit
from compliance.stats_aggregate import (
    _missing_docs_map,
    _parse_ymd,
    _result_ai_status,
    compute_ai_status_timeseries,
    compute_stats_snapshot,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

# Export column order (per tambahan.md).
_EXPORT_COLUMNS = ["id", "category", "item_code", "description", "score", "evidence", "ticket_id"]
_ERROR_COLUMNS = ["id", "sumber", "error_code", "item_code", "details_error", "reason", "evidence", "ticket_id"]
_RINGKASAN_COLUMNS = ["keterangan", "perubahan", "hasil"]

# TMS change-flag key -> human label surfaced as an Upload Document trigger. Order
# here is the display order in the button tooltip.
_CHANGE_LABELS = {
    "kantor": "Perubahan Alamat Kantor",
    "rumah": "Perubahan Alamat Rumah",
    "npwp": "Perubahan NPWP",
    "nik": "Perubahan NIK",
}

# Pembanding aman untuk uploaded_at yang NULL saat sorting. uploaded_at disimpan
# sebagai naive UTC, jadi sentinel-nya juga harus naive (jangan tz-aware).
_EPOCH = datetime.min


def _scoped_customer_ids(db: Session, current_user) -> Optional[list]:
    """The customer/ticket ids a scoped role may see, else ``None`` (no scoping):

    - ``qc``: only the tickets a Team Leader QC has ASSIGNED to them (manual QC
      assignment). No assignment => empty list => sees nothing.
    - ``area_manager``: tickets of every agent under their ``NIP AM`` (== username) &
      DEDICATED=cashline — i.e. their whole area (all team leaders + agents below).
    - ``team_leader``: tickets of agents under their ``NIP TL`` (== username) &
      DEDICATED=cashline — i.e. their whole team.
    - ``sales_agent`` (individual agent): tickets of the agent whose ``NIP BARU``
      (== username) & DEDICATED=cashline — i.e. their own tickets.
    - ``spq_head`` / ``team_leader_qc`` / ``telesales_head`` / system: ``None`` =>
      see everything.
    """
    role = getattr(current_user, "role", None)
    username = getattr(current_user, "username", "") or ""
    if role == "qc":
        return crud.assigned_ticket_ids_for_qc(db, username)
    if role == "area_manager":
        agent_ids = cashline_agent_ids_for_am(db, username)
    elif role == "team_leader":
        agent_ids = cashline_agent_ids_for_tl(db, username)
    elif role == "sales_agent":
        agent_ids = cashline_agent_ids_for_agent(db, username)
    else:
        return None
    return crud.customer_ids_for_agent_ids(db, list(agent_ids))


def _customer_id_from_files(source_files) -> Optional[str]:
    """Derive the customer/ticket id (prefix before the first ``_``) from the
    first source filename, e.g. ``181001bWvi_20260521150215.pdf`` -> ``181001bWvi``."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]


def _evaluation_dict(result_json) -> Optional[dict]:
    """Return the LLM ``evaluation`` object from a stored result_json, or None."""
    if not isinstance(result_json, dict):
        return None
    evaluation = result_json.get("evaluation")
    return evaluation if isinstance(evaluation, dict) else None


def _numeric_or_none(value) -> Optional[float]:
    """Return ``value`` as a number (int when whole), or None if not numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value == int(value) else value


def _to_num(value) -> Optional[float]:
    """Coerce ``value`` (number or numeric string) to a number (int when whole),
    or None if not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    else:
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
    if n != n:  # NaN
        return None
    return int(n) if n == int(n) else n


def _max_score(evaluation: dict):
    """Skor maksimal panggilan = jumlah produk yang diminati customer
    (Mega Cashline 108.75 + Mega Ultima Shield 41.25); fallback ke
    ``maximum_score`` dari evaluasi bila tidak ada produk yang diminati."""
    total = 0.0
    found = False
    if (evaluation.get("cashline_interest") or {}).get("status") == "INTERESTED":
        total += 108.75
        found = True
    if (evaluation.get("mus_interest") or {}).get("status") == "INTERESTED":
        total += 41.25
        found = True
    if found:
        return int(total) if total == int(total) else total
    return _to_num(evaluation.get("maximum_score"))


def _scorecard_score(evaluation: dict):
    """Skor scorecard (phase 2) = skor maksimal dikurangi bobot tiap item
    yang BELUM_SESUAI. Return None bila skor maksimal tidak diketahui."""
    max_sc = _max_score(evaluation)
    if max_sc is None:
        return None
    belum = sum(
        w for it in (evaluation.get("scorecard_result") or [])
        if it.get("status") == "BELUM_SESUAI"
        and (w := _to_num(it.get("weight"))) is not None
    )
    score = max_sc - belum
    return int(score) if score == int(score) else score


def _manual_status(qc_req, missing_docs: bool) -> Optional[str]:
    """The "Manual Status" column value (shown to every role): the QC's per-ticket
    verdict as confirmed through the QC->TL QC->SPQ Head hierarchy, plus the
    missing-documents default. One of: 'approve' | 'reject' | 'ditolak' | 'pending'
    | None.

    - approved verdict -> 'approve' (requested PASS) / 'reject' (requested FAIL);
    - the hierarchy rejected the QC's proposal -> 'ditolak' (see review/tl_qc_comment);
    - awaiting the hierarchy -> 'pending';
    - no request but the ticket is missing required documents -> 'pending';
    - otherwise None (no manual status)."""
    if qc_req is None:
        return "pending" if missing_docs else None
    eff = effective_appeal_status(qc_req)
    if eff == "approved":
        return "approve" if qc_req.requested_status == "PASS" else "reject"
    if eff == "rejected":
        return "ditolak"
    return "pending"


def _appeal_summary(appeals: list) -> Optional[dict]:
    """Summarize Error Code appeals ("banding") for one result, for the Results
    list "Banding Review" column: latest-per-row status counts + full history.
    QC uses this to see SPQ Head's review outcomes; SPQ Head uses ``pending`` to
    spot which IDs are awaiting review."""
    if not appeals:
        return None
    # Latest appeal per (error_code, item_code) — appeals arrive oldest-first.
    latest = {}
    for a in appeals:
        latest[(a.error_code, a.item_code)] = a
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    tl_pending = 0   # awaiting Team Leader QC decision
    spq_pending = 0  # escalated by TL QC, awaiting SPQ Head
    for a in latest.values():
        eff = effective_appeal_status(a)
        counts[eff] = counts.get(eff, 0) + 1
        tl = getattr(a, "tl_qc_status", "pending")
        if tl == "pending":
            tl_pending += 1
        elif tl == "escalated" and a.approval_status == "pending":
            spq_pending += 1
    history = [
        {
            "error_code": a.error_code,
            "item_code": a.item_code,
            "approval_status": a.approval_status,
            "tl_qc_status": getattr(a, "tl_qc_status", "pending"),
            "tl_qc_username": getattr(a, "tl_qc_username", None),
            "qc_reason": a.qc_reason,
            "tl_qc_comment": getattr(a, "tl_qc_comment", None),
            "review_comment": getattr(a, "review_comment", None),
            "requested_by_username": a.requested_by_username,
            "reviewed_by_username": a.reviewed_by_username,
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
            "requested_at": a.requested_at.isoformat() if a.requested_at else None,
        }
        for a in appeals
    ]
    return {
        "total": len(latest),
        "pending": counts["pending"],
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "tl_pending": tl_pending,
        "spq_pending": spq_pending,
        "history": history,
    }


@router.get("/stats/qc_performance")
def qc_performance(
    db: Session = Depends(get_db),
    current_user=Depends(get_tl_qc_or_spq_head_user),
):
    """Per-QC assigned / approved / approve-rate table, shown beneath the
    Hierarki Error Rate tree. Restricted to Team Leader QC, SPQ Head and admin —
    the roles that manage the QC division."""
    return crud.qc_performance_rows(db)


@router.get("/results/hierarchy_options")
def results_hierarchy_options(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """AM / TL / TLO options for the Results hierarchy filter, scoped to the
    caller's role. Empty lists mean the caller has no subordinates and the UI
    should hide the filter entirely.

    Team Leader QC oversees the QC team, not the sales org, so it gets QC / QC
    Support dropdowns (``qc_users`` / ``qc_support_users``) INSTEAD of AM/TL/TLO."""
    role = getattr(current_user, "role", None)
    if role == "team_leader_qc":
        qc = crud.qc_side_filter_options(db)
        return {
            "area_managers": [], "team_leaders": [], "agents": [],
            "qc_users": qc["qc_users"], "qc_support_users": qc["qc_support_users"],
        }
    opts = hierarchy_filter_options(db, role, getattr(current_user, "username", None))
    opts["qc_users"] = []
    opts["qc_support_users"] = []
    return opts


@router.get("/list_results", response_model=ResultListResponse)
def list_results(
    status: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None, description="Filter Approve/Reject: PASS | FAIL"),
    am_nip: Optional[str] = Query(None, description="Hierarchy filter: Area Manager NIP"),
    tl_nip: Optional[str] = Query(None, description="Hierarchy filter: Team Leader NIP"),
    agent_nip: Optional[str] = Query(None, description="Hierarchy filter: Sales Agent (TLO) NIP"),
    qc_username: Optional[str] = Query(None, description="Team Leader QC filter: tickets assigned to this QC (NIP)"),
    qc_support_username: Optional[str] = Query(None, description="Team Leader QC filter: tickets uploaded by this QC Support (NIP)"),
    date_start: Optional[str] = Query(None, description="Transcript-date lower bound (YYYY-MM-DD, WIB)"),
    date_end: Optional[str] = Query(None, description="Transcript-date upper bound (YYYY-MM-DD, WIB)"),
    banding_pending: bool = Query(False, description="Keep only tickets with an appeal awaiting the caller's review tier"),
    manual_status_pending: bool = Query(False, description="Pending Check menu: keep only tickets with a Manual Status request awaiting the caller's review tier (TL QC / SPQ Head)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    d_start = _parse_ymd(date_start)
    d_end = _parse_ymd(date_end)
    # Sales Agent (TL) & QC (agent) are scoped to their tickets; other roles: all.
    scoped_cids = _scoped_customer_ids(db, current_user)
    # Hierarchy dropdown (AM / TL / TLO). Narrows WITHIN the role scope above —
    # it never widens it, so an Area Manager passing another AM's NIP still only
    # sees their own tickets (the intersection is empty).
    filter_uids = agent_ids_for_hierarchy_filter(db, am_nip, tl_nip, agent_nip)
    if filter_uids is not None:
        filter_cids = crud.customer_ids_for_agent_ids(db, list(filter_uids))
        scoped_cids = (
            list(set(scoped_cids) & set(filter_cids)) if scoped_cids is not None
            else list(filter_cids)
        )
    # QC Support is a standalone, isolated result set: it sees ONLY its own uploads
    # (all complaint tickets); every other role EXCLUDES QC Support's uploads.
    role = getattr(current_user, "role", None)
    _iso = ({"uploaded_by_role": "qc_support"} if role == "qc_support"
            else {"exclude_uploaded_by_role": "qc_support"})
    # Team Leader QC filters by QC team member instead of the sales hierarchy:
    #  - "Semua QC"        -> narrow to tickets ASSIGNED to that QC;
    #  - "Semua QC Support" -> show that QC Support's uploads (overrides the default
    #    qc_support exclusion so those complaint tickets become visible).
    if role == "team_leader_qc":
        if (qc_username or "").strip():
            qc_cids = crud.assigned_ticket_ids_for_qc(db, qc_username)
            scoped_cids = (
                list(set(scoped_cids) & set(qc_cids)) if scoped_cids is not None
                else list(qc_cids)
            )
        if (qc_support_username or "").strip():
            _iso = {"uploaded_by_username": qc_support_username.strip()}
    ai_filter = ai_status.strip().upper() if isinstance(ai_status, str) else None
    if banding_pending:
        # "Manual Check" (banding) menu, filtered per role:
        #  - QC: every ticket that HAS a banding (any status) so the QC can track the
        #    review outcome of the bandings it filed;
        #  - Team Leader QC: tickets with a banding still pending its check;
        #  - SPQ Head: tickets with a banding escalated to it.
        # Derived from appeals (not stored on the row), so load the scoped set and
        # filter in Python.
        all_results, _ = crud.list_results(
            db, campaign=campaign, ticket_id=ticket_id, page=1, limit=1_000_000,
            customer_ids=scoped_cids, date_start=d_start, date_end=d_end, **_iso,
        )
        appeal_all = crud.error_code_appeals_for_results(db, [str(r.id) for r in all_results])
        is_spq = role in ("spq_head", "admin")
        is_qc = role == "qc"
        def _needs_review(rid):
            s = _appeal_summary(appeal_all.get(rid) or [])
            if not s:
                return False
            if is_qc:
                return s["total"] > 0
            return s["spq_pending"] > 0 if is_spq else s["tl_pending"] > 0
        matched = [r for r in all_results if _needs_review(str(r.id))]
        total = len(matched)
        results = matched[(page - 1) * limit : page * limit]
    elif manual_status_pending:
        # "Pending Check" menu (TL QC / SPQ Head): tickets whose Manual Status COLUMN
        # is "pending" — a QC status request still awaiting the hierarchy OR the
        # missing-documents default. Uses the SAME _manual_status helper the column
        # renders, so the queue matches the column value exactly (not stored on the
        # row, so load the scoped set and filter in Python).
        all_results, _ = crud.list_results(
            db, campaign=campaign, ticket_id=ticket_id, page=1, limit=1_000_000,
            customer_ids=scoped_cids, date_start=d_start, date_end=d_end, **_iso,
        )
        all_ids = [str(r.id) for r in all_results]
        qc_all = crud.qc_status_requests_for(db, all_ids)
        mdocs_all = _missing_docs_map(db, all_results)
        matched = [
            r for r in all_results
            if _manual_status(qc_all.get(str(r.id)), mdocs_all.get(str(r.id), False)) == "pending"
        ]
        total = len(matched)
        results = matched[(page - 1) * limit : page * limit]
    elif ai_filter in ("PASS", "FAIL"):
        # AI Status (Approve/Reject) is derived per result, not stored, so it can't be
        # filtered in SQL. Load the full matching set of done results, compute each
        # one's AI Status with the same canonical helper the table uses, then paginate
        # the filtered subset in Python.
        all_results, _ = crud.list_results(
            db, status="done", campaign=campaign, ticket_id=ticket_id, page=1,
            limit=1_000_000, customer_ids=scoped_cids, date_start=d_start, date_end=d_end, **_iso,
        )
        all_ids = [str(r.id) for r in all_results]
        appeal_all = crud.error_code_appeals_for_results(db, all_ids)
        qc_all = crud.qc_status_requests_for(db, all_ids)
        rj_all = crud.result_json_map(db, all_ids)
        mdocs_all = _missing_docs_map(db, all_results)
        matched = [
            r for r in all_results
            if _result_ai_status(
                rj_all.get(str(r.id)), appeal_all.get(str(r.id)), qc_all.get(str(r.id)),
                                mdocs_all.get(str(r.id), False)
            ) == ai_filter
        ]
        total = len(matched)
        results = matched[(page - 1) * limit : page * limit]
    else:
        results, total = crud.list_results(
            db, status=status, campaign=campaign, ticket_id=ticket_id, page=page,
            limit=limit, customer_ids=scoped_cids, date_start=d_start, date_end=d_end, **_iso,
        )
    # Customer Name + Nomor Kartu columns are surfaced to the "simple viewer" roles
    # (individual agent + team leader + area manager + telesales head), so only look
    # them up for those roles.
    is_simple_viewer = getattr(current_user, "role", None) in ("sales_agent", "team_leader", "area_manager", "telesales_head")
    # [FIX] Result id halaman ini — dipakai beberapa query batched di bawah.
    # Definisi ini hilang saat enrichment dipindah dari _build_items() ke sini,
    # menyebabkan NameError pada doctimes/qc_map.
    rid_list = [str(r.id) for r in results]
    # Which results on this page already have uploaded documents, plus the latest
    # upload time per result (single grouped query, no N+1).
    doctimes = crud.document_upload_times(db, rid_list)
    docset = set(doctimes.keys())
    # QC-proposed AI-status changes for this page (single grouped query, no N+1).
    qc_map = crud.qc_status_requests_for(db, rid_list)
    # Error Code appeals for this page (single grouped query, no N+1). Approved
    # appeals lift the score by flipping the linked scorecard item to SESUAI.
    appeal_map = crud.error_code_appeals_for_results(db, [str(r.id) for r in results])
    # TMS data-change flags per result (keyed by cid = customer id from the source
    # filename prefix). Gates the Upload Document button. Single batched query.
    cids = [_customer_id_from_files(r.source_files) for r in results]
    change_map = crud.get_tms_cashline_change_flags(db, [c for c in cids if c])
    # QC ticket -> (assignee, assigned_at). Team Leader QC / SPQ Head see who a
    # ticket is assigned to and when ("Assign Date").
    assignment_map = crud.assignment_map_for_tickets(db, [c for c in cids if c])
    # Per-ticket manual checks by QC for this page (batched, no N+1).
    manual_check_map = crud.qc_manual_checks_for_results(db, [str(r.id) for r in results])
    # Which results are "missing required documents" (TMS data changed or limit >= 50jt
    # but nothing uploaded) — drives the AI-status default + Manual Status "pending".
    mdocs_page = _missing_docs_map(db, results)
    items = []
    for r in results:
        ai_score = None
        ai_status = None
        passing_grade = None  # dynamic: taken from the LLM evaluation below
        maximum_score = None
        audio_duration = None
        campaign_interest = None
        critical_compliance_check = None
        non_tolerable_items = None
        evaluation = None  # per-iteration; the RETURN rule below reads it after the QC override
        data = None  # [NEW] di-declare di luar supaya bisa dibaca lagi setelah blok ini (reference_data)

        if r.status == "done":
            data = crud.get_result_data(db, str(r.id))
            if data is not None:
                if isinstance(data.result_json, dict):
                    audio_duration = data.result_json.get("audio_duration")
                evaluation = _evaluation_dict(data.result_json)
                if evaluation is not None:
                    # Terapkan banding yang di-approve (baris error code dihapus &
                    # item scorecard -> SESUAI) sebelum menghitung skor/status.
                    _row_appeals = appeal_map.get(str(r.id), [])
                    _approved = approved_appeals_only(_row_appeals)
                    _flip = [a for a in appeals_that_flip(_approved) if _appeal_kind(a) != "add"]
                    evaluation = apply_approved_appeals(evaluation, _flip)
                    evaluation = apply_approved_card_holder_appeals(evaluation, _flip)
                    evaluation = apply_approved_cashline_appeals(evaluation, _flip)
                    evaluation = apply_approved_critical_compliance_appeals(evaluation, _flip)
                    # 'add' bandings lower the score (attach a new error).
                    evaluation = apply_added_score_appeals(evaluation, added_appeals_only(_row_appeals))
                    # Non-tolerable (tolerable=NO) scorecard items still BELUM_SESUAI —
                    # surfaced as a Results column (and what forces AI Status = RETURN).
                    non_tolerable_items = _non_tolerable_reasons(evaluation)

                    # AI Score dihitung deterministik dari scorecard (sumber tunggal,
                    # konsisten dengan XLSX export): phase2 = skor maksimal dikurangi
                    # bobot item BELUM_SESUAI; phase3 = phase2 + verifikasi + kritis.
                    phase2 = _scorecard_score(evaluation)
                    verif = _to_num(evaluation.get("ai_score_verification"))
                    critical = _to_num(evaluation.get("ai_score_critical_compliance_check"))
                    if phase2 is not None or verif is not None or critical is not None:
                        score_total = (phase2 or 0) + (verif or 0) + (critical or 0)
                        ai_score = int(score_total) if score_total == int(score_total) else score_total

                    eval_pg = _numeric_or_none(evaluation.get("passing_grade"))
                    if eval_pg is not None:
                        passing_grade = eval_pg
                    maximum_score = _numeric_or_none(evaluation.get("maximum_score"))

                    # AI Status mengikuti skor deterministik di atas vs passing grade;
                    # fallback ke ai_status dari LLM bila skor/passing tidak tersedia.
                    if ai_score is not None and passing_grade is not None:
                        ai_status = "PASS" if ai_score >= passing_grade else "FAIL"
                    else:
                        status_val = evaluation.get("ai_status")
                        if isinstance(status_val, str):
                            ai_status = status_val.strip().upper()

                    ci = evaluation.get("campaign_interest")
                    if isinstance(ci, list):
                        campaign_interest = ci

                    ccc = evaluation.get("critical_compliance_check")
                    if isinstance(ccc, dict):
                        # Keep only what the Results column needs: overall status +
                        # the checked items (item_code / requirement / status).
                        items_raw = ccc.get("checked_items")
                        critical_compliance_check = {
                            "status": ccc.get("status"),
                            "checked_items": items_raw if isinstance(items_raw, list) else [],
                        }

        # An approved QC request overrides the displayed AI Status (table column only).
        qc_req = qc_map.get(str(r.id))
        if qc_req is not None and qc_req.approval_status == "approved":
            ai_status = qc_req.requested_status

        # Final rule (checked last): a non-tolerable, still-unmet scorecard item forces
        # RETURN, overriding score-pass and even an approved QC status change.
        if ai_status == "PASS" and evaluation is not None and _has_blocking_intolerable_item(evaluation):
            ai_status = "FAIL"

        cid = _customer_id_from_files(r.source_files)
        # Upload Document gate: TMS data changes for this result (Alamat Kantor/Rumah,
        # NPWP, NIK). Enabled when at least one change flag is set.
        flags = change_map.get(cid or "", {})
        document_triggers = [lbl for k, lbl in _CHANGE_LABELS.items() if flags.get(k)]
        document_upload_types = crud.allowed_doc_types_from_flags(flags)
        # "Kekurangan dokumen": dokumen wajib (perubahan data TMS ATAU limit >= 50jt)
        # tapi belum ada upload. Basis sama dengan chart/KPI (_missing_docs_map).
        missing_docs = mdocs_page.get(str(r.id), False)

        # --- Final AI Status precedence (last wins). base ai_status already reflects
        # the score with approved error-code appeals applied. ---
        qc_req = qc_map.get(str(r.id))
        approved_override = qc_req is not None and effective_appeal_status(qc_req) == "approved"
        # 1) non-tolerable veto
        if ai_status == "PASS" and evaluation is not None and _has_blocking_intolerable_item(evaluation):
            ai_status = "FAIL"
        # 2) missing-documents default -> FAIL, unless an approved Manual Status flips it
        if missing_docs and not approved_override:
            ai_status = "FAIL"
        # 3) approved Manual Status override — final authority (wins over the veto,
        # the missing-docs default, and the appeal-adjusted score)
        if approved_override:
            ai_status = qc_req.requested_status
        # "Manual Status" column value (all roles).
        manual_status = _manual_status(qc_req, missing_docs)
        customer_name = None
        account_number = None
        credit_limit = None
        if cid:
            # Fetch the customer's data once: simple viewers need name/card too, the
            # rest need only the credit limit (for the NPWP-upload trigger).
            if is_simple_viewer:
                info, _ = get_customer_info(cid, db)
                customer_name = info.get("customer_name")
                account_number = info.get("account_number")
                credit_limit = info.get("credit_limit")
            else:
                credit_limit = get_credit_limit(cid, db)
        # NPWP-upload trigger: a disbursement limit (CUST_CRLIMIT) >= Rp 50 juta
        # requires an NPWP, so allow it regardless of the TMS change flags.
        if npwp_required_by_limit(credit_limit):
            if "npwp" not in document_upload_types:
                document_upload_types = [*document_upload_types, "npwp"]
            _npwp_lbl = "NPWP (Limit >= 50 jt)"
            if _npwp_lbl not in document_triggers:
                document_triggers = [*document_triggers, _npwp_lbl]
        items.append(
            ResultListItem(
                result_id=str(r.id),
                id=cid,
                customer_name=customer_name,
                account_number=account_number,
                credit_limit=(credit_limit if is_simple_viewer else None),
                campaign=r.campaign,
                source_files=r.source_files,
                num_calls=r.num_calls,
                audio_duration=audio_duration,
                campaign_interest=campaign_interest,
                critical_compliance_check=critical_compliance_check,
                non_tolerable_items=non_tolerable_items,
                status=r.status,
                ai_score=ai_score,
                passing_grade=passing_grade,
                maximum_score=maximum_score,
                ai_status=ai_status,
                uploaded_at=r.uploaded_at,
                uploaded_by_username=r.uploaded_by_username,
                uploaded_by_role=r.uploaded_by_role,
                generated_at=r.generated_at,
                completed_at=r.completed_at,
                processing_sec=r.processing_sec,
                document_triggers=document_triggers,
                document_upload_types=document_upload_types,
                has_documents=str(r.id) in docset,
                document_uploaded_at=doctimes.get(str(r.id)),
                qc_request=qc_req,
                manual_status=manual_status,
                appeal_summary=_appeal_summary(appeal_map.get(str(r.id), [])),
                assigned_qc=(assignment_map.get(cid or "") or (None, None))[0],
                assigned_at=(assignment_map.get(cid or "") or (None, None))[1],
                qc_checked_at=getattr(manual_check_map.get(str(r.id)), "created_at", None),
                qc_checked_by=getattr(manual_check_map.get(str(r.id)), "checked_by_username", None),
            )
        )
    return ResultListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    data = crud.get_stats(db)
    return StatsResponse(**data)


@router.get("/stats/daily", response_model=DailyStatsResponse)
def get_daily_stats(db: Session = Depends(get_db)):
    days = crud.get_daily_stats(db)
    return DailyStatsResponse(days=days)


# --- Revamped Statistics dashboard (daily-cached snapshot) ------------------
# All three endpoints read the same once-per-day snapshot (overview, per-agent,
# campaign month-to-month, org hierarchy); see crud.get_or_build_stats_snapshot.

def _snapshot_for(db: Session, current_user) -> dict:
    """Statistics snapshot sesuai scope pemakainya.

    Area Manager mendapat snapshot yang dihitung ulang dari tiket area-nya saja,
    sehingga KPI, donut, Performa Sales, Performa Campaign dan hierarki semuanya
    konsisten satu sama lain. Role lain memakai snapshot global yang di-cache.

    Catatan: versi scoped TIDAK di-cache — dihitung per request. Bebannya
    terbatas karena query-nya sudah difilter di sisi DB ke tiket area tersebut.
    """
    if getattr(current_user, "role", None) != "area_manager":
        return crud.get_or_build_stats_snapshot(db)
    return compute_stats_snapshot(db, _scoped_customer_ids(db, current_user) or [])


@router.get("/stats/overview")
def stats_overview(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """KPI cards + status donut + sales-performance table."""
    snap = _snapshot_for(db, current_user)
    return {
        "overview": snap["overview"],
        "agents": snap["agents"],
        # Per-campaign breakdowns for the Overview campaign filter (older cached
        # snapshots may predate these keys, hence the defaults).
        "campaigns": snap.get("campaigns", []),
        "overview_by_campaign": snap.get("overview_by_campaign", {}),
        "agents_by_campaign": snap.get("agents_by_campaign", {}),
    }


@router.get("/stats/campaigns_monthly")
def stats_campaigns_monthly(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Per (campaign, month) performance report: submissions, Risk Base breakdown
    (High/Medium/Low/System/New) and error rate. Area Manager melihat area-nya saja."""
    return _snapshot_for(db, current_user)["campaign_monthly"]


@router.get("/stats/hierarchy")
def stats_hierarchy(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Error-rate hierarchy: Area Manager -> Team Leader -> Agent, plus All Telesales.

    Telesales Head, SPQ Head/Admin dan TL QC melihat pohon penuh. Seorang
    ``area_manager`` hanya melihat node-nya sendiri (TL + agent di bawahnya),
    termasuk ``all_telesales`` yang ikut dihitung dari area itu saja.
    """
    return _snapshot_for(db, current_user)["hierarchy"]


@router.get("/stats/role_counts")
def stats_role_counts(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """User counts per role, split into the Sales and QC divisions — for the
    "Jumlah Sales" / "Jumlah QC" tables under the Overview donut."""
    from sqlalchemy import func as _f
    from db.models import User
    rows = dict(
        db.query(User.role, _f.count()).filter(User.is_active == True).group_by(User.role).all()  # noqa: E712
    )
    return {
        "sales": {r: rows.get(r, 0) for r in ("telesales_head", "area_manager", "team_leader", "sales_agent")},
        "qc": {r: rows.get(r, 0) for r in ("team_leader_qc", "qc", "qc_support")},
    }


@router.get("/stats/my_overview")
def stats_my_overview(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Scoped KPI overview for an Area Manager, Team Leader or Sales Agent
    (individual agent): totals, failed count, and error rate over only the tickets
    they may see. For a Team Leader (team) or Area Manager (area) the response also
    includes ``agents`` — the per-agent roster (for the Statistics table); each row
    carries its ``team_leader`` so the Area Manager roster can group by TL. For an
    Area Manager the response also carries ``hierarchy`` — a scoped Team Leader ->
    Agent tree for the "Hierarki Error Rate" tab (no Area Manager level)."""
    from compliance.stats_aggregate import (
        compute_scoped_hierarchy,
        compute_scoped_overview,
        compute_team_agents,
    )

    role = getattr(current_user, "role", None)
    username = getattr(current_user, "username", "") or ""
    cids = _scoped_customer_ids(db, current_user)
    resp = {"overview": compute_scoped_overview(db, cids or [])}
    if role == "area_manager":
        roster = compute_team_agents(db, cashline_agent_ids_for_am(db, username))
        resp["agents"] = roster
        resp["hierarchy"] = compute_scoped_hierarchy(roster)
    elif role == "team_leader":
        resp["agents"] = compute_team_agents(db, cashline_agent_ids_for_tl(db, username))
    return resp


@router.get("/stats/ai_status_timeseries")
def stats_ai_status_timeseries(
    granularity: str = "monthly",
    start: Optional[str] = None,
    end: Optional[str] = None,
    campaign: Optional[str] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Approve/Reject proportions over time for the 100% stacked column chart.

    Scoped exactly like the KPI/donut it feeds: Sales Agent / Team Leader / Area
    Manager see only their tickets; QC / TL-QC / Telesales Head / SPQ Head / Admin
    see everything. ``granularity`` = daily|weekly|monthly|quarterly|semester|yearly;
    ``start``/``end`` = optional 'YYYY-MM-DD' WIB bounds; ``campaign`` optional filter;
    ``offset`` pages the default window by whole windows (0 = latest, <0 older)."""
    role = getattr(current_user, "role", None)
    scoped_roles = ("sales_agent", "team_leader", "area_manager")
    customer_ids = _scoped_customer_ids(db, current_user) if role in scoped_roles else None
    return compute_ai_status_timeseries(db, customer_ids, campaign, granularity, start, end, offset)


@router.post("/stats/refresh")
def stats_refresh(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Force-recompute today's Statistics snapshot (SPQ Head only)."""
    if getattr(current_user, "role", None) not in ("spq_head", "admin"):
        raise HTTPException(status_code=403, detail="Hanya SPQ Head yang dapat me-refresh statistik")
    crud.get_or_build_stats_snapshot(db, force=True)
    return {"status": "ok"}


def _append_scorecard_rows(sheet, result_json, cust_id) -> None:
    """Append scorecard rows (one per ``scorecard_result`` item, plus one per
    ``verified_parameter`` for Verifikasi Dinamis) from a single result JSON.
    The ``id`` column is the result-level ``cust_id`` (not derived from ticket_id)."""
    if not result_json:
        return
    evaluation = result_json.get("evaluation") or {}
    scorecard = evaluation.get("scorecard_result") or []
    for item in scorecard:
        evidence = item.get("evidence") or {}
        # LLM emits ticket_id inside evidence; fall back to an item-level field.
        ticket_id = evidence.get("ticket_id") or item.get("ticket_id") or ""
        ev_text = f'{evidence.get("timestamp", "")} {evidence.get("quote", "")}'.strip()
        sheet.append(
            [
                cust_id,
                item.get("category", ""),
                item.get("item_code", ""),
                item.get("requirement", ""),
                item.get("item_score", ""),
                ev_text,
                ticket_id,
            ]
        )
        # Verifikasi Dinamis: one row per verified_parameter (mirror dashboard).
        if item.get("category") == "Verifikasi Dinamis":
            detail = item.get("dynamic_verification_detail") or {}
            for param in detail.get("verified_parameters") or []:
                aq = param.get("agent_question") or {}
                ca = param.get("customer_answer") or {}
                p_ticket = aq.get("ticket_id") or ""
                agent = f'{aq.get("timestamp", "")} {aq.get("quote", "")}'.strip()
                customer = f'{ca.get("timestamp", "")} {ca.get("quote", "")}'.strip()
                p_evidence = f"Agent : {agent} | Customer Answer : {customer}"
                sheet.append(
                    [
                        cust_id,
                        item.get("category", ""),
                        item.get("item_code", ""),
                        param.get("param_name", ""),
                        "",  # score dikosongkan (SKOR)
                        p_evidence,
                        p_ticket,
                    ]
                )


# --- Error Code table -------------------------------------------------------
# All error-code logic lives in compliance/error_codes.py (single source of
# truth, shared with the dashboard via the /result API). This sheet renders the
# build_error_code_table() output, grouped by source ("sumber").


def _append_errorcard_rows(sheet, result_json, cust_id, appeals=None) -> None:
    """Append error-card rows mirroring the dashboard Error Code table:
    id | sumber | error_code | item_code | details_error | reason | evidence | ticket_id."""
    if not result_json:
        return
    evaluation = result_json.get("evaluation") or {}
    # Approved adds only — an export must not carry a banding that Team Leader QC /
    # SPQ Head has not accepted yet.
    table = inject_added_rows(build_error_code_table(evaluation), added_appeals_only(appeals or []))
    for row in table:
        sheet.append([
            cust_id,
            row["sumber"],
            row["error_code"],
            row["item_code"],
            row["details_error"],
            row["reason"],
            row["evidence"],
            row["ticket_id"],
        ])


def _non_tolerable_reasons(evaluation: dict) -> list:
    """Negated reasons for non-tolerable (tolerable=NO) scorecard items still unmet
    (status=BELUM_SESUAI), e.g. "Agent tidak menjelaskan biaya" — TEXT ONLY, without
    the (SC_CL_x) code suffix. Reads the (appeal-adjusted) evaluation, so approved
    appeals that flip an item to SESUAI drop out of the list."""
    out = []
    for item in evaluation.get("scorecard_result") or []:
        tol = str((item or {}).get("tolerable") or "").strip().upper()
        st = str((item or {}).get("status") or "").strip().upper()
        if tol == "NO" and st == "BELUM_SESUAI":
            reason = not_fulfilled_reason(item)  # "... (SC_CL_x)"
            code = (item or {}).get("item_code")
            if code:
                # Drop the " (SC_CL_x)" code tag wherever it appears (it sits mid-
                # string for the no-requirement fallback), leaving text only.
                reason = reason.replace(f" ({code})", "")
            out.append(reason)
    return out


def _has_blocking_intolerable_item(evaluation: dict) -> bool:
    """A scorecard item that is non-tolerable (tolerable=NO) yet still unmet
    (status=BELUM_SESUAI) forces an AI status of RETURN (FAIL), regardless of the
    numeric score. Reads the (appeal-adjusted) evaluation, so approved appeals
    that flip an item to SESUAI correctly stop triggering this."""
    return bool(_non_tolerable_reasons(evaluation))


def _ai_status_pass(evaluation: dict) -> bool:
    """PASS/FAIL: prefer the LLM's ai_status; fall back to final score vs passing grade.
    A non-tolerable, still-unmet scorecard item vetoes a pass (RETURN) regardless."""
    if _has_blocking_intolerable_item(evaluation):
        return False
    status = evaluation.get("ai_status")
    if isinstance(status, str):
        return status.strip().upper() == "PASS"
    final = _to_num(evaluation.get("ai_score_phase_3"))
    passing = _to_num(evaluation.get("passing_grade"))
    if final is None or passing is None:
        return False
    return final >= passing


def _append_ringkasan_rows(sheet, result_json) -> None:
    """Append the AI score-summary as a running-balance table (mirrors the
    dashboard "Ringkasan Penilaian AI"): Keterangan | Perubahan | Hasil."""
    if not result_json:
        return
    evaluation = result_json.get("evaluation") or {}
    # phase2 = skor maksimal dikurangi bobot tiap item BELUM_SESUAI.
    phase2 = _scorecard_score(evaluation)
    verif = _to_num(evaluation.get("ai_score_verification"))
    critical = _to_num(evaluation.get("ai_score_critical_compliance_check"))
    # phase3 = phase2 + verifikasi data + pelanggaran kritis.
    if phase2 is not None or verif is not None or critical is not None:
        phase3 = (phase2 or 0) + (verif or 0) + (critical or 0)
        phase3 = int(phase3) if phase3 == int(phase3) else phase3
    else:
        phase3 = None
    passing = _to_num(evaluation.get("passing_grade"))
    # max_score diturunkan dari breakdown produk yang diminati (bagian 1),
    # fallback ke maximum_score saat tidak ada produk yang diminati.
    breakdown = []
    if (evaluation.get("cashline_interest") or {}).get("status") == "INTERESTED":
        breakdown.append(("Mega Cashline", 108.75))
    if (evaluation.get("mus_interest") or {}).get("status") == "INTERESTED":
        breakdown.append(("Mega Ultima Shield", 41.25))
    if breakdown:
        max_score = sum(s for _, s in breakdown)
        max_score = int(max_score) if max_score == int(max_score) else max_score
    else:
        max_score = _to_num(evaluation.get("maximum_score"))
    blank = ""
    # 1) Skor Maksimal — sum of interested products (breakdown dihitung di atas).
    sheet.append([
        "Skor Maksimal panggilan ini",
        blank,
        blank if breakdown else (max_score if max_score is not None else blank),
    ])
    for name, score in breakdown:
        sheet.append([f"Tertarik {name}", score, blank])
    if breakdown:
        total = sum(s for _, s in breakdown)
        total = int(total) if total == int(total) else total
        sheet.append(["Skor Maksimal", blank, total])
    # 2) Pengurangan — penilaian scorecard.
    belum = [it for it in (evaluation.get("scorecard_result") or []) if it.get("status") == "BELUM_SESUAI"]
    sheet.append(["Pengurangan – Penilaian scorecard", blank, blank])
    for it in belum:
        w = _to_num(it.get("weight"))
        change = -w if w is not None else blank
        desc = f'{it.get("category") or "—"} - {it.get("item_code") or "—"} - {it.get("requirement") or "—"}'
        sheet.append([desc, change, blank])
    delta = None
    if phase2 is not None and max_score is not None:
        delta = phase2 - max_score
        delta = int(delta) if delta == int(delta) else delta
    sheet.append([
        "Skor awal (penilaian scorecard)",
        delta if delta is not None else blank,
        phase2 if phase2 is not None else blank,
    ])
    # 3) Pengurangan — verifikasi data.
    codes = [c for c in (evaluation.get("error_codes") or []) if c.get("error_code") in ("B02", "B03", "B05")]
    used: set = set()
    deductions = []
    # When the dynamic 2-match rule is met the leftover MISMATCH dynamic fields
    # score 0 as a group, so drop them from the deduction breakdown too.
    ch_two_match = card_holder_two_match_satisfied(evaluation.get("card_holder_verification"))
    for v in (evaluation.get("card_holder_verification") or []):
        s = _to_num(v.get("item_score"))
        if s is not None and s < 0:
            if ch_two_match and v.get("field") in CARD_HOLDER_DYNAMIC_FIELDS:
                continue
            deductions.append(("B17", v, s))
    for v in (evaluation.get("cashline_data_verification") or []):
        s = _to_num(v.get("item_score"))
        if s is not None and s < 0:
            deductions.append((code_for_cashline_field(v, codes, used), v, s))
    sheet.append(["Pengurangan – Verifikasi data", blank, blank])
    for code, v, s in deductions:
        field = str(v.get("field") or "").replace("_", " ").title()
        reason = v.get("reason")
        desc = f"{code} - {field}" + (f" - {reason}" if reason else "")
        sheet.append([desc, s, blank])
    after_verif = None
    if phase2 is not None or verif is not None:
        after_verif = (phase2 or 0) + (verif or 0)
        after_verif = int(after_verif) if after_verif == int(after_verif) else after_verif
    sheet.append([
        "Setelah verifikasi data",
        verif if verif is not None else blank,
        after_verif if after_verif is not None else blank,
    ])
    # 4) Pengurangan — pelanggaran kritis.
    sheet.append(["Pengurangan – Pelanggaran kritis", critical if critical is not None else blank, blank])
    # 5) Skor Akhir, Batas Lulus, Hasil.
    sheet.append(["Skor Akhir", blank, phase3 if phase3 is not None else blank])
    bl_label = f"Batas Lulus (90% × {max_score})" if max_score is not None else "Batas Lulus (90% × Skor Maksimal)"
    sheet.append([bl_label, blank, passing if passing is not None else blank])
    sheet.append(["Hasil", blank, "LULUS" if _ai_status_pass(evaluation) else "TIDAK LULUS"])


@router.get("/export_result_xlsx/{result_id}")
def export_result_xlsx(result_id: str, db: Session = Depends(get_db)):
    """Export scorecard rows (one per ``scorecard_result`` item) for a single
    ``done`` result as an XLSX download."""
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result tidak ditemukan")
    if result.status != "done":
        raise HTTPException(status_code=422, detail="result belum selesai (done)")
    data = crud.get_result_data(db, result_id)
    workbook = Workbook()
    ringkasan_sheet = workbook.active
    ringkasan_sheet.title = "ringkasan_penilaian_ai"
    ringkasan_sheet.append(_RINGKASAN_COLUMNS)
    scorecard_sheet = workbook.create_sheet("scorecard")
    scorecard_sheet.append(_EXPORT_COLUMNS)
    errorcard_sheet = workbook.create_sheet("errorcard")
    errorcard_sheet.append(_ERROR_COLUMNS)
    cust_id = _customer_id_from_files(result.source_files) or result_id
    if data and data.result_json:
        result_json = data.result_json
        # Apply approved Error Code appeals so the export matches the dashboard
        # (appealed error rows removed, linked scorecard item -> SESUAI, score up).
        appeals = crud.error_code_appeals_for_result(db, result_id)
        evaluation = result_json.get("evaluation") if isinstance(result_json, dict) else None
        if isinstance(evaluation, dict):
            _approved = approved_appeals_only(appeals)
            _flip = [a for a in appeals_that_flip(_approved) if _appeal_kind(a) != "add"]
            evaluation = apply_approved_appeals(evaluation, _flip)
            evaluation = apply_approved_card_holder_appeals(evaluation, _flip)
            evaluation = apply_approved_cashline_appeals(evaluation, _flip)
            evaluation = apply_approved_critical_compliance_appeals(evaluation, _flip)
            # 'add' bandings lower the score (attach a new error).
            evaluation = apply_added_score_appeals(evaluation, added_appeals_only(appeals))
            result_json = {**result_json, "evaluation": evaluation}
        _append_ringkasan_rows(ringkasan_sheet, result_json)
        _append_scorecard_rows(scorecard_sheet, result_json, cust_id)
        _append_errorcard_rows(errorcard_sheet, result_json, cust_id, appeals)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    # Filename = "<ID>_<timestamp>.xlsx" where the timestamp is the moment the
    # XLSX is generated (e.g. "180310ENv4_20260615103021.xlsx").
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{cust_id}_{timestamp}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete(
    "/delete_ticket",
    response_model=TicketDeleteResponse,
    dependencies=[Depends(get_spq_head_user)],
)
def delete_ticket(
    ticket_id: str = Query(..., description="Ticket id (prefix sebelum '_' pada nama file) yang semua entry-nya akan dihapus"),
    db: Session = Depends(get_db),
):
    """Delete ALL result entries for a ticket (SPQ Head only).

    Removes every Result whose ticket id matches ``ticket_id`` along with its
    dependent rows (result_data, documents, qc_status_requests,
    error_code_appeals) via ON DELETE CASCADE. Returns 404 when no entry matches.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ticket_id wajib diisi")
    deleted = crud.delete_results_by_ticket_id(db, tid)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tidak ada entry untuk ticket '{tid}'",
        )
    return TicketDeleteResponse(ticket_id=tid, deleted=deleted)