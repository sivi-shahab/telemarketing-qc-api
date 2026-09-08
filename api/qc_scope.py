"""QC ticket-assignment scoping helpers.

A QC (role ``qc``) may only see and act on tickets a Team Leader QC has assigned to
them. These helpers translate a result -> its ticket id (the customer-id prefix of
the source filenames) and enforce the assignment for QC callers. Non-QC roles are
gated by their own role dependencies and pass through untouched.
"""
from fastapi import HTTPException, status

from qc_core.db import crud


def ticket_id_for_result(result) -> str | None:
    """The customer/ticket id (prefix before the first ``_``) of a result's first
    source filename, e.g. ``181001bWvi_2026...pdf`` -> ``181001bWvi``."""
    sf = getattr(result, "source_files", None) or []
    if sf and isinstance(sf[0], str) and sf[0]:
        return sf[0].split("_", 1)[0]
    return None


def ensure_qc_assigned_to_result(db, current_user, result) -> None:
    """Raise 403 if a ticket-assigned user acts on a ticket not assigned to them.

    Berlaku untuk role ber-``data_scope`` ``qc_assigned``; role lain lewat begitu
    saja karena sudah dijaga capability-nya masing-masing.
    """
    from api.rbac import data_scope_for
    from api import permissions as P

    if data_scope_for(db, current_user) != P.SCOPE_QC_ASSIGNED:
        return
    ticket_id = ticket_id_for_result(result)
    assigned = crud.qc_username_for_ticket(db, ticket_id) if ticket_id else None
    me = (getattr(current_user, "username", "") or "").strip().casefold()
    if not assigned or assigned.strip().casefold() != me:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini tidak di-assign kepada Anda",
        )


def scoped_customer_ids(db, current_user):
    """The customer/ticket ids a scoped role may see, else ``None`` (no scoping).

    Ini versi DAFTAR dari ``ensure_can_view_result`` — keduanya harus menjawab
    pertanyaan yang sama ("tiket mana yang boleh dilihat login ini"), satu untuk
    menyaring daftar, satu untuk menjaga satu tiket:

    - ``qc_assigned``    -> hanya tiket yang di-ASSIGN kepadanya. Tanpa assignment =
      daftar kosong = tidak melihat apa pun (BUKAN "tanpa batas").
    - ``qc_support_own`` -> hanya tiket complaint yang di-upload QC Support.
    - ``sales_*``        -> tiket agent di bawahnya (dirinya / tim / area).
    - ``all`` / sistem   -> ``None`` = tanpa penyempitan.

    Di ATAS itu berlaku pembatasan CAMPAIGN role (``effective_campaigns_for``) untuk
    SEMUA cakupan — lihat ``narrow_to_campaigns``. Sebelum 12 Agustus 2026 pembatasan
    itu hanya dipasang di ``list_results``, sehingga role ber-``data_scope: all`` yang
    sengaja dipersempit ke satu campaign tetap melihat SELURUH transkrip dan seluruh
    angka Statistics organisasi.

    Tinggal di sini, bukan di ``routers/stats.py``, supaya router lain (Results,
    Transcripts) memakai definisi yang SAMA. Waktu ia masih privat di stats.py,
    menu Transcripts tidak ikut ter-scope sama sekali.
    """
    from api.rbac import data_scope_for, effective_campaigns_for
    from api import permissions as P
    from qc_core.sales_lookup import (
        agent_ids_for_agent,
        agent_ids_for_am,
        agent_ids_for_tl,
    )

    username = getattr(current_user, "username", "") or ""
    scope = data_scope_for(db, current_user)
    campaigns = effective_campaigns_for(db, current_user)
    if scope == P.SCOPE_QC_ASSIGNED:
        base = crud.assigned_ticket_ids_for_qc(db, username)
    elif scope == P.SCOPE_QC_SUPPORT_OWN:
        base = crud.customer_ids_uploaded_by_role(db, "qc_support")
    elif scope in (P.SCOPE_SALES_AM, P.SCOPE_SALES_TL, P.SCOPE_SALES_AGENT):
        if scope == P.SCOPE_SALES_AM:
            agent_ids = agent_ids_for_am(db, username, campaigns)
        elif scope == P.SCOPE_SALES_TL:
            agent_ids = agent_ids_for_tl(db, username, campaigns)
        else:
            agent_ids = agent_ids_for_agent(db, username, campaigns)
        base = crud.customer_ids_for_agent_ids(db, list(agent_ids))
    else:
        base = None
    return narrow_to_campaigns(db, base, campaigns)


