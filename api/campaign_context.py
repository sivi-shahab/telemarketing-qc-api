"""Pemetaan campaign App B -> field ``context`` App C, untuk /tickets-daily.

Halaman Recording Tickets dan Assign Ticket menampilkan baris dari App C
(``/tickets-daily``), bukan dari tabel ``results`` App B. Pembatasan campaign
milik RBAC (``api.rbac.effective_campaigns_for``) berbicara dalam NAMA campaign
App B (``Cashline``, ``Collection``), sedangkan baris App C membawa KODE campaign
(``ACT02``, ``CLENTB``, ``LOC26``, ``011``, ``MCS``, ``MP01``, ``NTB002``, ...).
Keduanya kosakata yang berbeda: mencocokkan nama App B ke kolom ``campaign`` App C
tidak pernah menghasilkan apa pun.

Yang dipakai sebagai jembatan adalah field ``context`` App C — ``cashline``,
``ntb``, ``usage``, ``card``, ``alloblast``, ``tbfu`` — karena itulah satu-satunya
kolom App C yang menyatakan JENIS panggilan, bukan kode kampanye operasional.
Kode campaign tidak bisa dipakai walau ingin: pemetaan kode->context bukan 1:1
(pada data 6 tanggal contoh, ``MCS`` muncul sebagai ``cashline``, ``usage``,
``alloblast`` DAN ``ntb``; ``ACT02`` sebagai ``ntb``, ``cashline`` dan ``usage``),
jadi menyaring per kode akan salah untuk sebagian barisnya.

Pemetaannya konfigurasi, bukan konstanta, karena daftar context dimiliki App C dan
bisa bertambah tanpa perubahan di repo ini::

    CAMPAIGN_CONTEXT_MAP=Cashline:cashline,Collection:collection

Beberapa context untuk satu campaign dipisah ``|`` (``Cashline:cashline|usage``).

GAGAL TERTUTUP: campaign App B yang TIDAK ada di peta tidak menyumbang context
apa pun, sehingga login yang dibatasi ke campaign itu tidak melihat satu baris
pun. Ini disengaja dan sejalan dengan ``api.rbac._role_def`` — kalau campaign yang
belum dipetakan malah diloloskan, pembatasan campaign justru membuka seluruh data,
persis bug yang ditutup modul ini.
"""
import os
from typing import Iterable, Optional


def _norm(value) -> str:
    return str(value or "").strip().casefold()


def parse_context_map(raw: Optional[str]) -> dict:
    """``"Cashline:cashline,Collection:collection"`` -> ``{nama: frozenset(context)}``.

    Nama campaign maupun context di-normalkan (trim + casefold) supaya pencocokan
    tidak bergantung pada bagaimana operator mengetik env var-nya. Entri tanpa
    context (``"Collection:"``) dibuang, bukan disimpan sebagai set kosong: dua
    bentuk yang artinya sama hanya menambah cara untuk salah membacanya.
    """
    out: dict = {}
    for chunk in (raw or "").split(","):
        name, sep, contexts = chunk.partition(":")
        if not sep:
            continue
        key = _norm(name)
        values = frozenset(v for v in (_norm(c) for c in contexts.split("|")) if v)
        if not key or not values:
            continue
        out[key] = out.get(key, frozenset()) | values
    return out


# Bawaan yang membuat sistem tetap jalan pada deploy yang belum menyetel env var.
# ``Cashline:cashline`` terverifikasi dari data App C; ``Collection:collection``
# masih PENANDA — per 2026-08-28 App C belum pernah mengirim baris collection sama
# sekali, jadi nilai context-nya harus dikonfirmasi ke pemilik App C dan disetel
# lewat env begitu diketahui.
_DEFAULT_MAP = "Cashline:cashline,Collection:collection"


def context_map_from_env() -> dict:
    """Peta dari env ``CAMPAIGN_CONTEXT_MAP``, dibaca setiap dipanggil.

    Sengaja tidak di-cache: isinya sekecil ini, dan mengubah env lalu me-restart
    proses harus langsung terasa tanpa perlu mengingat ada cache di sini.
    """
    return parse_context_map(os.getenv("CAMPAIGN_CONTEXT_MAP", _DEFAULT_MAP))


def contexts_for(campaigns: Optional[Iterable[str]], mapping: dict) -> Optional[frozenset]:
    """Context yang boleh dilihat, dari daftar campaign ``effective_campaigns_for``.

    ``campaigns is None`` -> ``None`` (TIDAK dibatasi; teruskan semua baris).
    Selain itu sebuah set — termasuk set KOSONG, yang berarti "tidak melihat baris
    apa pun". Perbedaan None vs kosong dipegang sampai ke pemanggil, sama seperti
    di ``api.rbac.effective_campaigns_for``.
    """
    if campaigns is None:
        return None
    allowed: frozenset = frozenset()
    for name in campaigns:
        allowed |= mapping.get(_norm(name), frozenset())
    return allowed


def filter_items(items: Iterable[dict], contexts: Optional[frozenset]) -> list:
    """Saring baris /tickets-daily ke ``contexts``. ``None`` = tanpa penyaringan.

    Baris yang field ``context``-nya kosong DIBUANG saat penyaringan aktif: tidak
    ada bukti baris itu masuk cakupan, dan meloloskannya berarti satu field kosong
    di App C cukup untuk menembus pembatasan campaign.
    """
    if contexts is None:
        return list(items)
    return [it for it in items if _norm(it.get("context")) in contexts]
