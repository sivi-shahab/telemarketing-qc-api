"""Konvensi waktu: SIMPAN UTC (naive), TAMPILKAN WIB.

Kode core (``func.timezone('Asia/Jakarta', func.timezone('UTC', uploaded_at))``,
``_wib_month``) dan dashboard (menambah ``'Z'`` lalu merender Asia/Jakarta) sudah
memakai konvensi ini. Yang melanggarnya adalah Postgres produksi: ``TimeZone =
Asia/Jakarta``, sehingga ``server_default=func.now()`` menulis WIB. Akibatnya
``uploaded_at`` dikonversi dua kali (upload sesudah 17:00 WIB masuk hari berikutnya)
dan tampil 7 jam maju di dashboard (28 September 2026).

Perbaikannya ada dua: sesi DB api/worker dipaksa ``timezone=UTC``, dan migrasi 0060
menggeser −7 jam kolom yang selama ini terisi WIB. Test migrasi hanya memeriksa
baris sintetis tahun 2000 dan seluruhnya berjalan dalam transaksi yang di-rollback.
"""
import importlib.util
import pathlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

H7 = timedelta(hours=7)


def _utcnow():
    return datetime.utcnow()


def test_sesi_db_menulis_now_dalam_utc(db):
    db_now = db.execute(text("select now()::timestamp")).scalar()
    assert abs(db_now - _utcnow()) < timedelta(minutes=2)


def test_uploaded_at_default_tersimpan_utc(db):
    from db.models import Result

    row = Result(id=uuid.uuid4(), campaign="Cashline", status="pending")
    db.add(row)
    db.flush()
    db.refresh(row)
    assert abs(row.uploaded_at - _utcnow()) < timedelta(minutes=2)


def _migration():
    path = next(pathlib.Path(__file__).resolve().parents[1]
                .glob("db/migrations/versions/0060_*.py"))
    spec = importlib.util.spec_from_file_location("m0060", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(db, statements):
    for sql in statements:
        db.execute(text(sql))
    db.flush()
    db.expire_all()


def test_migrasi_0060_menggeser_kolom_wib_dan_bisa_dibalik(db):
    from db.models import ReprocessJob, Result, ResultData

    wib = datetime(2000, 1, 1, 12, 0)       # nilai yang tersimpan (jam WIB)
    utc = wib - H7                          # nilai yang seharusnya

    # Result normal: uploaded_at WIB (default DB), started/completed UTC (worker).
    normal = Result(id=uuid.uuid4(), campaign="Cashline", status="done",
                    uploaded_at=wib, started_at=utc + timedelta(minutes=1),
                    completed_at=utc + timedelta(minutes=9))
    # Result jalur salin (crud.py lama: started_at = completed_at = func.now() WIB).
    salin = Result(id=uuid.uuid4(), campaign="Cashline", status="done",
                   uploaded_at=wib, started_at=wib, completed_at=wib)
    db.add_all([normal, salin])
    db.flush()
    data = ResultData(result_id=normal.id, result_json={}, created_at=wib)
    # Job lama: finished_at WIB (>= created_at); job baru: finished_at UTC (< created_at).
    job_wib = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], status="done",
                           total_tickets=0, scope="ticket", created_at=wib,
                           finished_at=wib + timedelta(minutes=5))
    job_utc = ReprocessJob(id=uuid.uuid4(), campaigns=["Cashline"], status="cancelled",
                           total_tickets=0, scope="ticket", created_at=wib,
                           finished_at=utc + timedelta(minutes=5))
    db.add_all([data, job_wib, job_utc])
    db.flush()

    m = _migration()
    _run(db, m.upgrade_statements())

    assert normal.uploaded_at == utc
    assert normal.started_at == utc + timedelta(minutes=1)          # sudah UTC, tak disentuh
    assert (salin.started_at, salin.completed_at) == (utc, utc)
    assert data.created_at == utc
    assert job_wib.created_at == utc and job_wib.finished_at == utc + timedelta(minutes=5)
    assert job_utc.finished_at == utc + timedelta(minutes=5)        # sudah UTC, tak disentuh

    _run(db, m.downgrade_statements())

    assert normal.uploaded_at == wib
    assert normal.started_at == utc + timedelta(minutes=1)
    assert (salin.started_at, salin.completed_at) == (wib, wib)
    assert data.created_at == wib
    assert job_wib.finished_at == wib + timedelta(minutes=5)
    assert job_utc.finished_at == utc + timedelta(minutes=5)
