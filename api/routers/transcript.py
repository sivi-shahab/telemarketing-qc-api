import io
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_user,
    get_db,
    get_evaluation_detail_user,
    get_minio,
    get_settings,
)
from api.schemas.result import ResultCreateResponse, ResultResponse, TranscriptListResponse
from api.permissions import MENU_TRANSCRIPTS, SCOPE_QC_SUPPORT_OWN
from api.rbac import data_scope_for, has_perm
from api.qc_scope import ensure_can_view_result, scoped_customer_ids
from db import crud
from sales_lookup import new_joiner_info
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    annotate_critical_compliance_reasons,
    derive_category_summary,
    added_appeals_visible,
    apply_added_score_appeals,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    apply_cashline_document_status,
    apply_static_document_status,
    normalize_dynamic_verification,
    normalize_static_verification,
    build_error_code_table,
    merge_dynamic_verification_rows,
    document_error_code_rows,
    effective_appeal_status,
    inject_added_rows,
    is_cashline_code,
    override_risk_base_for_new_joiner,
    relabel_error_table,
)
from compliance.scoring import (
    _to_num,
    base_ai_status,
    has_blocking_intolerable_item,
    non_tolerable_bomb,
    phase3_score,
    score_bomb_items,
    scorecard_score,
)
from compliance.stats_aggregate import (
    document_status_map,
    _doc_sla_expired,
    _missing_docs_map,
    doc_requirement_labels,
    wrong_document_types,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/upload_transcript", response_model=ResultCreateResponse)
def upload_transcript(
    files: list[UploadFile] = File(...),
    campaign: str = Form(...),
    # True (default) = reuse hasil `done` sebelumnya untuk ID ini (clone tanpa LLM);
    # False = paksa proses ulang lewat LLM meski hasil lama ada.
    reuse: bool = Form(True),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimal satu file PDF transkrip diperlukan",
        )

    # Validate every file is a PDF before doing anything.
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"File '{f.filename}' bukan PDF — hanya .pdf yang diterima",
            )

    # Campaign must exist and be active.
    if crud.get_active_campaign(db, campaign) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign '{campaign}' tidak ditemukan atau tidak aktif",
        )

    source_files = [f.filename for f in files]

    # Cek apakah customer ID ini sudah punya hasil `done` sebelumnya (kandidat
    # untuk di-clone). Dipilih dengan tie-break: utamakan yang sudah ada banding,
    # jika tidak ada ambil upload terbaru.
    customer_id = _customer_id_from_files(source_files)
    # Reuse hanya dicari bila mode reuse aktif; mode "proses ulang" (reuse=False)
    # selalu memproses via LLM walau hasil lama ada.
    source = crud.pick_reusable_done_result(db, customer_id) if (reuse and customer_id) else None

    # Setiap upload = row Result baru (supaya muncul sebagai baris tersendiri di
    # tabel Results dengan Transcript Upload = waktu upload sekarang).
    result = crud.create_result(
        db,
        campaign=campaign,
        source_files=source_files,
        num_calls=len(files),
        transcript_path=None,
        uploaded_by_username=getattr(current_user, "username", None),
        uploaded_by_role=getattr(current_user, "role", None),
    )
    result_id = str(result.id)

    # Simpan file transkrip yang diupload ke transcripts/{result_id}/{filename}
    # (agar viewer/download PDF jalan untuk row baru ini).
    settings = get_settings()
    client = get_minio()
    for f in files:
        data = f.file.read()
        object_name = f"{result_id}/{f.filename}"
        client.put_object(
            settings.minio_bucket_transcripts,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type="application/pdf",
        )
    result.transcript_path = f"{result_id}/"
    db.commit()

    if source is not None:
        # Sudah pernah diproses -> clone hasil lama (evaluasi + banding +
        # approval SPQ Head) ke row baru, TANPA proses ulang ke LLM.
        result_json = crud.clone_result_from(db, source, result)
        # Mirror JSON hasil ke bucket results agar konsisten dengan alur worker.
        try:
            payload = json.dumps(result_json).encode("utf-8")
            client.put_object(
                settings.minio_bucket_results,
                f"{result_id}.json",
                io.BytesIO(payload),
                length=len(payload),
                content_type="application/json",
            )
        except Exception:
            pass
        return ResultCreateResponse(result_id=result_id, status="done", reused=True)

    # Belum pernah ada hasil `done` -> proses normal lewat LLM.
    from api.celery_client import celery_app

    celery_app.send_task(
        "worker.tasks.process_transcript.process_transcript", args=[result_id]
    )

    return ResultCreateResponse(result_id=result_id, status="pending")


