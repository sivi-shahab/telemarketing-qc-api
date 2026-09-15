"""Tabel progres pipeline pada tiket yang masih pending/processing.

Sebelum 14 September 2026 layar hanya menampilkan "Status: processing — hasil belum
tersedia", tanpa rincian, padahal worker sudah punya checkpoint per tahap. Sekarang
``GET /result/{id}`` membawa ``current_stage`` + ``stages``.

Dua hal yang dijaga di sini:

* barisnya hanya terbit saat pending/processing — saat `done` atau `failed`, tabel
  Hasil Scorecard / pesan error sudah menggantikannya, dan mengirim tabel progres di
  situ hanya membingungkan;
* ``current_stage`` adalah checkpoint yang SUDAH selesai, jadi yang ditandai berjalan
  adalah satu sesudahnya (aturannya hidup di ``compliance.processing_stages``).
"""
from api.schemas.result import ProcessingStageInfo, ResultResponse
from compliance.processing_stages import PROCESSING_STAGES, stage_table


def test_respons_pending_membawa_seluruh_tahap():
    r = ResultResponse(
        result_id="r-1", status="processing",
        current_stage="klasifikasi_llm", stages=stage_table("klasifikasi_llm"),
    )
    assert len(r.stages) == len(PROCESSING_STAGES)
    assert all(isinstance(s, ProcessingStageInfo) for s in r.stages)


def test_tahap_berjalan_adalah_SATU_SESUDAH_current_stage():
    r = ResultResponse(
        result_id="r-1", status="processing",
        current_stage="klasifikasi_llm", stages=stage_table("klasifikasi_llm"),
    )
    state = {s.key: s.state for s in r.stages}
    assert state["klasifikasi_llm"] == "selesai"
    assert state["rangkai_transkrip"] == "berjalan"


def test_belum_ada_checkpoint_tahap_pertama_berjalan():
    r = ResultResponse(result_id="r-1", status="pending",
                       current_stage=None, stages=stage_table(None))
    assert r.stages[0].state == "berjalan"
    assert r.current_stage is None


def test_done_dan_failed_tidak_membawa_tabel_progres():
    for st in ("done", "failed"):
        r = ResultResponse(result_id="r-1", status=st)
        assert r.current_stage is None and r.stages is None


def test_label_tahap_ikut_terkirim():
    """Layar merender label, bukan key — kalau kosong barisnya tidak terbaca."""
    r = ResultResponse(result_id="r-1", status="processing",
                       current_stage=None, stages=stage_table(None))
    assert all(s.label.strip() for s in r.stages)
