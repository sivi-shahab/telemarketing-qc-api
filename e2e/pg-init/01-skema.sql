-- Skema `dashboard` HARUS sudah ada sebelum alembic jalan.
-- Migrasi tidak membuatnya sendiri (env.py hanya menyetel search_path dan
-- version_table_schema) — di produksi skema itu memang sudah ada sebagai skema DWH.
-- Tanpa baris ini container API mati saat startup dengan InvalidSchemaName.
CREATE SCHEMA IF NOT EXISTS dashboard;
