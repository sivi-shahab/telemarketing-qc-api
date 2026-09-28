"""Snapshot Statistics dihitung ulang di LATAR BELAKANG (stale-while-revalidate).

28 September 2026: menghitung ulang snapshot memakan ±6,5 detik (komputasi CPU), dan
terjadi setiap kali signature data berubah — pengguna Stats pertama sesudah ada
perubahan menunggu segitu. Dengan ``session_factory``, ``get_or_build_stats_snapshot``
langsung mengembalikan snapshot lama (versi format SAMA) dan menghitung ulang di
thread dengan sesi DB sendiri. Snapshot yang belum pernah ada, versi format berbeda,
atau ``force=True`` tetap dihitung langsung.

DB sungguhan dalam transaksi yang di-rollback; scope memakai kunci unik per test
supaya tidak menyentuh snapshot produksi.
"""
import uuid

import pytest


@pytest.fixture()
def scope():
    return f"pytest-{uuid.uuid4().hex[:8]}"


def _payload(tag):
    return {"overview": {"tag": tag}}


def _tidak_boleh(*a, **k):
    raise AssertionError("tidak boleh dipanggil")


def test_belum_ada_snapshot_dihitung_langsung(db, scope):
    from db import crud

    out = crud.get_or_build_stats_snapshot(
        db, scope_key=scope, compute_fn=lambda s: _payload("baru"), session_factory=_tidak_boleh,
    )
    assert out["overview"] == {"tag": "baru"}


def test_signature_berubah_sajikan_lama_lalu_hitung_di_latar(db, scope, monkeypatch):
    from db import crud

    crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("lama"))
    sig_baru = crud._stats_signature(db) + "|berubah"
    monkeypatch.setattr(crud, "_stats_signature", lambda s: sig_baru)
    started = []
    monkeypatch.setattr(crud, "_start_snapshot_refresh", lambda *a: started.append(a))

    out = crud.get_or_build_stats_snapshot(
        db, scope_key=scope, compute_fn=_tidak_boleh, session_factory=lambda: db,
    )
    assert out["overview"] == {"tag": "lama"}
    assert len(started) == 1 and started[0][1] == scope and started[0][3] == sig_baru


def test_tanpa_session_factory_perilaku_lama_sinkron(db, scope, monkeypatch):
    from db import crud

    crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("lama"))
    monkeypatch.setattr(crud, "_stats_signature", lambda s: crud_sig + "|berubah")
    crud_sig = "v25"
    out = crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("baru"))
    assert out["overview"] == {"tag": "baru"}


def test_versi_format_berbeda_tetap_dihitung_langsung(db, scope, monkeypatch):
    from db import crud

    crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("lama"))
    monkeypatch.setattr(crud, "_stats_signature", lambda s: "v999|lain")
    out = crud.get_or_build_stats_snapshot(
        db, scope_key=scope, compute_fn=lambda s: _payload("baru"), session_factory=_tidak_boleh,
    )
    assert out["overview"] == {"tag": "baru"}


def test_force_tetap_dihitung_langsung(db, scope):
    from db import crud

    crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("lama"))
    out = crud.get_or_build_stats_snapshot(
        db, force=True, scope_key=scope, compute_fn=lambda s: _payload("baru"),
        session_factory=_tidak_boleh,
    )
    assert out["overview"] == {"tag": "baru"}


def test_tugas_latar_menyimpan_hasil_baru_dengan_sesi_sendiri(db, scope, monkeypatch):
    from db import crud

    crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=lambda s: _payload("lama"))
    sig_baru = crud._stats_signature(db) + "|berubah"
    closed = []

    class _Sesi:  # sesi test yang sama; close() tidak boleh menutup transaksi test
        def __getattr__(self, n):
            return getattr(db, n)

        def close(self):
            closed.append(True)

    crud._refresh_snapshot_job(_Sesi, scope, lambda s: _payload("baru"), sig_baru)

    monkeypatch.setattr(crud, "_stats_signature", lambda s: sig_baru)
    out = crud.get_or_build_stats_snapshot(db, scope_key=scope, compute_fn=_tidak_boleh)
    assert out["overview"] == {"tag": "baru"} and out["_signature"] == sig_baru
    assert closed == [True]


def test_satu_scope_tidak_dihitung_dua_kali_bersamaan(monkeypatch):
    from db import crud

    held, runs = set(), []

    def _acquire(key, ttl_sec):
        if key in held:
            return False
        held.add(key)
        return True

    class _SyncThread:
        def __init__(self, target, args=(), daemon=None, name=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(crud.redis_cache, "acquire", _acquire)
    monkeypatch.setattr(crud.redis_cache, "release", lambda key: None)
    monkeypatch.setattr(crud, "_refresh_snapshot_job", lambda *a: runs.append(a))
    monkeypatch.setattr(crud.threading, "Thread", _SyncThread)

    crud._start_snapshot_refresh(lambda: None, "s1", None, "sig")
    crud._start_snapshot_refresh(lambda: None, "s1", None, "sig")
    assert len(runs) == 1
