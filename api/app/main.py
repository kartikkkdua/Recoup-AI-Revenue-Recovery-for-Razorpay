from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import metrics, prom, recoveries, roi, rules, simulator, stream, subscriptions, webhooks


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Recoup API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(recoveries.router, prefix="/api/recoveries", tags=["recoveries"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
app.include_router(rules.router, prefix="/api/rules", tags=["rules"])
app.include_router(roi.router, prefix="/api/roi", tags=["roi"])
app.include_router(simulator.router, prefix="/api/simulator", tags=["simulator"])
app.include_router(stream.router, prefix="/api/stream", tags=["stream"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(prom.router, prefix="/metrics", tags=["prometheus"])


@app.get("/health")
async def health():
    return {"ok": True}
