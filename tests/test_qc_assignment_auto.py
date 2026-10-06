"""Pembagian otomatis tiket ke QC (`POST /qc_assignment/auto`).

Dua fungsi murni yang memutuskan segalanya diuji di sini: mana tiket yang berhak ikut
dibagi, dan siapa mendapat apa. Sisanya di router hanyalah membaca DB dan menulis
hasilnya, jadi yang benar-benar bisa salah ada di dua fungsi ini.

Aturan pembagiannya sudah dua kali berganti:

1. Seluruh sisa (`N mod K`) ditumpuk ke QC TERAKHIR. Diganti setelah pembagian
   sungguhan pertama: 281 ticket ke 11 QC membuat satu orang menerima 31 sementara
   yang lain 25, dan karena urutan QC tetap, orang yang sama menanggungnya tiap hari.
2. `split_evenly` — `floor(N/K)` per orang, sisa disebar satu-satu. Adil DALAM satu
   batch, tetapi MENGAWETKAN ketimpangan yang sudah ada: QC yang memegang 40 dan yang
   memegang 10 tetap menerima jumlah yang sama pada batch berikutnya.
3. `split_by_load` (aturan bisnis 4 September 2026) — jatah dihitung dari beban TOTAL
   yang sudah dipegang tiap QC. Akibatnya QC yang baru aktif diborong tiket sampai
   "menyusul" total QC lain, dan QC lama dengan banyak tiket kebagian nol.
4. `qc_auto_assign.distribute_evenly` (2 Oktober 2026, diport dari 4-service@6296b02)
   — merata per MOMEN pembagian di antara QC yang aktif saat itu; beban lama tidak
   dihitung. Selisih dalam satu pembagian paling banyak 1 tiket; antrean dikocok dan
   seri diundi supaya tidak ada yang selalu kebagian tiket tertua/termuda. Aturan yang
   sama dipakai batch terjadwal di worker.

Yang diuji di bawah adalah aturan ke-4. Undiannya diberi `random.Random(seed)` supaya
hasilnya bisa diperiksa, bukan ditebak.
"""
import random

from api.routers.qc_assignment import eligible_tickets
from qc_auto_assign import distribute_evenly


def _by_qc(pairs):
    """[(tiket, qc)] -> {qc: [tiket]}, urutan tiket dipertahankan."""
    out = {}
    for ticket, qc in pairs:
        out.setdefault(qc, []).append(ticket)
    return out


def _counts(pairs):
    return {qc: len(v) for qc, v in _by_qc(pairs).items()}


# --------------------------------------------------------------------------
# distribute_evenly
# --------------------------------------------------------------------------

def test_terbagi_serata_mungkin():
    pairs = distribute_evenly([f"t{i}" for i in range(6)], ["a", "b", "c"], rnd=random.Random(1))
    assert sorted(_counts(pairs).values()) == [2, 2, 2]


def test_sisa_tidak_pernah_menumpuk_lebih_dari_satu():
    for seed in range(5):
        pairs = distribute_evenly([f"t{i}" for i in range(7)], ["a", "b", "c"], rnd=random.Random(seed))
        c = sorted(_counts(pairs).values())
        assert max(c) - min(c) <= 1


def test_semua_qc_aktif_kebagian_tanpa_melihat_beban_lama():
    """Inti aturan ke-4: 8 QC aktif -> 8 QC kebagian. Fungsi ini memang tidak
    menerima beban lama, jadi QC yang sudah berat tetap dapat jatah yang sama."""
    qcs = [f"qc{i}" for i in range(8)]
    pairs = distribute_evenly([f"t{i}" for i in range(16)], qcs, rnd=random.Random(0))
    assert _counts(pairs) == {q: 2 for q in qcs}


def test_seluruh_tiket_terbagi_habis_dan_tidak_ada_yang_kembar():
    tickets = [f"t{i}" for i in range(23)]
    pairs = distribute_evenly(tickets, ["a", "b", "c", "d"], rnd=random.Random(7))
    assert len(pairs) == len(tickets)
    assert sorted(t for t, _ in pairs) == sorted(tickets)


def test_tiket_lebih_sedikit_daripada_qc():
    pairs = distribute_evenly(["t1", "t2"], ["a", "b", "c", "d"], rnd=random.Random(2))
    assert len(pairs) == 2
    assert len(set(qc for _t, qc in pairs)) == 2, "dua QC berbeda, bukan satu orang dua kali"


