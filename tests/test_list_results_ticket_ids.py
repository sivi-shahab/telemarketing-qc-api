"""Parameter ``ticket_ids`` di ``/list_results`` — pengayaan per-tiket, bukan per-tabel.

Menu Assign Ticket butuh kolom lokal (Checked At / Approved At / QC ditugaskan)
untuk ticket yang TAMPIL di tabelnya saja. Sebelum parameter ini ada, halaman itu
menarik ``/list_results`` halaman demi halaman TANPA satu pun filter — sampai
10.000 baris — hanya untuk memungut beberapa puluh di antaranya.

``ticket_ids`` MEMPERSEMPIT, tidak pernah memperlebar: ia diiriskan dengan cakupan
yang sudah dihitung RBAC, persis seperti filter hierarki AM/TL/TLO.
"""
import pytest

from api.routers import stats as st


class _Row:
    def __init__(self, rid):
        self.id = rid
        self.status = "done"
        self.source_files = [f"{rid}_1.pdf"]


@pytest.fixture()
def resolver(monkeypatch):
    """``_resolve_filtered_results`` dengan ketergantungan DB/RBAC di-stub.

    ``captured`` menampung kwargs yang diteruskan ke ``crud.list_results`` — yang
    diuji adalah cakupan yang DIMINTA ke SQL, karena di situlah penghematannya.
    """
    captured = {}

    def _fake_list_results(db, **kw):
        captured.clear()
        captured.update(kw)
        return [_Row("T1")], 1

    monkeypatch.setattr(st, "effective_campaigns_for", lambda db, u: None)
    monkeypatch.setattr(st, "_scoped_customer_ids", lambda db, u: None)
    monkeypatch.setattr(st, "agent_ids_for_hierarchy_filter", lambda *a, **k: None)
    monkeypatch.setattr(st, "data_scope_for", lambda db, u: "all")
    monkeypatch.setattr(st, "has_perm", lambda db, u, p: False)
    monkeypatch.setattr(st.crud, "list_results", _fake_list_results)

    def _call(**kw):
        rows, total = st._resolve_filtered_results(db=None, current_user=object(), **kw)
        return rows, total, captured

    return _call


def test_ticket_ids_diteruskan_sebagai_customer_ids(resolver):
    _, _, captured = resolver(ticket_ids=["T1", "T2"])
    assert sorted(captured["customer_ids"]) == ["T1", "T2"]


def test_tanpa_ticket_ids_cakupan_tidak_berubah(resolver):
    _, _, captured = resolver()
    assert captured["customer_ids"] is None


def test_ticket_ids_diiriskan_dengan_cakupan_role(monkeypatch, resolver):
    """Minta ticket di luar cakupan tidak boleh melebarkan hasil."""
    monkeypatch.setattr(st, "_scoped_customer_ids", lambda db, u: ["T1", "T9"])
    _, _, captured = resolver(ticket_ids=["T1", "T2"])
    assert sorted(captured["customer_ids"]) == ["T1"]


def test_ticket_ids_kosong_berarti_tidak_ada_hasil(resolver):
    """List kosong = "tidak ada id yang diminta", bukan "tanpa batas"."""
    rows, total, _ = resolver(ticket_ids=[])
    assert (rows, total) == ([], 0)
