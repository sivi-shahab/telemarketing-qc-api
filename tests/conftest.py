import os

# Must be set before any import that triggers Settings instantiation.
# Uses setdefault so a real .env in the environment is not clobbered when
# running against live infra, but tests always have a deterministic key.
TEST_API_KEY = "test-api-key-integration-12345"
os.environ.setdefault("API_KEY", TEST_API_KEY)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6378/0")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")

import pytest


@pytest.fixture()
def db():
    """Sesi DB di dalam transaksi yang SELALU di-rollback.

    Test boleh menyisipkan baris (job reproses, item) dan tetap tidak
    meninggalkan apa pun — termasuk saat dijalankan terhadap DB yang berisi data
    sungguhan. Dilewati kalau DB tidak terjangkau, supaya suite tetap bisa jalan
    di luar container.
    """
    from sqlalchemy.orm import sessionmaker

    from api.dependencies import _make_engine, get_settings

    try:
        engine = _make_engine(get_settings())
        # REPEATABLE READ, bukan READ COMMITTED bawaan: test yang membandingkan dua
        # pembacaan (mis. helper filter vs /list_results) memakai belasan detik, dan
        # worker reproses menghapus/menyisipkan row justru di sela itu — hasilnya
        # kegagalan yang hanya muncul saat ada job berjalan. Satu snapshot membuat
        # kedua pembacaan melihat data yang sama.
        conn = engine.connect().execution_options(isolation_level="REPEATABLE READ")
    except Exception as exc:
        pytest.skip(f"database tidak terjangkau: {exc}")

    trans = conn.begin()
    # `join_transaction_mode="create_savepoint"` WAJIB: kode yang diuji memanggil
    # db.commit() sendiri (mis. crud.create_reprocess_job). Tanpa ini commit itu
    # menembus sampai ke transaksi luar dan baris test tertinggal di DB sungguhan;
    # dengan ini ia hanya melepas SAVEPOINT, dan rollback di bawah tetap membuang
    # semuanya.
    session = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture()
def admin_user(db):
    """Row ``User`` dengan role admin — bentuk yang sama dengan ``current_user``.

    ``get_current_user`` mengembalikan row ``db.models.User``, jadi route bisa
    dipanggil sebagai fungsi Python biasa dengan row ini.
    """
    from db.models import User

    # ``order_by`` WAJIB: tanpa urutan, Postgres mengembalikan baris menurut letak
    # fisiknya, dan UPDATE apa pun pada tabel users (mis. reset password)
    # memindahkannya — test lalu diam-diam memakai admin lain dengan cakupan
    # campaign berbeda (25 September 2026).
    user = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if user is None:
        pytest.skip("tidak ada user role admin di database")
    return user


@pytest.fixture()
def ticket_load_dates_table(db):
    """Membuat tabel ``ticket_load_dates`` DI DALAM transaksi test (20 Oktober 2026).

    Migrasi 0069 belum dijalankan di DB sungguhan saat test ini ditulis, dan test
    memakai DB prod. DDL Postgres transaksional, jadi tabel ini ikut hilang saat
    ``db`` di-rollback — tidak ada yang tertinggal. ``checkfirst`` membuatnya tetap
    jalan setelah migrasi benar-benar diterapkan.
    """
    from db.models import TicketLoadDate

    TicketLoadDate.__table__.create(bind=db.connection(), checkfirst=True)
    return TicketLoadDate