# Accepted audio extensions -> Content-Type for MinIO storage.
AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
    ".webm": "audio/webm",
    ".amr": "audio/amr",
}

# Ekstensi yang benar-benar diawasi producer antrian STT (AUDIO_EXTS di
# /data/script_antrian/producer_watch.py). Sengaja LEBIH SEMPIT dari
# AUDIO_CONTENT_TYPES di atas: format lain memang bisa diterima dan diarsipkan ke
# S3, tapi kalau ditulis ke folder antrian ia hanya akan menumpuk tanpa pernah
# diproses — jadi ditolak di depan dengan pesan yang jujur.
VTT_SUPPORTED_AUDIO_EXTS = (".wav", ".wave", ".mp3")

# Akhiran berkas sementara saat menulis ke folder antrian. WAJIB di luar
# AUDIO_EXTS producer: ``on_created`` di sana tidak menunggu berkas selesai
# ditulis, jadi nama sementara ber-ekstensi audio akan dipublish saat isinya baru
# separuh. Setelah tuntas, berkas di-rename — dan rename itulah yang memicu
# ``on_moved``, jalur yang memang dirancang untuk pola tulis-lalu-rename.
_RECORDING_TMP_SUFFIX = ".part"


def _ext_of(filename: str) -> str:
    name = filename or ""
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def ensure_vtt_supported_audio(filename: str) -> str:
    """Pastikan ekstensi ada di daftar yang diawasi producer, atau lempar 422."""
    ext = _ext_of(filename)
    if ext not in VTT_SUPPORTED_AUDIO_EXTS:
        didukung = ", ".join(VTT_SUPPORTED_AUDIO_EXTS)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"File '{filename}' berformat {ext or 'tanpa ekstensi'} — "
                f"pemrosesan STT hanya mendukung {didukung}. Konversi dulu ke "
                f"salah satu format itu."
            ),
        )
    return ext


def write_audio_to_recording_dir(directory: str, filename: str, data: bytes) -> str:
    """Tulis audio ke folder antrian STT dengan pola tulis-lalu-rename.

    Mengembalikan path akhir. Lihat ``_RECORDING_TMP_SUFFIX`` untuk alasan kenapa
    penulisannya tidak boleh langsung ke nama akhir.
    """
    os.makedirs(directory, exist_ok=True)
    final_path = os.path.join(directory, os.path.basename(filename))
    tmp_path = final_path + _RECORDING_TMP_SUFFIX
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return final_path



@router.post("/upload_audio", response_model=ResultCreateResponse)
def upload_audio(
    files: list[UploadFile] = File(...),
    campaign: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Template endpoint for audio upload (mirrors ``upload_transcript``).

    Stores the raw audio files in the ``audio`` bucket and creates a ``pending``
    result. NOTE: there is no speech-to-text / processing pipeline yet, so this
    endpoint only persists the upload. Wire the transcription task at the marked
    TODO below once the worker step exists.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimal satu file audio diperlukan",
        )

    # Validasi SEBELUM apa pun ditulis. Dibatasi ke format yang diawasi producer
    # antrian STT, bukan seluruh AUDIO_CONTENT_TYPES: file di luar itu tidak akan
    # pernah diproses, jadi lebih baik ditolak terang-terangan.
    for f in files:
        ensure_vtt_supported_audio(f.filename)

    # Campaign must exist and be active.
    if crud.get_active_campaign(db, campaign) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Campaign '{campaign}' tidak ditemukan atau tidak aktif",
        )

    source_files = [f.filename for f in files]
    result = crud.create_result(
        db,
        campaign=campaign,
        source_files=source_files,
        num_calls=len(files),
        transcript_path=None,
        uploaded_by_username=getattr(current_user, "username", None),
        uploaded_by_role=getattr(current_user, "role", None),
    )
    result_id = str(result.id)

    # Upload each audio file to audio/{result_id}/{original_filename}
    settings = get_settings()
    client = get_minio()
    for f in files:
        data = f.file.read()
        ext = _ext_of(f.filename)
        object_name = f"{result_id}/{f.filename}"
        client.put_object(
            settings.minio_bucket_audio,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=AUDIO_CONTENT_TYPES.get(ext, "application/octet-stream"),
        )
        # Bucket S3 adalah ARSIP; yang memicu pemrosesan adalah berkas di folder
        # antrian. Nama dipakai apa adanya dan DATAR (tidak di-nest dalam
        # {result_id}/) karena producer memindai WATCH_DIR secara non-rekursif dan
        # hilirnya mengenali tiket dari pola <customer_id>_<timestamp>.
        try:
            write_audio_to_recording_dir(settings.audio_recording_dir, f.filename, data)
        except Exception as exc:
            # Sengaja TIDAK ditelan: kalau langkah ini gagal, audio hanya
            # mengendap di S3 dan tidak akan pernah ditranskrip — kegagalan yang
            # menyamar jadi sukses.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Audio '{f.filename}' tersimpan di storage tapi GAGAL ditulis "
                    f"ke folder antrian STT ({settings.audio_recording_dir}): {exc}"
                ),
            ) from exc

    # Record the storage prefix.
    result.transcript_path = f"{result_id}/"
    db.commit()

    # TODO: enqueue the audio -> transcript -> evaluation pipeline once it exists,
    # e.g. celery_app.send_task("worker.tasks.process_audio.process_audio", args=[result_id]).
    # The result stays "pending" until that task is implemented.

    return ResultCreateResponse(result_id=result_id, status="pending")


