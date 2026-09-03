# Image API — self-contained: seluruh kode ikut di-COPY, TIDAK mengandalkan
# bind-mount `.:/app` seperti compose monorepo dulu. Build context = root repo
# (submodule `core/` harus sudah ter-checkout).
#
#   docker build -f api/Dockerfile -t qc-api .
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Sertifikat cdn.bankmega.local. Server hanya mengirim leaf-nya tanpa CA
# penerbit ("Bank Mega Local Authority"), jadi leaf itu sendiri yang dipercaya
# --- sama seperti trust store host. Tanpa ini SETIAP operasi MinIO gagal
# CERTIFICATE_VERIFY_FAILED, bukan cuma ensure_buckets() saat startup.
COPY certs/bankmegalocal.crt /usr/local/share/ca-certificates/bankmegalocal.crt
RUN update-ca-certificates

# minio 7.2.20 memakai `ca_certs=os.environ.get("SSL_CERT_FILE") or certifi.where()`,
# dan certifi TIDAK ikut membaca trust store sistem -- jadi SSL_CERT_FILE wajib
# ditunjuk eksplisit ke bundle hasil update-ca-certificates. REQUESTS_CA_BUNDLE
# menyamakan perilaku untuk `requests` (DWH API, TMS, view streams).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Dependensi core lebih dulu, baru milik API — dua layer cache terpisah.
COPY core/requirements.txt /tmp/core-requirements.txt
COPY api/requirements.txt  /tmp/api-requirements.txt
RUN pip install --no-cache-dir -r /tmp/core-requirements.txt -r /tmp/api-requirements.txt

# Isi core di-COPY DATAR ke /app supaya import tetap `from db import crud`
# (bukan `from core.db import crud`), sama seperti saat masih monorepo.
COPY core/db              /app/db
COPY core/compliance      /app/compliance
COPY core/services        /app/services
COPY core/prompt          /app/prompt
COPY core/sales_lookup.py /app/sales_lookup.py
COPY core/core_config.py  /app/core_config.py

COPY api           /app/api
COPY alembic.ini   /app/alembic.ini
COPY db/migrations /app/db/migrations
COPY scripts       /app/scripts

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:4000/health || exit 1

# API adalah satu-satunya pemilik migrasi Alembic — worker tidak menjalankannya.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
