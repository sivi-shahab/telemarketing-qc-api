"""Melepas assignment QC: tombol "Lepas Semua" dan penghapusan user QC.

1. "Lepas Semua" (``DELETE /qc_assignment``) dulu memakai ``scoped_customer_ids``
   langsung. Untuk SPQ Head / TL QC ber-tag ``Telemarketing`` daftar itu hanya
   berisi tiket yang sudah ada di ``results``, padahal tiket di menu Assign Ticket
   berasal dari App C — jadi assignment-nya tidak pernah ikut terlepas. Sekarang
   memakai ``_assignment_scope``, sama dengan assign / lepas satu tiket.
2. Menghapus user QC (``DELETE /auth/users/{id}``) ikut melepas seluruh tiket yang
   di-assign kepadanya. ``qc_assignments.qc_username`` tidak ber-FK, jadi tanpa ini
   tiketnya tetap tercatat milik QC yang sudah tidak ada: tampil di Assign Ticket,
   tidak ikut Auto Assign, dan tidak dikerjakan siapa pun.
"""
from types import SimpleNamespace

from api import permissions as P
from api.routers import auth
from api.routers import qc_assignment as qa


# --- Lepas Semua -------------------------------------------------------------

_SPQ = SimpleNamespace(username="spq")

def _capture_bulk_unassign(monkeypatch):
    calls = []

    def fake(db, ticket_ids=None, actor_username=None):
        assert actor_username == "spq"
        calls.append(None if ticket_ids is None else set(ticket_ids))
        return 3

    monkeypatch.setattr(qa.crud, "bulk_unassign_tickets", fake)
    return calls


def test_lepas_semua_telemarketing_supervisor_melepas_tiket_app_c(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: ["Telemarketing", "Cashline"])
    monkeypatch.setattr(qa, "data_scope_for", lambda db, u: P.SCOPE_ALL)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: ["resultonly"])
    calls = _capture_bulk_unassign(monkeypatch)

    out = qa.remove_all_assignments(ticket_ids=None, db=object(), current_user=_SPQ)

    # Tanpa batas, seperti Admin — bukan hanya tiket yang kebetulan ada di results.
    assert calls == [None]
    assert out == {"removed": 3}


def test_lepas_semua_collection_supervisor_tetap_dibatasi(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_CONTEXT_MAP", raising=False)
    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: ["Collection"])
    monkeypatch.setattr(qa, "data_scope_for", lambda db, u: P.SCOPE_ALL)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: ["resultonly"])
    calls = _capture_bulk_unassign(monkeypatch)

    qa.remove_all_assignments(ticket_ids=None, db=object(), current_user=_SPQ)

    assert calls == [{"resultonly"}]


# --- Lepas Semua per tanggal (ticket_ids dari tabel) ----------------------------

def test_lepas_semua_hanya_tiket_tanggal_yang_dikirim(monkeypatch):
    """Dashboard mengirim tiket tanggal yang sedang dimuat; hanya itu yang dilepas."""
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: None)
    calls = _capture_bulk_unassign(monkeypatch)

    qa.remove_all_assignments(ticket_ids=[" t1 ", "t2", "t1", ""], db=object(), current_user=_SPQ)

    assert calls == [{"t1", "t2"}]


def test_lepas_semua_per_tanggal_tetap_dibatasi_cakupan(monkeypatch):
    """Daftar dari browser tidak dipercaya: tiket di luar cakupan dibuang."""
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: {"t1"})
    calls = _capture_bulk_unassign(monkeypatch)

    qa.remove_all_assignments(ticket_ids=["t1", "lain"], db=object(), current_user=_SPQ)

    assert calls == [{"t1"}]


def test_lepas_semua_per_tanggal_semua_di_luar_cakupan_tidak_melepas_apa_pun(monkeypatch):
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: {"t1"})
    calls = _capture_bulk_unassign(monkeypatch)

    out = qa.remove_all_assignments(ticket_ids=["lain"], db=object(), current_user=_SPQ)

    # Jangan sampai daftar kosong jatuh menjadi None ("lepas semua baris").
    assert calls == [] and out == {"removed": 0}


# --- Angka di tombol "Lepas Semua" ---------------------------------------------

class _Assign:
    def __init__(self, ticket_id):
        self.ticket_id = ticket_id


def _summary(monkeypatch, scope):
    monkeypatch.setattr(qa, "_auto_assign_pool", lambda db, u: (["resultonly"], []))
    monkeypatch.setattr(qa, "_active_qc_usernames", lambda db: ["qc1"])
    monkeypatch.setattr(qa, "_assignment_scope", lambda db, u: scope)
    monkeypatch.setattr(
        qa.crud, "list_qc_assignments",
        lambda db: [_Assign("resultonly"), _Assign("220229Qxz5"), _Assign("lain")],
    )
    return qa.unassigned_summary(db=object(), current_user=object())


def test_angka_lepas_semua_menghitung_tiket_app_c(monkeypatch):
    """``releasable`` = baris yang akan dihapus ``DELETE /qc_assignment``, bukan
    hitungan berbasis ``results`` (``assigned``) yang tidak memuat tiket App C."""
    out = _summary(monkeypatch, None)
    assert out["releasable"] == 3
    # Kontrak lama tetap: assigned + unassigned == total.
    assert out["assigned"] + out["unassigned"] == out["total"]


def test_angka_lepas_semua_mengikuti_cakupan(monkeypatch):
    out = _summary(monkeypatch, {"220229Qxz5"})
    assert out["releasable"] == 1


# --- Hapus user QC -----------------------------------------------------------

class _Query:
    def __init__(self, session):
        self.session = session

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self.session.user

    def update(self, *_a, **_k):
        return 0


class _Session:
    def __init__(self, user):
        self.user = user
        self.deleted_objs = []
        self.commits = 0

    def query(self, _model):
        return _Query(self)

    def delete(self, obj):
        self.deleted_objs.append(obj)

    def commit(self):
        self.commits += 1


def test_hapus_user_qc_melepas_assignment_nya_dalam_satu_commit(monkeypatch):
    user = SimpleNamespace(id=7, username="qc7", role="qc")
    db = _Session(user)
    calls = []
    monkeypatch.setattr(
        auth.crud, "unassign_tickets_of_qc",
        lambda db, username, actor_username=None, source=None: calls.append(
            (username, actor_username, source)),
    )

    out = auth.delete_user(7, db=db, current_user=SimpleNamespace(id=1, username="spq"))

    assert out["deleted"] is True
    # Event-nya (lihat test_qc_assignment_events) ikut commit yang sama.
    assert calls == [("qc7", "spq", "user_deleted")]
    assert db.deleted_objs == [user]
    assert db.commits == 1
