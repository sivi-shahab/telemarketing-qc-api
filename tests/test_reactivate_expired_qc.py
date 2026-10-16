"""QC yang dinonaktifkan TL QC (Kelola QC) aktif kembali lewat 00.00 WIB.

``crud.reactivate_expired_qc_users`` dipanggil beat worker tiap 2 menit dan saat
login; diuji di SQLite supaya UPDATE-nya benar-benar dijalankan.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import crud
from db.models import User


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _add(db, uid, active, until):
    db.add(User(id=uid, username=f"qc{uid}", email=f"qc{uid}@x", hashed_password="x",
                role="qc", is_active=active, inactive_until=until))


def test_hanya_yang_lewat_batas_diaktifkan(db):
    now = datetime(2026, 10, 16, 17, 1)
    _add(db, 1, False, datetime(2026, 10, 16, 17, 0))  # lewat -> aktif
    _add(db, 2, False, datetime(2026, 10, 17, 17, 0))  # belum
    _add(db, 3, False, None)                            # nonaktif permanen (Admin)
    _add(db, 4, True, None)
    db.commit()
    assert crud.reactivate_expired_qc_users(db, now=now) == ["qc1"]
    db.expire_all()
    state = {u.id: (u.is_active, u.inactive_until) for u in db.query(User)}
    assert state[1] == (True, None)
    assert state[2] == (False, datetime(2026, 10, 17, 17, 0))
    assert state[3] == (False, None)
    assert state[4] == (True, None)


def test_tanpa_yang_kedaluwarsa_tidak_ada_perubahan(db):
    _add(db, 1, False, datetime(2026, 10, 16, 17, 0))
    db.commit()
    assert crud.reactivate_expired_qc_users(db, now=datetime(2026, 10, 16, 16, 0)) == []