def test_satu_qc_mengambil_semuanya():
    pairs = distribute_evenly(["t1", "t2", "t3"], ["solo"], rnd=random.Random(0))
    assert _counts(pairs) == {"solo": 3}


def test_tanpa_tiket_atau_tanpa_qc_tidak_menghasilkan_apa_apa():
    assert distribute_evenly([], ["a", "b"]) == []
    assert distribute_evenly(["t1"], []) == []


def test_undiannya_deterministik_untuk_seed_yang_sama():
    a = distribute_evenly([f"t{i}" for i in range(8)], ["x", "y", "z"], rnd=random.Random(42))
    b = distribute_evenly([f"t{i}" for i in range(8)], ["x", "y", "z"], rnd=random.Random(42))
    assert a == b


# --------------------------------------------------------------------------
# eligible_tickets
# --------------------------------------------------------------------------

def test_hanya_tiket_yang_belum_diassign_yang_ikut():
    """Tombolnya tidak boleh mengacak penugasan yang sedang dikerjakan."""
    got = eligible_tickets(["t1", "t2", "t3"], allowed=None, already_assigned={"t2"})

    assert got == ["t1", "t3"]


def test_tiket_di_luar_cakupan_campaign_dibuang():
    """Daftar dari browser tidak dipercaya: cakupan diperiksa ulang di server."""
    got = eligible_tickets(["t1", "t2"], allowed={"t1"}, already_assigned=set())

    assert got == ["t1"]


def test_allowed_none_berarti_tanpa_batas():
    got = eligible_tickets(["t1", "t2"], allowed=None, already_assigned=set())

    assert got == ["t1", "t2"]


def test_cakupan_kosong_berarti_tidak_ada_yang_boleh():
    """Set kosong BUKAN sinonim None — bedanya dijaga sampai ke sini."""
    got = eligible_tickets(["t1", "t2"], allowed=set(), already_assigned=set())

    assert got == []


def test_duplikat_dan_spasi_dirapikan_urutan_dipertahankan():
    got = eligible_tickets([" t1 ", "t2", "t1", ""], allowed=None, already_assigned=set())

    assert got == ["t1", "t2"]


# --------------------------------------------------------------------------
# _auto_assign_pool — SELURUH antrean dalam cakupan, bukan satu halaman
# --------------------------------------------------------------------------

def test_pool_membuang_tiket_yang_sudah_punya_qc(monkeypatch):
    """Pratinjau dan pembagian memakai fungsi yang SAMA, jadi angkanya tidak bisa
    berbeda dari yang benar-benar dibagikan."""
    from api.routers import qc_assignment as qa

    class _R:
        def __init__(self, tid):
            self.source_files = [f"{tid}_1.pdf"]

    class _A:
        def __init__(self, tid):
            self.ticket_id = tid

    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: None)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: None)
    monkeypatch.setattr(qa.crud, "list_results",
                        lambda *a, **k: ([_R("t1"), _R("t2"), _R("t3")], 3))
    monkeypatch.setattr(qa.crud, "list_qc_assignments", lambda db: [_A("t2")])

    ticket_ids, pool = qa._auto_assign_pool(None, object())
    assert ticket_ids == ["t1", "t2", "t3"]
    assert pool == ["t1", "t3"], "t2 sudah punya QC — tidak boleh diacak ulang"


def test_pool_meng_unique_kan_tiket_dua_agent(monkeypatch):
    """Satu ticket id bisa punya lebih dari satu baris Result; assignment-nya per
    TIKET, jadi tiket yang sama tidak boleh menghabiskan jatah dua kali."""
    from api.routers import qc_assignment as qa

    class _R:
        def __init__(self, tid):
            self.source_files = [f"{tid}_1.pdf"]

    monkeypatch.setattr(qa, "effective_campaigns_for", lambda db, u: None)
    monkeypatch.setattr(qa, "scoped_customer_ids", lambda db, u: None)
    monkeypatch.setattr(qa.crud, "list_results", lambda *a, **k: ([_R("t1"), _R("t1")], 2))
    monkeypatch.setattr(qa.crud, "list_qc_assignments", lambda db: [])

    ticket_ids, pool = qa._auto_assign_pool(None, object())
    assert ticket_ids == ["t1"] and pool == ["t1"]
