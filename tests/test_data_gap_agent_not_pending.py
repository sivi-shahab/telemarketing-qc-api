"""Agent yang tidak terpetakan di roster sales TIDAK memaksa AI Status PENDING.

Regresi yang dijaga (6 Oktober 2026): ketika roster sales terbaca kosong, SETIAP
tiket membawa kekurangan ``agent`` dan aturan data-gap memaksa semuanya PENDING —
halaman Results tidak berisi satu pun Qualified / Not Qualified. Data agent tidak
dikirim ke LLM, jadi skor dan vetonya tetap sah; kekurangannya cukup dicatat.

Transkrip / TMS / Ascend kosong tetap PENDING: ketiganya acuan evaluasi.
"""
import pytest

import compliance.stats_aggregate as sa
from compliance.stats_aggregate import (
    DATA_GAP_AGENT,
    DATA_GAP_ASCEND,
    DATA_GAP_TMS,
    DATA_GAP_TRANSCRIPT,
    _result_ai_status,
    pending_data_gap,
)


@pytest.fixture()
def verdict(monkeypatch):
    """Evaluasi palsu: skor menentukan ``base``, tanpa veto apa pun."""
    def _set(base):
        monkeypatch.setattr(sa, "_adjusted_evaluation", lambda rj, ap, ds=None: {"x": 1})
        monkeypatch.setattr(sa, "base_ai_status", lambda ev: base)
        monkeypatch.setattr(sa, "has_blocking_intolerable_item", lambda ev: False)
        monkeypatch.setattr(sa, "static_consistency_failures", lambda ev: [])
        monkeypatch.setattr(sa, "has_badword", lambda ev: False)
    return _set


@pytest.mark.parametrize("base", ["PASS", "FAIL"])
def test_agent_gap_keeps_score_verdict(verdict, base):
    verdict(base)
    assert _result_ai_status({}, None, None, data_gap=(DATA_GAP_AGENT,)) == base


@pytest.mark.parametrize("gap", [
    (DATA_GAP_TRANSCRIPT,),
    (DATA_GAP_TMS, DATA_GAP_ASCEND),
    (DATA_GAP_AGENT, DATA_GAP_ASCEND),
])
def test_reference_gaps_still_pending(verdict, gap):
    verdict("PASS")
    assert _result_ai_status({}, None, None, data_gap=gap) == "PENDING"


def test_pending_data_gap_drops_agent_only():
    assert pending_data_gap((DATA_GAP_AGENT,)) == ()
    assert pending_data_gap((DATA_GAP_AGENT, DATA_GAP_ASCEND)) == (DATA_GAP_ASCEND,)
    assert pending_data_gap(None) == ()
