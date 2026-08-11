from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import ensure_buckets
from api.routers import agent_error, auth, campaign, document, error_code_appeal, qc_assignment, qc_database, qc_manual_check, qc_status, sales_database, stats, transcript, webhook


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

app.include_router(auth.router)
app.include_router(transcript.router)
app.include_router(campaign.router)
app.include_router(document.router)
app.include_router(webhook.router)
app.include_router(stats.router)
app.include_router(agent_error.router)
app.include_router(qc_status.router)
app.include_router(qc_manual_check.router)
app.include_router(error_code_appeal.router)
app.include_router(qc_assignment.router)
app.include_router(qc_database.router)
app.include_router(sales_database.router)


@app.get("/health")
def health():
    return {"status": "ok"}