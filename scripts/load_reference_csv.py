"""Muat ulang data referensi TMS / Ascend dari CSV export ke PostgreSQL.

Tabelnya sendiri dibuat oleh migration 0005; script ini HANYA mengisi data.
Drop CSV baru (mis. ``data_tms_07072026.csv``) lalu jalankan script ini —
tidak perlu bikin revisi alembic baru, karena skemanya tidak berubah.

Jalankan dari dalam container ``api`` (di situ ada koneksi DB-nya)::

    docker compose exec api python //app/scripts/load_reference_csv.py \
        --tms  "//app/csv_bank/data_tms_07072026.csv" \
        --mode replace --yes

Mode:
  append   (default) tambahkan baris CSV ke isi tabel sekarang.
  replace  kosongkan tabel dulu, baru muat CSV. DESTRUKTIF — wajib ``--yes``.

Header CSV dicocokkan dengan kolom tabel sebenarnya (introspeksi, bukan hardcode).
Kolom di CSV yang tidak dikenal tabel akan MENGGAGALKAN proses, bukan diam-diam
dibuang — export yang berubah bentuk lebih baik ketahuan sekarang daripada jadi
kolom kosong yang baru disadari berminggu-minggu kemudian.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, "/app")

import sqlalchemy as sa  # noqa: E402

from api.dependencies import get_db  # noqa: E402

# tabel -> kolom kunci (NOT NULL; baris dengan kunci kosong dilewati)
TARGETS = {
    "tms": ("tms_cashline", "result_id"),
    "ascend": ("ascend_custp", "CUST_LOCAL_NAME"),
}


def table_columns(db, table):
    """Nama kolom tabel sesuai urutan fisiknya, tanpa surrogate ``id``."""
    return [c["name"] for c in sa.inspect(db.bind).get_columns(table) if c["name"] != "id"]


def read_csv(path, delimiter, no_header, columns):
    """Baca CSV jadi (rows, headers).

    ``no_header=True`` dipakai untuk export mentah yang barisnya langsung data
    (mis. dump Ascend dengan pemisah ';'). Nama kolomnya diambil dari URUTAN
    kolom tabel — makanya jumlah field WAJIB sama persis; kalau meleset satu
    saja, semua nilai bergeser ke kolom tetangga tanpa error apa pun.
    """
    if not os.path.isfile(path):
        sys.exit(f"ERROR: file tidak ditemukan: {path}")
    # utf-8-sig: export Windows sering menyisipkan BOM yang bikin nama kolom
    # pertama jadi "﻿result_id" dan gagal dicocokkan dengan kolom tabel.
    with open(path, newline="", encoding="utf-8-sig") as fh:
        if not no_header:
            reader = csv.DictReader(fh, delimiter=delimiter)
            return [dict(r) for r in reader], list(reader.fieldnames or [])

        raw = [r for r in csv.reader(fh, delimiter=delimiter) if any(f.strip() for f in r)]
        if not raw:
            return [], []
        bad = {len(r) for r in raw} - {len(columns)}
        if bad:
            sys.exit(
                f"ERROR: {os.path.basename(path)} tanpa header diharapkan "
                f"{len(columns)} field per baris, tapi ada baris dengan {sorted(bad)}.\n"
                f"       Pemetaan posisional dibatalkan — kolomnya akan bergeser."
            )
        return [dict(zip(columns, r)) for r in raw], list(columns)


def load(db, table, key_col, path, mode, assume_yes, dry_run, delimiter, no_header):
    columns = table_columns(db, table)
    rows, headers = read_csv(path, delimiter, no_header, columns)
    if not rows:
        print(f"  {table}: CSV kosong, dilewati.")
        return

    if no_header:
        # Pemetaannya ditebak dari posisi, jadi cetak baris pertama supaya bisa
        # diperiksa mata sebelum commit — inilah gunanya --dry-run di sini.
        print(f"  pemetaan posisional {os.path.basename(path)} (baris pertama):")
        for i, h in enumerate(headers):
            v = str(rows[0].get(h) or "").strip()
            if v:
                print(f"    {i:3} {h:28} = {v[:44]!r}")

    cols = set(columns) | {"id"}
    unknown = [h for h in headers if h not in cols]
    if unknown:
        sys.exit(
            f"ERROR: {os.path.basename(path)} punya kolom yang tidak ada di "
            f"tabel {table}: {unknown}\n"
            f"       Kalau export-nya memang berubah, skemanya perlu migration "
            f"baru dulu."
        )
    missing = sorted(cols - set(headers) - {"id"})
    if missing:
        print(f"  catatan: {len(missing)} kolom tabel tidak ada di CSV, akan NULL: {missing[:8]}"
              + (" ..." if len(missing) > 8 else ""))

    if key_col not in headers:
        sys.exit(f"ERROR: kolom kunci '{key_col}' tidak ada di {os.path.basename(path)}")

    payload = [r for r in rows if str(r.get(key_col) or "").strip()]
    skipped = len(rows) - len(payload)
    if skipped:
        print(f"  catatan: {skipped} baris dilewati karena '{key_col}' kosong.")
    if not payload:
        print(f"  {table}: tidak ada baris valid, dilewati.")
        return

    before = db.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

    if mode == "replace":
        if before and not assume_yes and not dry_run:
            sys.exit(
                f"ERROR: mode replace akan menghapus {before} baris dari {table}. "
                f"Tambahkan --yes kalau memang itu yang diinginkan."
            )
        db.execute(sa.text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY'))

    quoted = ", ".join(f'"{h}"' for h in headers)
    binds = ", ".join(f":{i}" for i in range(len(headers)))
    stmt = sa.text(f'INSERT INTO "{table}" ({quoted}) VALUES ({binds})')
    db.execute(stmt, [{str(i): r.get(h) for i, h in enumerate(headers)} for r in payload])

    # Hitung SEBELUM commit/rollback: di dalam transaksi yang sama, angka ini
    # sudah mencerminkan hasil insert, jadi dry-run melaporkan hasil sebenarnya.
    after = db.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
    if dry_run:
        db.rollback()
        print(f"  {table}: {before} -> {after} baris (DRY RUN, dibatalkan)")
    else:
        db.commit()
        print(f"  {table}: {before} -> {after} baris (+{len(payload)} dimuat, mode={mode})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tms", help="path CSV export TMS/CASHLINE")
    ap.add_argument("--ascend", help="path CSV export Ascend/CUSTP")
    ap.add_argument("--mode", choices=["append", "replace"], default="append")
    ap.add_argument("--yes", action="store_true",
                    help="konfirmasi TRUNCATE saat --mode replace")
    ap.add_argument("--dry-run", action="store_true",
                    help="jalankan penuh lalu ROLLBACK — untuk validasi export baru")
    ap.add_argument("--tms-delimiter", default=",")
    ap.add_argument("--ascend-delimiter", default=",",
                    help="dump Ascend mentah biasanya pakai ';'")
    ap.add_argument("--tms-no-header", action="store_true")
    ap.add_argument("--ascend-no-header", action="store_true",
                    help="baris pertama langsung data; kolom dipetakan dari urutan tabel")
    args = ap.parse_args()

    if not args.tms and not args.ascend:
        ap.error("minimal salah satu dari --tms / --ascend harus diisi")

    db = next(get_db())
    try:
        print(f"Memuat data referensi (mode={args.mode}):")
        opts = {
            "tms": (args.tms, args.tms_delimiter, args.tms_no_header),
            "ascend": (args.ascend, args.ascend_delimiter, args.ascend_no_header),
        }
        for flag, (path, delim, no_hdr) in opts.items():
            if not path:
                continue
            table, key_col = TARGETS[flag]
            load(db, table, key_col, path, args.mode, args.yes, args.dry_run, delim, no_hdr)
        print("Selesai.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
