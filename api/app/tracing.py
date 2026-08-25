"""OpenTelemetry setup — one tracer, in-memory span exporter by default.

Emits spans for the load-bearing steps of the recovery pipeline:
- webhook.receive
- agent.classify
- agent.reliability_gates
- agent.strategist (with bandit + memory + uplift attrs)
- agent.execute
- closer.close_event

In production point OTEL_EXPORTER_OTLP_ENDPOINT at Grafana Tempo /
Datadog / Honeycomb — swap in OTLPSpanExporter, no other code changes.
"""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# In-memory exporter — spans stay queryable from /api/traces/recent for the demo.
_memory_exporter = InMemorySpanExporter()


def configure() -> None:
    resource = Resource.create({"service.name": "recoup-api", "service.version": "0.1.0"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
    if os.environ.get("RECOUP_OTEL_CONSOLE") == "1":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def get_tracer():
    return trace.get_tracer("recoup")


def recent_spans(limit: int = 100) -> list[dict]:
    spans = _memory_exporter.get_finished_spans()
    out = []
    for s in spans[-limit:]:
        ctx = s.get_span_context()
        parent = getattr(s.parent, "span_id", None) if s.parent else None
        out.append({
            "trace_id": f"{ctx.trace_id:032x}",
            "span_id": f"{ctx.span_id:016x}",
            "parent_span_id": f"{parent:016x}" if parent else None,
            "name": s.name,
            "start_ns": s.start_time,
            "end_ns": s.end_time,
            "duration_ms": (s.end_time - s.start_time) / 1_000_000 if s.end_time else None,
            "status": s.status.status_code.name,
            "attributes": dict(s.attributes or {}),
        })
    return out


def clear_spans() -> None:
    _memory_exporter.clear()
