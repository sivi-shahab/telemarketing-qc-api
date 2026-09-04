"""Pembagian otomatis tiket ke QC (`POST /qc_assignment/auto`).

Dua fungsi murni yang memutuskan segalanya diuji di sini: mana tiket yang berhak
ikut dibagi, dan siapa mendapat apa. Sisanya di router hanyalah membaca DB dan
menulis hasilnya, jadi yang benar-benar bisa salah ada di dua fungsi ini.

Aturan pembagiannya ditetapkan bersama pemintanya: N Ticket ID dibagi rata ke K
QC aktif, `floor(N/K)` per orang, dan SISA-nya (`N mod K`) diberikan ke QC
TERAKHIR — bukan disebar satu-satu seperti round-robin biasa.
"""
from api.routers.qc_assignment import eligible_tickets, split_evenly


def _by_qc(pairs):
    """[(tiket, qc)] -> {qc: [tiket]}, urutan tiket dipertahankan."""
    out = {}
    for ticket, qc in pairs:
        out.setdefault(qc, []).append(ticket)
    return out


# --------------------------------------------------------------------------
# split_evenly
# --------------------------------------------------------------------------

def test_habis_dibagi_setiap_qc_dapat_sama_banyak():
    pairs = split_evenly(["t1", "t2", "t3", "t4", "t5", "t6"], ["a", "b", "c"])

    assert _by_qc(pairs) == {"a": ["t1", "t2"], "b": ["t3", "t4"], "c": ["t5", "t6"]}


def test_sisa_jatuh_ke_qc_terakhir():
    """7 tiket / 3 QC = 2 per orang, sisa 1 ke QC terakhir — bukan ke QC pertama."""
    pairs = split_evenly(["t1", "t2", "t3", "t4", "t5", "t6", "t7"], ["a", "b", "c"])

    assert _by_qc(pairs) == {"a": ["t1", "t2"], "b": ["t3", "t4"], "c": ["t5", "t6", "t7"]}


def test_sisa_lebih_dari_satu_tetap_utuh_ke_qc_terakhir():
    pairs = split_evenly([f"t{i}" for i in range(1, 12)], ["a", "b", "c", "d"])

    assert [len(v) for v in _by_qc(pairs).values()] == [2, 2, 2, 5]


def test_potongannya_berurutan_bukan_selang_seling():
    """Blok berurutan mengikuti urutan tabel: QC pertama dapat tiket teratas."""
    pairs = split_evenly(["t1", "t2", "t3", "t4"], ["a", "b"])

    assert pairs == [("t1", "a"), ("t2", "a"), ("t3", "b"), ("t4", "b")]


def test_tiket_lebih_sedikit_daripada_qc_dibagi_satu_satu():
    """`floor` = 0 di sini. Kalau aturan sisa diikuti mentah-mentah, ketiga tiket
    menumpuk ke satu orang — kebalikan dari maksud tombolnya."""
    pairs = split_evenly(["t1", "t2", "t3"], ["a", "b", "c", "d", "e"])

    assert pairs == [("t1", "a"), ("t2", "b"), ("t3", "c")]


def test_jumlah_tiket_sama_dengan_jumlah_qc():
    pairs = split_evenly(["t1", "t2", "t3"], ["a", "b", "c"])

    assert pairs == [("t1", "a"), ("t2", "b"), ("t3", "c")]


def test_satu_qc_mengambil_semuanya():
    pairs = split_evenly(["t1", "t2", "t3"], ["solo"])

    assert _by_qc(pairs) == {"solo": ["t1", "t2", "t3"]}


def test_tanpa_tiket_tidak_menghasilkan_apa_apa():
    assert split_evenly([], ["a", "b"]) == []


def test_tanpa_qc_tidak_menghasilkan_apa_apa():
    """Router yang menolak dengan pesan; fungsinya sendiri tidak boleh membagi ke
    ketiadaan (dan tidak boleh melempar ZeroDivisionError)."""
    assert split_evenly(["t1"], []) == []


def test_semua_tiket_terbagi_habis():
    """Penjaga menyeluruh: tidak ada tiket yang hilang atau tergandakan."""
    tickets = [f"t{i}" for i in range(1, 38)]
    pairs = split_evenly(tickets, ["a", "b", "c", "d", "e"])

    assert [t for t, _ in pairs] == tickets


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
