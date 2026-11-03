"""Uji pembanding Statistics/AI Status: evaluasi UTUH vs SLIM (3 November 2026).

WAJIB dijalankan sebelum menambah field ke ``crud.SLIM_SCORECARD_DROP`` atau
mengubah sebuah fungsi menjadi ``slim=True``: setiap fungsi dijalankan dua kali
(evaluasi utuh lalu slim) atas SELURUH tiket ``done`` prod dan keluarannya
dibandingkan sebagai JSON. Fungsi slim hanya boleh dipakai bila hasilnya SAMA.
Lihat docs/PERBAIKAN_MEMORI_API_03112026.md.

Kandidat field yang diuji ada di ``CANDIDATES``; tambahkan kandidat baru di sana.
mem <kandidat> | mem old  -> ukur kenaikan RSS saat memuat evaluasi semua tiket
(``old`` = pola loop ORM lama, untuk pembanding).

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
        --entrypoint python local/qc-api:latest /probe/perf_slim_equal.py            # uji kesamaan
    #   ... /probe/perf_slim_equal.py mem A_all_text   # ukur pemuatan evaluasi

    rm /tmp/api.env; git worktree remove --force /tmp/wt
"""
import json
import resource
import sys
import time

from sqlalchemy.orm import sessionmaker

from api.dependencies import _make_engine, get_settings
from compliance import stats_aggregate as sa
from db import crud
from db.models import Result, User

CANDIDATES = {
    "none": frozenset(),
    "A_all_text": frozenset({"evidence", "reason", "requirement",
                             "point_of_improvement", "dynamic_verification_detail"}),
    "B_keep_reason_req": frozenset({"evidence", "point_of_improvement",
                                    "dynamic_verification_detail"}),
    "C_keep_evidence": frozenset({"reason", "requirement", "point_of_improvement",
                                  "dynamic_verification_detail"}),
    "D_poi_dyn": frozenset({"point_of_improvement", "dynamic_verification_detail"}),
}


def session():
    engine = _make_engine(get_settings())
    conn = engine.connect().execution_options(isolation_level="REPEATABLE READ")
    trans = conn.begin()
    s = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
    return conn, trans, s


def canon(x):
    return json.dumps(x, sort_keys=True, default=str)


def run_all(db, done, cids, uids, force_slim):
    """force_slim=True: semua pemanggil (termasuk failure reasons) pakai slim."""
    orig = crud.result_json_map
    if force_slim:
        crud.result_json_map = lambda d, ids, slim=False: orig(d, ids, slim=True)
    try:
        out = {}
        jobs = {
            "ai_status_map": lambda: sa.ai_status_map(db, done),
            "scoped_overview": lambda: sa.compute_scoped_overview(db, cids),
            "stats_snapshot": lambda: sa.compute_stats_snapshot(db),
            "timeseries": lambda: sa.compute_ai_status_timeseries(db, None, None, "monthly", None, None),
            "qc_performance": lambda: sa.compute_qc_performance(db),
            "team_agents": lambda: sa.compute_team_agents(db, uids),
            "failure_reasons": lambda: sa.compute_failure_reasons(db),
            "failure_hier": lambda: sa.compute_failure_reasons_hierarchy(db),
        }
        for name, fn in jobs.items():
            t = time.time()
            try:
                out[name] = canon(fn())
            except Exception as exc:  # noqa: BLE001
                out[name] = f"ERROR {type(exc).__name__}: {exc}"
            print(f"   {name:18s} {time.time()-t:6.1f}s", flush=True)
        return out
    finally:
        crud.result_json_map = orig


def equality():
    conn, trans, db = session()
    try:
        done = sa.exclude_hidden_results(db.query(Result).filter(Result.status == "done")).all()
        cids = sorted({(r.source_files or [""])[0].split("_", 1)[0] for r in done
                       if r.source_files and isinstance(r.source_files[0], str)})
        uids = [str(u.id).casefold() for u in db.query(User).all()]
        print(f"done={len(done)} cids={len(cids)} users={len(uids)}", flush=True)
        crud.SLIM_SCORECARD_DROP = frozenset()
        print("baseline (penuh)", flush=True)
        base = run_all(db, done, cids, uids, force_slim=False)
        for name, drop in CANDIDATES.items():
            if name == "none":
                continue
            crud.SLIM_SCORECARD_DROP = drop
            print(f"kandidat {name}", flush=True)
            got = run_all(db, done, cids, uids, force_slim=True)
            for k in base:
                same = base[k] == got[k]
                print(f"  {name:18s} {k:18s} {'SAMA' if same else 'BEDA'}"
                      + ("" if same else f"  base={base[k][:120]!r}"), flush=True)
    finally:
        db.close()
        trans.rollback()
        conn.close()


def mem(cand):
    conn, trans, db = session()
    try:
        done = sa.exclude_hidden_results(db.query(Result).filter(Result.status == "done")).all()
        ids = [str(r.id) for r in done]
        crud.SLIM_SCORECARD_DROP = CANDIDATES.get(cand, frozenset())
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        t = time.time()
        if cand == "old":
            # Pola lama di stats_aggregate: semua versi JSON lewat ORM sekaligus.
            from db.models import ResultData
            m = {}
            for rid, rjson in (db.query(ResultData.result_id, ResultData.result_json)
                               .filter(ResultData.result_id.in_([r.id for r in done]))
                               .order_by(ResultData.created_at.desc()).all()):
                m.setdefault(str(rid), rjson)
        else:
            m = crud.result_json_map(db, ids, slim=cand != "none")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        print(f"mem {cand:18s} n={len(m)} awal={before}MB puncak={peak}MB "
              f"naik={peak-before}MB {time.time()-t:.1f}s", flush=True)
    finally:
        db.close()
        trans.rollback()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "mem":
        mem(sys.argv[2])
    else:
        equality()
