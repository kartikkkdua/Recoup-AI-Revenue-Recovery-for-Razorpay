# Recoup API

FastAPI service — webhook receiver, agent, orchestrator, metrics.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in Razorpay keys when you have them
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `POST /webhooks` — Razorpay webhook receiver (HMAC-verified, idempotent by `event.id`)
- `POST /api/simulator/run` — inject N synthetic failed-payment scenarios (sandbox only)
- `GET  /api/recoveries` — paginated recoveries list
- `GET  /api/recoveries/{id}` — recovery detail with full audit trail
- `GET  /api/metrics/summary` — headline metrics for the dashboard
- `GET  /api/metrics/cohorts` — per-cohort breakdown
- `GET  /api/rules` / `PUT /api/rules/{cohort}` — merchant-editable retry rules

## Point Razorpay webhooks at us

In Razorpay dashboard → Settings → Webhooks:
- URL: `https://<your-tunnel>/webhooks`
- Secret: whatever you put in `RAZORPAY_WEBHOOK_SECRET`
- Events: `payment.failed`, `subscription.charged.failed`, `order.paid`, `payment_link.paid`

For local dev, use `cloudflared tunnel --url http://localhost:8000` or ngrok.

## Tests

```bash
pytest
```

Covers HMAC verification, duplicate-event dedupe, and classifier rule hits.
