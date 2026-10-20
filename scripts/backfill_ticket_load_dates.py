"""Isi ulang ``ticket_load_dates`` dari App C untuk rentang tanggal (20 Oktober 2026).

Tabel diisi terus oleh task beat ``sync-ticket-load-dates`` (3 hari terakhir); script
ini untuk data lama, mis. sekali jalan setelah migrasi 0069::

    docker compose exec api python //app/scripts/backfill_ticket_load_dates.py \
        --from 2026-08-01 [--to 2026-10-19]

``--to`` bawaannya hari ini WIB. Aman diulang (upsert).
"""
import argparse
import sys
from datetime import date, timedelta

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/core")

from api.dependencies import new_session  # noqa: E402
from db import crud  # noqa: E402
from services import load_date_sync  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    args = ap.parse_args(argv)
    end = args.end or crud.now_wib().date()
    if args.start > end:
        sys.exit("ERROR: --from lebih besar dari --to")

    dates = [args.start + timedelta(days=i) for i in range((end - args.start).days + 1)]
    db = new_session()
    try:
        result = load_date_sync.sync_dates(db, dates)
    finally:
        db.close()
    for d in dates:
        print(f"{d}: {result[d]}" if d in result else f"{d}: GAGAL (App C)")
    print(f"total: {sum(result.values())} baris, {len(result)}/{len(dates)} tanggal")


if __name__ == "__main__":
    main()
