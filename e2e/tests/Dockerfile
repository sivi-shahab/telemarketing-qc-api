FROM python:3.11-slim
WORKDIR /tests
# passlib/bcrypt versinya disamakan dengan api/requirements.txt supaya hash yang
# dibuat test bisa diverifikasi oleh aplikasi yang diuji.
RUN pip install --no-cache-dir pytest allure-pytest requests psycopg2-binary \
    "passlib[bcrypt]" "bcrypt==3.2.2"
