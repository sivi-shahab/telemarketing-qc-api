"""Statistics dihitung ulang SEGERA setelah vonis/dokumen berubah (21 Oktober 2026).

Kasus 0704449OzZ: TL QC meng-approve Manual Status PASS pukul 15.01.13 WIB, tetapi
snapshot Statistics baru menyusul 15.03.39 — penghitung ulang terjadwal (tiap 2
menit) antre di belakang 8 evaluasi LLM, dan snapshot ter-cache baru dihitung ulang
saat seseorang membuka halaman (yang pertama tetap menerima angka lama).

``api.stats_refresh`` memasang hook di sesi DB API: commit yang menyentuh Manual
Status / banding / dokumen mengirim ``refresh_stats_snapshot`` ke antrean ``stats``
(dikerjakan worker khusus, lihat docker-compose repo worker). Tanpa DB / broker.
"""
from types import SimpleNamespace

import pytest

from api import stats_refresh


class _Obj:
    pass


@pytest.fixture()
def sent(monkeypatch):
    calls = []

    def fake_send(name, **kw):
        calls.append((name, kw))

    monkeypatch.setattr(stats_refresh, "_send_task", fake_send)
    monkeypatch.setattr(stats_refresh.redis_cache, "acquire", lambda key, ttl_sec: True)
    return calls


def _session(new=(), dirty=(), deleted=()):
    return SimpleNamespace(new=set(new), dirty=set(dirty), deleted=set(deleted), info={})


def test_commit_manual_status_banding_dokumen_memicu_refresh(sent):
    from db.models import Document, ErrorCodeAppeal, QcStatusRequest

    for model, where in ((QcStatusRequest, "new"), (ErrorCodeAppeal, "dirty"),
                         (Document, "deleted")):
        s = _session(**{where: [model.__new__(model)]})
        stats_refresh._after_flush(s, None)
        stats_refresh._after_commit(s)
    assert [c[0] for c in sent] == [stats_refresh.TASK_NAME] * 3
    name, kw = sent[0]
    assert kw["queue"] == stats_refresh.QUEUE == "stats"
    assert kw["countdown"] == stats_refresh.DEBOUNCE_SEC
    assert kw["expires"] > kw["countdown"]


def test_commit_tanpa_data_vonis_tidak_memicu(sent):
    s = _session(new=[_Obj()], dirty=[_Obj()])
    stats_refresh._after_flush(s, None)
    stats_refresh._after_commit(s)
    assert sent == []


def test_rollback_membatalkan_pemicu(sent):
    from db.models import QcStatusRequest

    s = _session(new=[QcStatusRequest.__new__(QcStatusRequest)])
    stats_refresh._after_flush(s, None)
    stats_refresh._after_rollback(s)
    stats_refresh._after_commit(s)
    assert sent == []


def test_rentetan_perubahan_digabung_dalam_jendela_debounce(monkeypatch, sent):
    from db.models import QcStatusRequest

    held = set()

    def acquire(key, ttl_sec):
        if key in held:
            return False
        held.add(key)
        return True

    monkeypatch.setattr(stats_refresh.redis_cache, "acquire", acquire)
    for _ in range(3):
        s = _session(dirty=[QcStatusRequest.__new__(QcStatusRequest)])
        stats_refresh._after_flush(s, None)
        stats_refresh._after_commit(s)
    assert len(sent) == 1


def test_broker_mati_tidak_menggagalkan_request(monkeypatch):
    def boom(name, **kw):
        raise ConnectionError("redis mati")

    monkeypatch.setattr(stats_refresh, "_send_task", boom)
    monkeypatch.setattr(stats_refresh.redis_cache, "acquire", lambda key, ttl_sec: True)
    stats_refresh.request_stats_refresh()  # tidak melempar


def test_hook_terpasang_di_sesi_api(monkeypatch):
    """Sesi dari ``new_session`` (subclass buatan sessionmaker) ikut memanggil hook:
    listener dipasang di kelas dasar ``Session`` dan berlaku untuk turunannya."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from api.dependencies import new_session

    s = new_session()
    try:
        assert isinstance(s, Session)
        assert event.contains(Session, "after_commit", stats_refresh._after_commit)
        assert event.contains(Session, "after_flush", stats_refresh._after_flush)
        fired = []
        monkeypatch.setattr(stats_refresh, "request_stats_refresh", lambda: fired.append(1))
        s.info["stats_refresh_pending"] = True
        s.dispatch.after_commit(s)  # yang dipanggil SQLAlchemy saat commit selesai
        assert fired == [1]
    finally:
        s.close()