def _customer_id_from_files(source_files):
    """Customer/session ID = prefix before the first ``_`` of the first source file."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]


def _appeal_history_entry(a):
    """Serialize an appeal ORM row into a plain dict for the Error Code table."""
    return {
        "id": a.id,
        "approval_status": a.approval_status,
        "qc_reason": a.qc_reason,
        "qc_evidence": a.qc_evidence,
        "qc_ticket_id": a.qc_ticket_id,
        "qc_reference_value": a.qc_reference_value,
        "qc_extracted_value": a.qc_extracted_value,
        "qc_new_error_code": getattr(a, "qc_new_error_code", None),
        "appeal_kind": getattr(a, "appeal_kind", "remove"),
        "add_source": getattr(a, "add_source", None),
        "origin": getattr(a, "origin", "qc"),
        "ai_sumber": a.ai_sumber,
        "ai_risk_base": a.ai_risk_base,
        "ai_details_error": a.ai_details_error,
        "ai_reason": a.ai_reason,
        "ai_evidence": a.ai_evidence,
        "ai_ticket_id": a.ai_ticket_id,
        "requested_by_username": a.requested_by_username,
        "requested_at": a.requested_at.isoformat() if a.requested_at else None,
        "tl_qc_status": getattr(a, "tl_qc_status", "pending"),
        "tl_qc_username": getattr(a, "tl_qc_username", None),
        "tl_qc_reviewed_at": a.tl_qc_reviewed_at.isoformat() if getattr(a, "tl_qc_reviewed_at", None) else None,
        "tl_qc_comment": getattr(a, "tl_qc_comment", None),
        "reviewed_by_username": a.reviewed_by_username,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "review_comment": getattr(a, "review_comment", None),
    }


def _with_error_code_table(result_json, is_new_joiner: bool = False, appeals=None,
                           doc_overdue: bool = False, documents=(), doc_status=None):
    """Return a shallow copy of result_json with evaluation.error_code_table
    computed by the shared single-source-of-truth builder (so the dashboard
    renders the same grouped table the XLSX export uses).

    For a new-joiner submission, each row's Risk Base ``L``/``M`` is softened to
    ``N`` (the qc / SPQ Head Error Code table reads ``risk_base``).

    ``appeals`` (Error Code banding rows for this result) drive two things:
    approved appeals are applied to the evaluation first (flipping the linked
    scorecard item to SESUAI, so the appealed error row disappears and the score
    lifts), and each remaining row is annotated with its latest appeal status +
    full history for the QC "Manual Check" / SPQ Head "Review Banding" columns.

    ``doc_overdue`` — dokumen pendukung yang diminta belum diunggah DAN tenggat H+2
    sudah lewat: menambahkan baris B09 ke tabel. ``documents``
    (``[(doc_type, ocr_json), ...]``) menambahkan C03 untuk slot yang isinya jenis
    dokumen keliru. Keduanya meniru agregasi statistik
    (``compliance.stats_aggregate._error_code_rows``) dan harus sepakat dengannya,
    karena QC membaca tabel ini untuk menjelaskan angka di Stats."""
    if not isinstance(result_json, dict):
        return result_json
    evaluation = result_json.get("evaluation")
    if not isinstance(evaluation, dict):
        return result_json
    appeals = appeals or []
    approved = approved_appeals_only(appeals)
    # 'change' bandings to a deduction-bearing code keep their deduction (relabel
    # only); every other approved remove/change banding flips the item/field to lift
    # the score. 'add' bandings are handled separately (they lower the score).
    flip = [a for a in appeals_that_flip(approved) if _appeal_kind(a) != "add"]
    # Zona abu-abu ditegakkan di kode, sebelum banding & skor dihitung.
    evaluation = normalize_static_verification(evaluation)
    # Baris verifikasi dinamis tanpa dua sisi pembanding (Ascend/transkrip kosong)
    # turun ke SKIPPED_NULL, bukan MISMATCH — tidak menerbitkan B17.
    evaluation = normalize_dynamic_verification(evaluation)
    # Status dokumennya menyusul: PENDING selama tenggat H+2 berjalan, MISMATCH bila
    # terlewat tanpa unggah (lihat ``error_codes.apply_static_document_status``).
    if doc_status is not None:
        evaluation = apply_static_document_status(evaluation, doc_status[0], doc_status[1])
        # Sisi cashline menyusul: baris yang menunggu cover buku tabungan menjadi
        # PENDING selama tenggat H+2, agar jalur dokumennya tidak terpotong.
        evaluation = apply_cashline_document_status(evaluation, doc_status[0], doc_status[1])
    evaluation = apply_approved_appeals(evaluation, flip)
    evaluation = apply_approved_card_holder_appeals(evaluation, flip)
    evaluation = apply_approved_cashline_appeals(evaluation, flip)
    evaluation = apply_approved_critical_compliance_appeals(evaluation, flip)
    # 'add' bandings: attach a NEW error to an existing item/field and LOWER the score
    # (source 'others' is display-only, injected into the table below).
    added = added_appeals_only(appeals)
    evaluation = apply_added_score_appeals(evaluation, added)
    # Recompute the aggregate score fields from the appeal-adjusted evaluation so the
    # detail response is self-consistent (the apply_* helpers only lift the frozen
    # verification/critical penalties; ai_score_phase_2/phase_3/ai_status stay at the
    # original LLM values otherwise). Mirrors api/routers/stats.py::list_results.
    phase2 = scorecard_score(evaluation)
    if phase2 is not None:
        # Rumus phase3 hidup di SATU tempat (termasuk iris 10% non-tolerable) —
        # lihat compliance.scoring.phase3_score.
        phase3 = phase3_score(evaluation)
        status_val = base_ai_status(evaluation)
        if status_val == "PASS" and has_blocking_intolerable_item(evaluation):
            status_val = "FAIL"
        evaluation = {
            **evaluation,
            # Daftar SEMUA item yang mengebom skor — kritis (25%) DAN non-tolerable
            # lain (10%) — supaya panel Critical Compliance Check / kolom SCOREBOMB
            # menampilkan seluruh potongan, bukan hanya yang kritis.
            "score_bomb_items": score_bomb_items(evaluation),
            "ai_score_non_tolerable": non_tolerable_bomb(evaluation),
            "ai_score_phase_2": phase2,
            "ai_score_phase_3": int(phase3) if phase3 == int(phase3) else phase3,
            "ai_status": status_val,
        }
    # Tampilan: B16 & B17-dinamis yang berulang dilebur jadi satu baris beralasan
    # gabungan (31 Agustus 2026). Dilakukan di sini, bukan di dalam builder, supaya
    # hitungan risk base tidak ikut mengecil — lihat merge_dynamic_verification_rows.
    table = merge_dynamic_verification_rows(build_error_code_table(evaluation))
    doc_rows = document_error_code_rows(
        missing=bool(doc_overdue),
        missing_labels=doc_requirement_labels(result_json) if doc_overdue else (),
        wrong_type=wrong_document_types(documents),
    )
    if doc_rows:
        table = table + doc_rows
    # Inject display rows for 'add' bandings (pending awaiting review + approved),
    # keyed by their master code so the annotation below attaches their review state.
    table = inject_added_rows(table, added_appeals_visible(appeals))
    if is_new_joiner:
        table = override_risk_base_for_new_joiner(table)
    table = _annotate_appeals(table, appeals)
    # Relabel/inject/drop rows for approved 'change'/'remove' bandings (after
    # annotation so each row keeps its appeal metadata under the original code).
    table = relabel_error_table(table, [a for a in approved if _appeal_kind(a) != "add"])
    evaluation = {**evaluation, "error_code_table": table}
    # One sentence per failed critical item, computed here so every surface renders
    # the same wording (and the static verification items say WHY they failed).
    evaluation = annotate_critical_compliance_reasons(evaluation)
    # Ringkasan Kategori is derived from the scorecard rather than trusted from the
    # LLM's own block, which can contradict it (see derive_category_summary).
    evaluation = derive_category_summary(evaluation)
    return {**result_json, "evaluation": evaluation}


def _annotate_appeals(table, appeals):
    """Attach appeal state to each Error Code row. Every row is manual-checkable
    (banding may REMOVE or CHANGE the code); ``appeal`` carries latest status +
    history for the QC Manual Check / TL QC / SPQ Head columns."""
    # Group appeals by (error_code, item_code), oldest-first (input order).
    by_row = {}
    for a in appeals:
        by_row.setdefault((a.error_code, a.item_code), []).append(a)
    annotated = []
    for row in table:
        item_code = row.get("item_code") or ""
        # Every Error Code row can be manual-checked now.
        row = {**row, "appealable": True}
        matched = by_row.get((row.get("error_code"), item_code))
        if matched:
            latest = matched[-1]
            row["appeal"] = {
                "latest_id": latest.id,
                "latest_status": latest.approval_status,
                "tl_qc_status": getattr(latest, "tl_qc_status", "pending"),
                "tl_qc_username": getattr(latest, "tl_qc_username", None),
                "effective_status": effective_appeal_status(latest),
                "requested_by_username": latest.requested_by_username,
                "history": [_appeal_history_entry(a) for a in matched],
            }
        else:
            row["appeal"] = None
        annotated.append(row)
    return annotated


@router.get("/result/{result_id}", response_model=ResultResponse)
def get_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_evaluation_detail_user),
):
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result tidak ditemukan",
        )
    # Cakupan tiket, bukan sekadar capability: tanpa ini seluruh evaluasi (skor,
    # error code, isi percakapan) satu tiket terbuka lewat result_id-nya saja untuk
    # siapa pun yang punya RESULTS_EVALUATION_DETAIL — termasuk QC yang tiketnya
    # tidak di-assign dan role ber-``data_scope: all`` yang dipersempit ke satu
    # campaign. Daftar Results/Transcripts sudah ter-scope, halaman detailnya belum.
    ensure_can_view_result(db, current_user, result)

    if result.status == "done":

        data = crud.get_result_data(db, result_id)
        # New-joiner check softens Risk Base L/M -> N in the Error Code table.
        cid = _customer_id_from_files(result.source_files)
        cashline_row = crud.get_tms_cashline_by_result_id(db, cid) if cid else None
        is_new_joiner = new_joiner_info(cashline_row, db)["is_new_joiner"]
        appeals = crud.error_code_appeals_for_result(db, result_id)
        # B09 terbit hanya kalau dokumen yang diminta belum ada DAN tenggat H+2 sudah
        # lewat — dihitung dengan bahan yang sama dengan daftar Results & Stats.
        raw_json = data.result_json if data else None
        # ``get_tms_cashline_by_result_id`` mengembalikan dict ber-key nama kolom CSV,
        # BUKAN objek ORM — jadi submit_time diambil dengan .get(), bukan atribut.
        submit_time = cashline_row.get("submit_time") if cashline_row else None
        doc_overdue = bool(
            _missing_docs_map(db, [result], {str(result.id): raw_json}).get(str(result.id))
            and _doc_sla_expired(submit_time, datetime.now())
        )
        result_json = _with_error_code_table(
            raw_json, is_new_joiner, appeals, doc_overdue,
            crud.document_ocr_by_result(db, [str(result.id)]).get(str(result.id), ()),
            document_status_map(db, [result]).get(str(result.id)),
        )

        return ResultResponse(
            result_id=result_id,
            status=result.status,
            result=result_json,
        )

    if result.status == "failed":
        return ResultResponse(
            result_id=result_id,
            status=result.status,
            error=result.error_message,
        )

    # pending / processing
    return ResultResponse(result_id=result_id, status=result.status)


@router.get("/list_transcripts", response_model=TranscriptListResponse)
def list_transcripts(
    status: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None, description="Filter Approve/Reject: PASS | FAIL"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List transcript PDFs (one row per PDF, not per ticket), DALAM CAKUPAN role.

    Cakupannya sama persis dengan menu Results (``scoped_customer_ids``): QC hanya
    melihat transkrip tiket yang di-assign kepadanya, sisi sales hanya tiket agent di
    bawahnya, QC Support hanya tiket complaint-nya; TL QC / SPQ Head / Admin melihat
    semuanya. Sebelumnya endpoint ini TIDAK ter-scope sama sekali — seorang QC dengan
    6 tiket tetap melihat 223 transkrip milik seluruh organisasi.

    Termasuk pembatasan CAMPAIGN role: sejak 12 Agustus 2026 ``scoped_customer_ids``
    ikut mengiris dengan campaign yang boleh dilihat, jadi role bertag campaign tidak
    lagi melihat transkrip campaign lain di sini (dulu 217 transkrip cashline tetap
    terbuka untuk role yang tag-nya CECC)."""
    if not has_perm(db, current_user, MENU_TRANSCRIPTS):
        # 403 ditulis sebagai angka, BUKAN status.HTTP_403_FORBIDDEN: parameter query
        # ``status`` di atas menutupi modul ``status`` milik FastAPI, sehingga atribut
        # itu dibaca dari None dan endpoint balas 500 alih-alih 403.
        raise HTTPException(status_code=403, detail="Akses ditolak")
    # Cakupan qc_support_own: himpunan terisolasi (hanya upload-annya sendiri);
    # role lain justru mengecualikannya.
    iso = ({"uploaded_by_role": "qc_support"}
           if data_scope_for(db, current_user) == SCOPE_QC_SUPPORT_OWN
           else {"exclude_uploaded_by_role": "qc_support"})
    items, total = crud.list_transcripts(
        db, status=status, campaign=campaign, ticket_id=ticket_id,
        ai_status=ai_status, page=page, limit=limit,
        customer_ids=scoped_customer_ids(db, current_user), **iso,
    )
    return TranscriptListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/transcript_pdf/{result_id}")
