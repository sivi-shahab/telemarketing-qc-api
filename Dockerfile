# Image API — self-contained: seluruh kode ikut di-COPY, TIDAK mengandalkan
# bind-mount `.:/app`. Build context = root repo.
#
#   docker build -f api/Dockerfile -t qc-api .
FROM imageregistry.bankmegadev.com:5000/python/python:3.11.15-slim

# Proxy
ENV http_proxy=http://10.190.21.24:3128
ENV https_proxy=http://10.190.21.24:3128
ENV no_proxy=localhost,127.0.0.1,.bankmega.com
ENV HTTP_PROXY=http://10.190.21.24:3128
ENV HTTPS_PROXY=http://10.190.21.24:3128
ENV NO_PROXY=localhost,127.0.0.1,.bankmega.com

# Environment default
ENV PYTHONPATH=/pythonlibs
ENV PYTHONUNBUFFERED=1 
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/pythonlibs/.venv-qc-api/bin:$PATH"

# Install required package
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

# certifi TIDAK ikut membaca trust store sistem, jadi SSL_CERT_FILE wajib
# ditunjuk eksplisit ke bundle hasil update-ca-certificates. REQUESTS_CA_BUNDLE
# menyamakan perilaku untuk `requests` (DWH API, TMS, view streams).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Create non-root user
RUN useradd -m -u 101 appuser

# Create virtual environment
RUN mkdir -p /pythonlibs
RUN python -m venv /pythonlibs/.venv-qc-api
RUN chown -R appuser:appuser /pythonlibs

# Work directory
WORKDIR /app

# Prepare permission
RUN chown -R appuser:appuser /app

# Dependensi core lebih dulu, baru milik API — dua layer cache terpisah.
COPY --chown=appuser:appuser core/requirements.txt /tmp/core-requirements.txt
COPY --chown=appuser:appuser api/requirements.txt  /tmp/api-requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/core-requirements.txt -r /tmp/api-requirements.txt

# Isi core di-COPY DATAR ke /app supaya import tetap `from db import crud`
# (bukan `from core.db import crud`), sama seperti saat masih monorepo.
COPY --chown=appuser:appuser core/db              /app/db
COPY --chown=appuser:appuser core/compliance      /app/compliance
COPY --chown=appuser:appuser core/services        /app/services
COPY --chown=appuser:appuser core/prompt          /app/prompt
COPY --chown=appuser:appuser core/sales_lookup.py /app/sales_lookup.py
COPY --chown=appuser:appuser core/core_config.py  /app/core_config.py
COPY --chown=appuser:appuser core/qc_auto_assign.py /app/qc_auto_assign.py

COPY --chown=appuser:appuser api           /app/api
COPY --chown=appuser:appuser scripts       /app/scripts
COPY --chown=appuser:appuser alembic.ini   /app/alembic.ini
COPY --chown=appuser:appuser db/migrations /app/db/migrations

# Non-root user
USER appuser

# Cleanup Proxy
ENV http_proxy=
ENV https_proxy=
ENV no_proxy=localhost,127.0.0.1,.bankmega.com
ENV HTTP_PROXY=
ENV HTTPS_PROXY=
ENV NO_PROXY=localhost,127.0.0.1,.bankmega.com

EXPOSE 4000

CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
