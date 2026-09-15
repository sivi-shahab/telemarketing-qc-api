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
   yang sudah dipegang tiap QC. Yang paling sedikit dapat lebih dulu, seri diundi, dan
   antreannya dikocok supaya tidak ada yang selalu kebagian tiket tertua/termuda.

Yang diuji di bawah adalah aturan ke-3. Undiannya diberi `random.Random(seed)` supaya
hasilnya bisa diperiksa, bukan ditebak.
"""
import random

from api.routers.qc_assignment import eligible_tickets, split_by_load


def _by_qc(pairs):
    """[(tiket, qc)] -> {qc: [tiket]}, urutan tiket dipertahankan."""
    out = {}
    for ticket, qc in pairs:
        out.setdefault(qc, []).append(ticket)
    return out


def _counts(pairs):
    return {qc: len(v) for qc, v in _by_qc(pairs).items()}


# --------------------------------------------------------------------------
# split_by_load
# --------------------------------------------------------------------------

def test_tanpa_beban_awal_terbagi_serata_mungkin():
    pairs = split_by_load([f"t{i}" for i in range(6)], ["a", "b", "c"], rnd=random.Random(1))
    assert sorted(_counts(pairs).values()) == [2, 2, 2]


def test_sisa_tidak_pernah_menumpuk_lebih_dari_satu():
    pairs = split_by_load([f"t{i}" for i in range(7)], ["a", "b", "c"], rnd=random.Random(1))
    c = sorted(_counts(pairs).values())
    assert max(c) - min(c) <= 1


def test_ketimpangan_yang_SUDAH_ada_dikejar_lebih_dulu():
    """Inti aturan ke-3: yang sudah berat tidak dapat apa-apa sampai yang lain menyusul."""
    pairs = split_by_load(["t1", "t2", "t3"], ["berat", "ringan"],
                          current_load={"berat": 10, "ringan": 7}, rnd=random.Random(0))
    counts = _counts(pairs)
    assert counts.get("ringan") == 3, "yang ringan mengejar dulu"
    assert "berat" not in counts, "yang berat belum boleh dapat tambahan"


def test_setelah_menyusul_pembagiannya_kembali_berselang():
    """Begitu bebannya sama, tambahan berikutnya tersebar, bukan menumpuk."""
    pairs = split_by_load([f"t{i}" for i in range(6)], ["a", "b"],
                          current_load={"a": 2, "b": 0}, rnd=random.Random(3))
    c = _counts(pairs)
    assert c["b"] == 4 and c["a"] == 2, "b mengejar 2 dulu, sisanya dibagi rata"


def test_beban_akhir_selisihnya_tidak_lebih_dari_satu():
    for seed in range(5):
        load = {"a": 9, "b": 3, "c": 5}
        pairs = split_by_load([f"t{i}" for i in range(10)], ["a", "b", "c"],
                              current_load=load, rnd=random.Random(seed))
        akhir = dict(load)
        for _t, qc in pairs:
            akhir[qc] += 1
        assert max(akhir.values()) - min(akhir.values()) <= 1, akhir


def test_qc_tanpa_catatan_beban_dianggap_nol():
    pairs = split_by_load(["t1"], ["a", "baru"], current_load={"a": 5}, rnd=random.Random(0))
    assert _counts(pairs) == {"baru": 1}


def test_seluruh_tiket_terbagi_habis_dan_tidak_ada_yang_kembar():
    tickets = [f"t{i}" for i in range(23)]
    pairs = split_by_load(tickets, ["a", "b", "c", "d"], rnd=random.Random(7))
    assert len(pairs) == len(tickets)
    assert sorted(t for t, _ in pairs) == sorted(tickets)


def test_tiket_lebih_sedikit_daripada_qc():
    pairs = split_by_load(["t1", "t2"], ["a", "b", "c", "d"], rnd=random.Random(2))
    assert len(pairs) == 2
    assert len(set(qc for _t, qc in pairs)) == 2, "dua QC berbeda, bukan satu orang dua kali"


def test_satu_qc_mengambil_semuanya():
    pairs = split_by_load(["t1", "t2", "t3"], ["solo"], rnd=random.Random(0))
    assert _counts(pairs) == {"solo": 3}


def test_tanpa_tiket_atau_tanpa_qc_tidak_menghasilkan_apa_apa():
    assert split_by_load([], ["a", "b"]) == []
    assert split_by_load(["t1"], []) == []


def test_undiannya_deterministik_untuk_seed_yang_sama():
    a = split_by_load([f"t{i}" for i in range(8)], ["x", "y", "z"], rnd=random.Random(42))
    b = split_by_load([f"t{i}" for i in range(8)], ["x", "y", "z"], rnd=random.Random(42))
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
