# Image API — self-contained. Core BUKAN lagi folder di repo ini melainkan
# dependensi pip (telemarketing-qc-core, dipin di api/requirements.txt).
#
#   docker build -f api/Dockerfile -t qc-api .

# --- Stage builder: satu-satunya tempat `git` dibutuhkan -------------------
# pip harus meng-clone core dari git+https. Dengan mengubahnya jadi wheel di
# sini, image akhir tidak perlu memasang git sama sekali.
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git gcc \
    && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

# --- Stage runtime --------------------------------------------------------
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

# --no-index: seluruh isi terpasang dari wheel hasil stage builder, tidak ada
# satu pun yang ditarik diam-diam dari jaringan saat stage ini berjalan.
#
# /wheels di-bind-mount, BUKAN di-COPY: COPY selalu membuat layer sendiri, dan
# `rm -rf /wheels` sesudahnya tidak bisa merebut kembali ~64 MB itu -- wheel-nya
# ikut terbawa selamanya di image akhir. Bind mount hanya ada selama RUN.
COPY api/requirements.txt /tmp/requirements.txt
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt

COPY api           /app/api
COPY alembic.ini   /app/alembic.ini
COPY db/migrations /app/db/migrations
COPY scripts       /app/scripts

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:4000/health || exit 1

# API adalah satu-satunya pemilik migrasi Alembic — worker tidak menjalankannya.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
