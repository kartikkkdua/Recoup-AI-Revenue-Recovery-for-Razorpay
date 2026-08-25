"""OTel span emission — handle_event produces the expected span tree."""
import pytest

from app import tracing
from app.agent import handle_event
from app.db import SessionLocal, WebhookEvent


@pytest.mark.asyncio
async def test_handle_event_emits_named_spans():
    tracing.configure()
    tracing.clear_spans()
    async with SessionLocal() as s:
        e = WebhookEvent(razorpay_event_id="evt_trace_1", event_type="payment.failed",
                         payload={"id": "evt_trace_1", "event": "payment.failed",
                                  "simulated": True,
                                  "payload": {"payment": {"entity": {
                                      "id": "p", "order_id": "o", "amount": 12300,
                                      "currency": "INR", "status": "failed", "method": "upi",
                                      "error_code": "GATEWAY_ERROR", "error_reason": "bank_error",
                                      "error_description": "issuer offline",
                                      "notes": {"customer_id": "cust_trace"},
                                  }}}})
        s.add(e); await s.commit(); await s.refresh(e); eid = e.id
    await handle_event(eid, mode="agent")
    spans = tracing.recent_spans()
    names = {s["name"] for s in spans}
    assert "agent.handle_event" in names
    assert "agent.classify" in names
    assert "agent.execute" in names
    # Ordering: parent (handle_event) is not before children finish
    handle = next(s for s in spans if s["name"] == "agent.handle_event")
    classify = next(s for s in spans if s["name"] == "agent.classify")
    assert classify["attributes"]["cohort"] == "bank_downtime"
    assert handle["end_ns"] >= classify["end_ns"]


@pytest.mark.asyncio
async def test_recent_spans_endpoint_shape():
    tracing.configure()
    tracing.clear_spans()
    tr = tracing.get_tracer()
    with tr.start_as_current_span("test.dummy", attributes={"k": "v"}):
        pass
    from app.routers.traces import recent
    r = await recent(limit=10)
    assert r["spans"]
    assert any(s["name"] == "test.dummy" and s["attributes"]["k"] == "v" for s in r["spans"])
