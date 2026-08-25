from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import logging_setup, tracing
from app.config import settings
from app.db import init_db
from app.routers import advanced, causal, metrics, prom, recoveries, roi, rules, simulator, stream, subscriptions, traces, uplift, webhooks


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging_setup.configure(json_output=False)  # flip to True in production
    tracing.configure()
    await init_db()
    yield


app = FastAPI(title="Recoup API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Assign a fresh trace_id per request, honor an inbound X-Trace-Id header
    (so upstream callers — Razorpay retries, curl scripts — can correlate)."""
    tid = request.headers.get("x-trace-id") or logging_setup.new_trace()
    logging_setup._trace.set(tid)
    response = await call_next(request)
    response.headers["x-trace-id"] = tid
    return response

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
app.include_router(causal.router, prefix="/api/causal", tags=["causal"])
app.include_router(uplift.router, prefix="/api/uplift", tags=["uplift"])
app.include_router(traces.router, prefix="/api/traces", tags=["traces"])
app.include_router(advanced.router, prefix="/api", tags=["advanced-ml"])


@app.get("/health")
async def health():
    return {"ok": True}