def narrow_to_campaigns(db, customer_ids, campaigns):
    """Iris daftar cakupan dengan campaign yang boleh dilihat role.

    ``campaigns is None`` = tidak dibatasi -> ``customer_ids`` dikembalikan apa adanya
    (termasuk ``None`` yang berarti "tanpa penyempitan"). Bila dibatasi, hasilnya
    SELALU sebuah daftar — juga ketika cakupan asalnya ``None`` — karena "boleh
    melihat semua tiket" tetap harus mengecil menjadi "semua tiket campaign ini".

    Untuk cakupan sales sebenarnya sudah tersaring lewat tag roster; irisan ini tetap
    dipasang karena tag roster menjawab "orang ini melayani campaign apa", sedangkan
    yang perlu dijamin adalah "TIKET ini milik campaign apa" — dua hal yang bisa
    berbeda ketika seorang agent pernah mengerjakan tiket campaign lain.
    """
    if campaigns is None:
        return customer_ids
    allowed = crud.customer_ids_for_campaigns(db, campaigns)
    if customer_ids is None:
        return allowed
    allowed_set = set(allowed)
    return [c for c in customer_ids if c in allowed_set]


def _customer_id_of(result) -> str:
    """Ticket id sebuah ``Result`` = prefix sebelum "_" pada source file pertama.

    Definisi yang sama dipakai daftar Results, penyaring cakupan, dan penghapusan
    tiket — sengaja tidak dibuat versi kedua di sini.
    """
    files = getattr(result, "source_files", None) or []
    first = files[0] if files else None
    if not isinstance(first, str) or not first:
        return ""
    return first.split("_", 1)[0]


def ensure_can_view_result(db, current_user, result) -> None:
    """Raise 403 unless ``current_user`` is allowed to see ``result`` at all.

    Mencerminkan cakupan daftar Results, tetapi digerakkan ``data_scope`` role —
    bukan nama role — supaya role buatan operator (menu Manage Role) ikut ter-scope
    dengan benar alih-alih jatuh ke cabang "role tak dikenal, tolak":

      - ``qc_assigned``     -> hanya tiket yang di-assign kepadanya;
      - ``qc_support_own``  -> hanya tiket yang di-upload QC Support;
      - ``sales_*``         -> hanya tiket agent di bawahnya (tim / area / dirinya);
      - ``all``             -> tanpa penyempitan.

    Di atas itu berlaku pembatasan CAMPAIGN, diambil dari
    ``rbac.effective_campaigns_for``: untuk cakupan sales campaign-nya menyusul tag
    DEDICATED orangnya di roster, untuk cakupan lain menyusul deklarasi role. Daftar
    kosong berarti tidak dibatasi — itulah bawaan sisi QC.
    """
    from api.rbac import data_scope_for, effective_campaigns_for
    from api import permissions as P
    from qc_core.compliance.stats_aggregate import is_hidden_ticket

    # Tiket yang DISEMBUNYIKAN ditolak lebih dulu, sebelum aturan campaign & cakupan.
    # Ini gerbang tunggal seluruh permukaan per-tiket — detail transkrip, PDF, unduhan,
    # ekspor XLSX, Agent Error Summary, banding, status QC, manual check, dokumen —
    # jadi satu pemeriksaan di sini menutup semuanya sekaligus.
    #
    # 404, bukan 403: tiket yang disembunyikan harus terlihat seolah TIDAK ADA. 403
    # justru mengonfirmasi keberadaannya, dan itu bocor persis pada permukaan yang
    # sedang ditahan untuk presentasi.
    if is_hidden_ticket(_customer_id_of(result)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="result tidak ditemukan",
        )

    allowed_campaigns = effective_campaigns_for(db, current_user)
    if allowed_campaigns is not None:
        # List kosong = dibatasi ke himpunan kosong -> tidak ada tiket yang lolos.
        rc = (getattr(result, "campaign", None) or "").strip().casefold()
        if rc not in {(c or "").strip().casefold() for c in allowed_campaigns}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ticket ini di luar campaign yang menjadi cakupan Anda",
            )

    scope = data_scope_for(db, current_user)
    if scope == P.SCOPE_QC_ASSIGNED:
        ensure_qc_assigned_to_result(db, current_user, result)
        return
    if scope == P.SCOPE_ALL:
        return
    if scope == P.SCOPE_QC_SUPPORT_OWN:
        if (getattr(result, "uploaded_by_role", None) or "") != "qc_support":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ticket ini di luar cakupan Anda",
            )
        return

    # Sisi sales: dipersempit ke agent di bawah login ini.
    from qc_core.sales_lookup import (
        agent_ids_for_agent,
        agent_ids_for_am,
        agent_ids_for_tl,
    )

    username = (getattr(current_user, "username", "") or "").strip()
    if scope == P.SCOPE_SALES_TL:
        agent_ids = agent_ids_for_tl(db, username, allowed_campaigns)
    elif scope == P.SCOPE_SALES_AM:
        agent_ids = agent_ids_for_am(db, username, allowed_campaigns)
    elif scope == P.SCOPE_SALES_AGENT:
        agent_ids = agent_ids_for_agent(db, username, allowed_campaigns)
    else:  # data_scope tak dikenal: tolak, jangan bocor
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini di luar cakupan Anda",
        )

    ticket_id = ticket_id_for_result(result)
    allowed = set(crud.customer_ids_for_agent_ids(db, list(agent_ids)))
    if not ticket_id or ticket_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ticket ini di luar cakupan Anda",
        )
