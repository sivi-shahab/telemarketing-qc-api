from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.dependencies import ensure_buckets
# qc_database dinonaktifkan (bucket qc-database di-comment di api/dependencies.py)
from api.routers import agent_error, app_setting, auth, campaign, collection, document, error_code_appeal, qc_assignment, qc_manual_check, qc_status, reprocess, role, sales_database, stats, stats_collection, tickets_daily, tickets_daily_pdf, transcript, webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_buckets()
    yield


app = FastAPI(
    title="Bank Call Center QA System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://10.158.32.26:4006",
        "http://10.158.32.26:8000",
        "http://10.158.32.26:8001",
        "http://10.158.32.26:8010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Stats snapshot & list responses are large JSON (hierarki bisa ratusan KB) —
# gzip memangkasnya ~80-90% saat client kirim Accept-Encoding: gzip. Kalau nanti
# ada reverse proxy di depan yang sudah mengompres, ini jadi no-op (tidak
# dobel-compress: GZipMiddleware skip response yang sudah ber-Content-Encoding).
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(auth.router)
app.include_router(role.router)
app.include_router(transcript.router)
app.include_router(campaign.router)
app.include_router(document.router)
app.include_router(webhook.router)
app.include_router(stats_collection.router)
app.include_router(stats.router)
app.include_router(agent_error.router)
app.include_router(qc_status.router)
app.include_router(qc_manual_check.router)
app.include_router(error_code_appeal.router)
app.include_router(qc_assignment.router)
# app.include_router(qc_database.router)
app.include_router(sales_database.router)
app.include_router(reprocess.router)
app.include_router(tickets_daily.router)
app.include_router(tickets_daily_pdf.router)
app.include_router(app_setting.router)
app.include_router(collection.router)


@app.get("/health")
def health():
    return {"status": "ok"}
