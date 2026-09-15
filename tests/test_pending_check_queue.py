"""Menu "Pending Check" berisi persis satu hal: tiket ber-AI Status = Pending.

Sebelum 3 September 2026 menu ini menyaring ``manual_review_state == "menunggu"``,
yaitu "usulan Manual Status belum diputus ATAU tiket kekurangan dokumen" — dua keadaan
yang tidak sama dengan Pending dan tidak sama satu sama lain. Akibatnya menu bernama
"Pending Check" memuat tiket Qualified maupun Not Qualified, sementara sebagian tiket
yang benar-benar Pending justru tidak ada di dalamnya.

Aturannya sekarang satu kalimat, dan itu yang dikunci di sini. Cabang ini hidup di
dalam ``_resolve_filtered_results`` yang butuh DB, jadi ketergantungan luarnya
di-stub — yang diuji murni aturan pemilihannya, bukan SQL-nya.
"""
import pytest

from api.routers import stats as st


class _Row:
    def __init__(self, rid, status="done"):
        self.id = rid
        self.status = status
        self.source_files = [f"{rid}_1.pdf"]


@pytest.fixture()
def resolver(monkeypatch):
    """``_resolve_filtered_results`` dengan seluruh ketergantungan DB/RBAC di-stub."""
    rows = [_Row("t-pending"), _Row("t-qualified"), _Row("t-notqualified"),
            _Row("t-belum-selesai", status="processing")]
    ai = {"t-pending": "PENDING", "t-qualified": "PASS", "t-notqualified": "FAIL"}

    monkeypatch.setattr(st, "effective_campaigns_for", lambda db, u: None)
    monkeypatch.setattr(st, "_scoped_customer_ids", lambda db, u: None)
    monkeypatch.setattr(st, "agent_ids_for_hierarchy_filter", lambda *a, **k: None)
    monkeypatch.setattr(st, "data_scope_for", lambda db, u: "all")
    monkeypatch.setattr(st, "has_perm", lambda db, u, p: False)
    monkeypatch.setattr(st.crud, "list_results", lambda *a, **k: (rows, len(rows)))
    monkeypatch.setattr(st, "ai_status_map",
                        lambda db, rs: {str(r.id): ai[str(r.id)] for r in rs if str(r.id) in ai})
    # Kalau cabangnya masih memakai jalur lama, stub ini yang akan terpanggil.
    monkeypatch.setattr(st, "manual_review_state",
                        lambda *a, **k: pytest.fail("Pending Check tidak boleh lagi memakai manual_review_state"))
    return lambda **kw: st._resolve_filtered_results(db=None, current_user=object(), **kw)


def test_hanya_tiket_ber_AI_status_pending(resolver):
    rows, total = resolver(manual_status_pending=True)
    assert [str(r.id) for r in rows] == ["t-pending"]
    assert total == 1


def test_qualified_dan_not_qualified_tidak_ikut(resolver):
    rows, _ = resolver(manual_status_pending=True)
    ids = {str(r.id) for r in rows}
    assert "t-qualified" not in ids
    assert "t-notqualified" not in ids


def test_hasil_yang_belum_selesai_dibuang(resolver):
    """AI Status baru ada setelah evaluasi selesai — baris pending/processing tidak
    mungkin cocok dengan nilai mana pun."""
    rows, _ = resolver(manual_status_pending=True)
    assert "t-belum-selesai" not in {str(r.id) for r in rows}
