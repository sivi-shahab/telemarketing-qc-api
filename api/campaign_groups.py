"""Campaign grup ``Telemarketing`` — payung atas semua campaign NON-Collection.

Tabel ``campaigns`` berisi config PENILAIAN per produk (``Cashline`` = prompt,
scorecard, dan KB produk Cashline). Nama config itu tidak cocok dipakai sebagai
cakupan orang: QC, TL QC, dan SPQ Head telemarketing mengurus seluruh produk
telemarketing — Cashline, NTB, dan setiap produk yang muncul di tiket App C
(``Activation CC New``, ``Megapay``, ``Personal Loan``, ``CashLine NTB``, ``LOC
Change Request``, ...). Tag ``Telemarketing`` di tab Assign Role menyatakan itu.

Bukan baris di tabel ``campaigns`` dan tidak pernah tersimpan di
``results.campaign``: ia DIEKSPANSI saat request oleh
``api.rbac.effective_campaigns_for`` menjadi dirinya sendiri + setiap config
non-Collection, sehingga penyaring ``results`` (Results, Stats, Transcripts)
bekerja tanpa perubahan. Untuk baris App C, ``Telemarketing`` dipetakan ke ``*``
(seluruh baris) di ``api.campaign_context``.

"Non-Collection" mengikuti ``COLLECTION_CAMPAIGNS`` — sumber kebenaran yang sama
dengan pemisahan Collection di seluruh sistem.
"""
from compliance.campaign_kind import is_collection

TELEMARKETING = "Telemarketing"


def _norm(name) -> str:
    return str(name or "").strip().casefold()


def is_group(name) -> bool:
    return _norm(name) == _norm(TELEMARKETING)


def expand(names, known_campaigns, collection_campaigns) -> list:
    """``names`` + setiap ``known_campaigns`` non-Collection, bila grupnya ada.

    Urutan dipertahankan dan hasilnya bebas duplikat (case-insensitive). Tanpa
    ``Telemarketing`` di ``names`` daftarnya dikembalikan apa adanya.
    """
    names = list(names or [])
    if not any(is_group(n) for n in names):
        return names
    out, seen = [], set()
    for n in names + [c for c in known_campaigns or [] if not is_collection(c, collection_campaigns)]:
        key = _norm(n)
        if key and key not in seen:
            seen.add(key)
            out.append(n)
    return out


def allowed_set(names) -> set:
    return {_norm(n) for n in names or [] if _norm(n)}


def allows(allowed: set, name, collection_campaigns) -> bool:
    """Apakah ``name`` lolos irisan dengan ``allowed`` (hasil :func:`allowed_set`).

    Grup ``Telemarketing`` meloloskan setiap nama non-Collection — termasuk tag
    roster (mis. ``NTB``) yang tidak punya config campaign sendiri.
    """
    if _norm(name) in allowed:
        return True
    return _norm(TELEMARKETING) in allowed and not is_collection(name, collection_campaigns)


def with_group_option(names) -> list:
    """Pilihan campaign untuk form Assign Role / Manage Role: grup lebih dulu."""
    return [TELEMARKETING] + sorted(n for n in names if not is_group(n))


def members(known_campaigns, collection_campaigns) -> list:
    """Config campaign yang menjadi bagian grup ``Telemarketing`` (urut nama)."""
    return sorted(
        c for c in known_campaigns or []
        if not is_group(c) and not is_collection(c, collection_campaigns)
    )


def tree(known_campaigns, collection_campaigns) -> dict:
    """``{grup: [anggota]}`` untuk form Assign Role / Manage Role, supaya UI bisa
    menampilkan Cashline dkk. sebagai SUBSET Telemarketing, bukan pilihan setara."""
    return {TELEMARKETING: members(known_campaigns, collection_campaigns)}


def normalize(names, collection_campaigns) -> list:
    """Buang anggota yang sudah tercakup grupnya sebelum disimpan.

    ``Telemarketing`` + ``Cashline`` disimpan sebagai ``Telemarketing`` saja —
    menyimpan keduanya tidak menambah cakupan apa pun dan hanya membuat tag orang
    tampak seperti dua hal yang berbeda. ``Cashline`` tanpa grupnya dipertahankan:
    itu pembatasan sengaja ke satu produk.
    """
    names = list(names or [])
    if not any(is_group(n) for n in names):
        return names
    return [n for n in names if is_group(n) or is_collection(n, collection_campaigns)]
