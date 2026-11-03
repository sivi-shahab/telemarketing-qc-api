"""Puncak memori SATU fungsi Statistics/AI Status di proses baru (3 November 2026).

Dipakai membandingkan kode lama vs baru: jalankan dua kali dengan worktree yang
berbeda (commit prod polos vs commit prod + patch), satu fungsi per proses supaya
puncak RSS (``ru_maxrss``) tidak tercampur. Lihat
docs/PERBAIKAN_MEMORI_API_03112026.md §3.2.

Cara menjalankan (di server docker; HANYA membaca — semua query di dalam satu transaksi
REPEATABLE READ yang di-rollback):

    # 1. Worktree dari commit yang SEDANG JALAN di prod + perubahan yang diuji.
    #    Jangan pakai `main` bila main membawa migrasi yang belum ada di DB prod
    #    (model ORM akan membaca kolom yang belum ada).
    git worktree add --detach /tmp/wt <commit-prod> && git -C /tmp/wt apply <patch>

    # 2. Env dari container API prod (berisi kredensial: hapus sesudahnya).
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' \
        telemarketing-qc-api-api-1 > /tmp/api.env && chmod 600 /tmp/api.env

    # 3. Container sementara dari image API dengan kode worktree di-mount.
    docker run --rm --network container:telemarketing-qc-api-api-1 \
        --env-file /tmp/api.env \
        -v /tmp/wt/core/db:/app/db:ro -v /tmp/wt/core/compliance:/app/compliance:ro \
        -v /tmp/wt/api:/app/api:ro -w /app \
        -v /data/scorecard_v2/telemarketing-qc-api/scripts:/probe:ro \
        --entrypoint python local/qc-api:latest /probe/perf_peak_memory.py <fungsi>   # ai_status_map | stats_snapshot | scoped_overview | failure_reasons

    rm /tmp/api.env; git worktree remove --force /tmp/wt
"""
import resource
import sys
import time

from sqlalchemy.orm import sessionmaker

from api.dependencies import _make_engine, get_settings
from compliance import stats_aggregate as sa
from db.models import Result

engine = _make_engine(get_settings())
conn = engine.connect().execution_options(isolation_level="REPEATABLE READ")
trans = conn.begin()
db = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
done = sa.exclude_hidden_results(db.query(Result).filter(Result.status == "done")).all()
cids = sorted({(r.source_files or [""])[0].split("_", 1)[0] for r in done
               if r.source_files and isinstance(r.source_files[0], str)})
jobs = {
    "ai_status_map": lambda: sa.ai_status_map(db, done),          # Pending Check / filter AI Status
    "stats_snapshot": lambda: sa.compute_stats_snapshot(db),
    "scoped_overview": lambda: sa.compute_scoped_overview(db, cids),
    "failure_reasons": lambda: sa.compute_failure_reasons(db),
}
name = sys.argv[1]
base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
t = time.time()
jobs[name]()
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
print(f"{name:16s} awal={base}MB puncak={peak}MB naik={peak-base}MB {time.time()-t:.1f}s", flush=True)
trans.rollback()
