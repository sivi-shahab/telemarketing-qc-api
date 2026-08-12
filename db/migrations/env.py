import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Build URL from environment variables (overrides alembic.ini interpolation)
def get_url():
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ.get('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}"
    )

# '%' di-escape jadi '%%': nilai ini masuk ke ConfigParser, yang memperlakukan
# '%' sebagai sintaks interpolasi. Password URL-encoded (mis. %40 untuk '@')
# akan membuat alembic gagal total tanpa escape ini.
config.set_main_option("sqlalchemy.url", get_url().replace("%", "%%"))

# Schema tujuan semua tabel aplikasi. Kosong = 'public' (perilaku lama, DB
# lokal). Diisi mis. 'dashboard' untuk DB DWH yang schema-nya dipakai bersama
# tim lain, supaya migrasi TIDAK menulis ke public.
SCHEMA = os.environ.get("POSTGRES_SCHEMA", "").strip()

from db.models import Base
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA or None,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if SCHEMA:
            # Migrasi memakai op.create_table() tanpa schema eksplisit, jadi
            # search_path yang menentukan tabel mendarat di mana. 'public' tetap
            # ikut supaya extension/type bawaan tetap terlihat.
            connection.exec_driver_sql(f'SET search_path TO "{SCHEMA}", public')
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA or None,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
