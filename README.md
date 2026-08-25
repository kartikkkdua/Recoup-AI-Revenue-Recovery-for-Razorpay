# Recoup — AI Revenue Recovery for Razorpay

[![tests](https://github.com/kartikcodespaces/Bulidathon/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/kartikcodespaces/Bulidathon/actions/workflows/test.yml)

An agent that watches a Razorpay merchant's payment stream, classifies every
failure, and executes the recovery playbook that actually works for that
cohort — retries on the right rail at the right time, sends re-tokenization
links for expired mandates, dunns subscription failures via payday-aligned
nudges, and skips the retries that would only waste gateway fees and annoy
the customer. Every action is idempotent, rate-limited, circuit-broken, and
audited.

Built for the **Razorpay AI Buildathon** — Revenue Recovery track.

> ![landing](docs/images/landing.png)
> *Landing page — pulls live numbers from the API. Falls back to seed benchmark if backend is unreachable.*

---

## The headline number

On 400 identical synthetic failures, run through both strategies back-to-back:

| | Naive baseline<br/>(retry-everything-3×) | **Recoup agent** | Lift |
|---|---:|---:|---:|
| Recovery rate | 18.0% | **56.7%** | **+38.7 pp** |
| ₹ Recovered (of ~₹10.5L eligible) | ₹2.4L | **₹5.98L** | **+₹3.6L** |
| Gateway fees burned | ₹2.6K | **₹1.2K** | **saved ₹1.4K** |
| Attempts spent | 1,327 | **608** | **719 fewer Razorpay API calls** |
| Precision | 19.9% | 62.6% | +42.7 pp |

Same failures, same amounts. The comparison lives on `/api/metrics/compare`
and renders on the dashboard.

> The point isn't retrying more successfully. The point is knowing *when not
> to retry*. Every doomed attempt we skip is money the merchant keeps and
> trust the customer keeps.

> ![dashboard](docs/images/dashboard.png)
> *Live dashboard — SSE ticker top, agent-vs-naive comparison, cohort chart, drift alerts when any surface.*

---

## What makes it an agent, not a retry loop

**Ten things** a naive retry loop can't do — all shipped, all provable:

1. **Multi-strategy per cohort.** 7 distinct playbooks. `insufficient_funds` → WhatsApp nudge + payday retry via UPI. `auth_expired` → re-tokenization link. `card_declined` → rail-switch payment link (UPI default). `bank_downtime` → exponential backoff on same rail. `risk_declined` → human review, no auto-retry.
2. **Adaptive learning.** Every attempt updates a per-`cohort × action × hour-of-day` conversion estimate. The strategist blends learned rates with hardcoded priors via a Beta(4,6) smoother — cold cohorts don't swing wildly and hot ones drift toward observed reality.
3. **Idempotency defense.** Duplicate webhooks dropped on `razorpay_event_id` with a visible counter. Fired the same signed webhook 3× → `accepted → duplicate → duplicate`.
4. **Per-customer rate limit.** Max 3 recovery actions per customer per 24h. 6 events same customer → 3 executed, 3 skipped as `rate_limited`.
5. **Time-of-day gate.** Retries scheduled into 11pm–6am IST are deferred with an explicit `deferred_low_success_window` audit + `defer_hours`.
6. **Circuit breaker on the Razorpay client.** Opens after 5 consecutive 5xx, half-open probe after 30s. Failing calls become `circuit_open_deferred`, not silently swallowed.
7. **Close-loop webhooks.** `payment_link.paid` and `payment.captured` map back to the recovery row via `razorpay_recovery_ref` and flip status to RECOVERED automatically. `subscription.halted/completed` close subscription recoveries. `refund.processed` retracts a prior recovery.
8. **Subscriptions vertical.** MRR-at-risk / retained / churned funnel with annualised value; ~30% of simulated failures are subscription-tagged.
9. **Cohort-mix drift alerts.** Detects when a cohort's share of recent failures shifts ≥10 pp from the 7-day baseline. Actionable upstream (e.g. `bank_downtime` spiking = call your acquirer).
10. **PII redacted by default.** Emails / phones / card tails masked on `GET /api/recoveries/{id}`. Opt-in with `X-Show-PII: 1`.

Click any recovery on `/recoveries/{id}` — the **"Why we did this"** card
shows the classification rationale, the blended-vs-prior probability, and any
gate that fired.

> ![decision](docs/images/decision-explain.png)
> *Every recovery has this card. Zero black-box decisions on a money path.*

---

## The load-bearing principle

**The LLM never sits between a webhook and a charge decision.**

Failure classification runs deterministic rules first. If rules match, we're
done. Only if rules are ambiguous do we call the LLM (Gemini 2.0 Flash), and
even then the LLM's job is *just to pick a cohort label* — the strategy
lookup and the money action are deterministic, driven by merchant-editable
rules.

Payments teams get burned when an LLM hallucinates a decision that
authorizes a charge. Recoup can't do that by construction.

---

## Architecture

```
                              ┌──────────────────────────┐
        Razorpay webhooks ──▶ │ POST /webhooks           │
     (payment.failed,         │  • HMAC-SHA256 verify    │
      payment.captured,       │  • dedup on event.id     │
      payment_link.paid,      │  • duplicate counter     │
      subscription.*,         │  • routes agent/closer   │
      refund.processed)       └───────────┬──────────────┘
                                          │
              ┌───────── failure ─────────┴───────── close ─────────┐
              ▼                                                       ▼
   ┌──────────────────────┐                          ┌──────────────────────┐
   │ Classifier           │                          │ Closer               │
   │  1. rules            │                          │  find recovery by    │
   │  2. keyword          │                          │  razorpay_recovery_  │
   │  3. Gemini fallback  │                          │  ref → mark closed   │
   └──────────┬───────────┘                          └──────────────────────┘
              ▼
   ┌──────────────────────┐
   │ Reliability gates    │
   │  • rate limit / 24h  │
   │  • time-of-day IST   │
   │  • circuit breaker   │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Strategist           │
   │  • per-cohort playbook│
   │  • merchant override │
   │  • learned probability│
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Executor             │
   │  • real Razorpay API │
   │  • stores link_id /  │
   │    order_id as ref   │
   │  • audits every step │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Learning loop        │
   │  record_outcome(     │
   │    cohort, action,   │
   │    hour, success)    │
   └──────────┬───────────┘
              ▼
        Next.js dashboard  ──▶  merchant
        (live SSE ticker, agent-vs-naive,
         cohorts, subscriptions, ROI,
         drift alerts, per-recovery "why")
              ▲
              │
   Prometheus /metrics  ──▶  Grafana / VictoriaMetrics
```

---

## Repo layout

```
api/
  app/
    routers/            webhooks · recoveries · metrics · rules · roi · simulator
                        · stream (SSE) · subscriptions · prom (Prometheus)
    agent.py            classifier → gates → strategist → executor pipeline
    closer.py           payment_link.paid / payment.captured / subscription.* handlers
    classifier.py       rules + keyword + Gemini fallback
    strategist.py       per-cohort playbooks + naive baseline
    reliability.py      circuit breaker + rate limiter + time-of-day gate
    learning.py         Beta-smoothed per-cohort×action×hour conversion rates
    redact.py           PII redaction for audit output
    razorpay_client.py  wrapped in circuit breaker, sandbox-aware
    db.py               SQLAlchemy models (async SQLite for MVP; drop-in Postgres)
  simulator/            realistic scenario generator (with subscription mix)
  tests/                33 tests: idempotency, classifier, close-loop, rate limit,
                        circuit breaker, ROI, rules roundtrip, subscriptions,
                        drift, PII redaction, Prometheus format

web/
  src/
    app/                Next.js 14 App Router pages
      page.tsx          landing (live numbers from API, seed fallback)
      dashboard/        headline + live SSE ticker + reliability strip +
                        agent-vs-naive + cohorts + drift alerts + recent
      recoveries/[id]/  detail + DecisionExplain + full audit trail
      subscriptions/    MRR-at-risk funnel + subscription recoveries feed
      rules/            editable per-cohort playbook overrides (PUT persists live)
      roi/              interactive ROI calculator (observed rates when available)
      settings/         integration + config
    components/         HeadlineMetrics · ComparisonPanel · ReliabilityStrip ·
                        CohortTable · DecisionExplain · LiveTicker · DriftAlerts …
    lib/                typed API client + INR/percent formatting
```

---

## Quickstart

**Backend** (Python 3.13):

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add Razorpay test keys + Gemini key + webhook secret
uvicorn app.main:app --reload --port 8080
```

**Frontend** (Node 20+):

```bash
cd web
npm install
npm run dev               # http://localhost:3000
```

**See it work in 10 seconds:**

```bash
curl -X POST http://localhost:8080/api/simulator/benchmark \
  -H 'content-type: application/json' \
  -d '{"count": 400, "concurrency": 8}'
```

Open `http://localhost:3000/dashboard`. The live SSE ticker at the top will
show events processing in real time (~100 events/sec on SQLite).

---

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /webhooks` | HMAC-verified Razorpay webhook receiver; routes to agent or closer |
| `GET /api/metrics/summary` | Recovery rate, ₹ recovered, fees, precision |
| `GET /api/metrics/compare` | Agent-vs-naive side-by-side with lift |
| `GET /api/metrics/cohorts?mode=agent\|naive` | Per-cohort breakdown |
| `GET /api/metrics/reliability` | Duplicates, rate-limit denials, circuit state |
| `GET /api/metrics/drift` | Cohort-mix drift alerts (recent vs baseline) |
| `GET /api/metrics/learned` | Observed conversion rates per cohort × action × hour |
| `GET /api/stream/live` | Server-Sent Events — dashboard live tick |
| `GET /api/subscriptions/summary` | MRR-at-risk / retained / churned |
| `GET /api/subscriptions` | Subscription recoveries list |
| `GET /api/recoveries` | Paginated recoveries |
| `GET /api/recoveries/{id}` | Detail + decision context + audit; PII redacted by default |
| `GET /api/rules` · `PUT /api/rules/{cohort}` · `DELETE /api/rules/{cohort}` | Merchant-editable playbook overrides |
| `GET /api/roi/defaults` · `POST /api/roi/estimate` | ROI calculator (observed rates when available) |
| `POST /api/simulator/run` · `POST /api/simulator/benchmark` | Inject synthetic failures / run agent-vs-naive |
| `GET /metrics` | Prometheus text-format scrape |

---

## Real Razorpay end-to-end

The pipeline **actually integrates with Razorpay's test-mode API** — not a mock.
A live test end-to-end:

1. Fired a signed `payment.failed` webhook with a real customer contact
2. Classifier picked `card_declined` from rules (no LLM)
3. Strategist chose `rail_switch_link` (UPI as default rail)
4. `client.payment_link.create(...)` hit real Razorpay → `plink_TSixxAYCvqBQs1` returned
5. Razorpay dispatched real SMS + email to the customer
6. Customer paid the link with test card `4111 1111 1111 1111`
7. Razorpay fired `payment_link.paid` → closer matched on `razorpay_recovery_ref` → recovery flipped to RECOVERED with `closed_by_payment_link_paid` audit entry

Full trail visible on `/recoveries/{id}` with the real Razorpay `plink_...` id.

---

## Prometheus / Grafana

`GET /metrics` returns standard Prometheus text-format 0.0.4 exposition:

```
# HELP recoup_recoveries_total Recoveries by mode and terminal status (30d window)
# TYPE recoup_recoveries_total gauge
recoup_recoveries_total{mode="agent",status="recovered"} 179
recoup_recoveries_total{mode="agent",status="lost"} 89
recoup_recovered_amount_paise{cohort="insufficient_funds"} 19743900
recoup_gateway_fees_paise{cohort="bank_downtime"} 34800
recoup_duplicates_dropped_total 0
recoup_razorpay_circuit_state{state="closed"} 1
...
```

Sample Grafana queries:
```promql
sum(recoup_recovered_amount_paise) / sum(recoup_eligible_amount_paise)  # recovery rate
rate(recoup_duplicates_dropped_total[5m])                                # dedup rate
recoup_razorpay_circuit_state{state="open"} == 1                         # alert when open
```

---

## Test suite

```bash
cd api && pytest -q
# ................................. 33 passed in 1.20s
```

| File | What it proves |
|---|---|
| `test_classifier.py` | Rules match canonical error codes; keyword fallback works |
| `test_idempotency.py` | Duplicate signed webhooks yield one recovery row; bad sig → 401 |
| `test_close_loop.py` | `payment_link.paid` / `payment.captured` / `subscription.halted` all close recoveries; `refund.processed` retracts |
| `test_rate_limit.py` | Nth+1 attempt denied per customer; distinct customers have separate buckets |
| `test_circuit_breaker.py` | Opens after threshold, half-opens after cooldown, success resets counter |
| `test_rules_roundtrip.py` | PUT override → strategist reads it live; DELETE resets to default; disabled override ignored |
| `test_subscriptions.py` | Summary + list filter to subscription-tagged recoveries only |
| `test_drift.py` | Flags cohorts whose share shifted ≥10 pp; silent when recent window too small |
| `test_redact.py` | Emails/phones/cards masked by default; unredacted with `X-Show-PII: 1` |
| `test_roi.py` | Lift scales with volume; sub bonus applies to annual only |
| `test_prom.py` | Prometheus format valid; circuit gauges mutually exclusive |

---

## Performance

- **~100 events/sec** on SQLite WAL (measured: 800 events in 7.9s at concurrency=8)
- **1600 → 800 commits/run** — single commit per recovery, not two
- **Sub-second** headline metric queries at 10k+ recovery rows
- **Postgres migration path**: change `DATABASE_URL` to `postgresql+asyncpg://...`, bump `pool_size`, done. SA async engine already async. Expected 10–50× throughput.

---

## What we'd build next (month-1 intern roadmap)

1. **Deploy to Render + Vercel** with a stable HTTPS URL so panel members can visit
2. **Postgres + Redis Streams** — replace SQLite + in-process asyncio at ~10k events/sec
3. **Redis-backed reliability primitives** — circuit breaker + rate limiter shared across replicas
4. **Playbook A/B testing** — 20% of failures get an experimental variant, compare weekly
5. **Cohort-mix drift → Slack webhook** — currently surfaces on dashboard, should also push
6. **Merchant multi-tenancy** — real `merchant_id` on webhooks with per-merchant dashboards
7. **Real WhatsApp send** via Gupshup/MSG91 — currently stubbed (audit-only)

---

## Design decisions

- **Async everything.** FastAPI + `sqlalchemy[asyncio]` + `aiosqlite`. Real-time SSE stream to the dashboard.
- **In-process reliability primitives on purpose.** Circuit breaker + rate limiter + dup counter all in `app/reliability.py`. At merchant scale they move to Redis without changing callers — the API surface is unchanged.
- **Sandbox mode is opt-in per call.** Real Razorpay traffic still hits Razorpay; simulator marks events `"simulated": true` and the client short-circuits accordingly.
- **PII redacted by default.** Even the merchant dashboard doesn't show raw contact/email unless explicitly opted-in (`X-Show-PII` header).
- **The LLM is disposable.** Rules match ~85% of failures deterministically. Toggle rules-only mode in `.env` if a merchant doesn't trust LLM classification.

---

## Not built (yet), and why

- **No user auth / multi-tenancy** — single-merchant demo. Adding auth without a second merchant to demo is complexity for no story.
- **No fancy animations or dark-mode toggle** — zero panel score.
- **No hash-chained immutable audit log** — overkill for MVP; SQLite unique constraint on event id + WAL journaling gives us "add-only for the important reasons."

---

## Submission

- Track: **AI Revenue Recovery**
- Author: Kartik Dua
- Pitch narrative: [`PITCH.md`](PITCH.md)
- Demo script: [`DEMO.md`](DEMO.md)