def transcript_pdf(
    result_id: str,
    filename: str = Query(..., description="Nama file PDF transkrip"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Stream a single transcript PDF from MinIO for the dashboard PDF viewer.

    The filename must belong to the result's ``source_files`` (guards against
    arbitrary object access / path traversal), DAN tiketnya harus berada dalam
    cakupan pemanggil — menyaring daftarnya saja tidak cukup: tanpa penjagaan di
    sini, isi transkrip tiket mana pun tetap bisa diambil dengan menebak
    ``result_id``, sehingga cakupan menu Transcripts hanya berlaku di tampilan."""
    result = crud.get_result(db, result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result tidak ditemukan")
    ensure_can_view_result(db, current_user, result)

    if filename not in (result.source_files or []):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' bukan bagian dari result ini",
        )

    settings = get_settings()
    client = get_minio()
    object_name = f"{result_id}/{filename}"
    try:
        response = client.get_object(settings.minio_bucket_transcripts, object_name)
        data = response.read()
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF tidak ditemukan di storage")
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

    # Source PDFs are generated externally (ReportLab) with /Title = "untitled", which
    # the browser's embedded PDF viewer shows as the document name. Overwrite /Title
    # with the real filename so the viewer shows a meaningful name (works for existing
    # tickets too — no re-upload). Best-effort: on any failure, stream the original.
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(data))
        writer = PdfWriter(clone_from=reader)
        writer.add_metadata({"/Title": filename})
        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()
    except Exception:
        pass

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/download_transcript/{transcript_id}")
def download_transcript(
    transcript_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Download 1 PDF transkrip asli berdasarkan ID nama file (stem).

    Contoh: ``GET /download_transcript/061058ecB3_20260612171830`` mengunduh
    ``061058ecB3_20260612171830.pdf`` dari MinIO sebagai attachment.

    Dijaga cakupan yang sama dengan ``transcript_pdf``: nama berkasnya sendiri sudah
    memuat ticket id, jadi tanpa penjagaan ini transkrip tiket mana pun bisa diunduh
    hanya dengan menyusun namanya.
    """
    filename = (
        transcript_id
        if transcript_id.lower().endswith(".pdf")
        else f"{transcript_id}.pdf"
    )

    result = crud.get_result_by_source_file(db, filename)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript '{filename}' tidak ditemukan",
        )
    ensure_can_view_result(db, current_user, result)

    settings = get_settings()
    client = get_minio()
    object_name = f"{result.id}/{filename}"
    try:
        response = client.get_object(settings.minio_bucket_transcripts, object_name)
        data = response.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF tidak ditemukan di storage",
        )
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
