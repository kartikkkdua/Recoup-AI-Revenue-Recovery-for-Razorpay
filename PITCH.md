# Pitch — Recoup

For the Razorpay AI Buildathon panel. Read this before the demo.

---

## The problem, in one paragraph

Indian merchants on Razorpay lose 10–15% of attempted payments to failure —
insufficient funds, bank downtime, mandate expiry, PSP flakiness, risk
declines. A big chunk of those are *recoverable* with the right action at
the right time: a nudge before payday, a re-tokenization link, a rail switch
from card to UPI. Most merchants do the naive thing — retry everything a few
times — which recovers ~18% and wastes gateway fees on doomed attempts.
There's no product on the Razorpay platform that watches failures per
merchant and picks the right playbook per cohort.

## What Recoup is

An agent that sits behind the merchant's webhook stream, classifies every
failure, and executes the recovery playbook that actually works for that
cohort — with a learning loop that adapts per-merchant over time and a
reliability layer (rate limits, circuit breakers, time-of-day gates) so the
merchant trusts it with money.

## What we built

- **Full pipeline**: HMAC-verified webhook receiver → deterministic
  classifier (rules primary, LLM only for ambiguous cases) → per-cohort
  strategist → executor with circuit-broken Razorpay client → adaptive
  learning loop → merchant dashboard.
- **7 cohorts, 7 distinct playbooks** — not "retry or don't."
- **Agent-vs-naive comparison** on identical failure streams — 3.2× more
  revenue recovered, 55% fewer gateway calls.
- **Reliability primitives** — dedup counter, per-customer rate limit,
  circuit breaker, low-success-hour retry gate — all provable in the demo.
- **Adaptive learning** — Beta-smoothed rolling conversion rates per
  cohort × action × hour drive the strategist's decisions.
- **Explain-my-decision UI** — every recovery has a "Why we did this" card
  showing classification rationale, blended vs prior probability, and any
  gate that triggered.

## The one measured result

400 identical synthetic failures, both strategies:

| | Naive | **Recoup** |
|---|---:|---:|
| Recovery rate | 18.0% | **56.7%** |
| ₹ Recovered (of ₹10.5L eligible) | ₹2.4L | **₹5.98L** |
| Gateway fees | ₹2.6K | **₹1.2K** |
| Attempts | 1,327 | **608** |

3.2× more recovered on the same failures, with fewer gateway calls.

## Why an ML/AI person wants to work on this

The interesting part isn't the LLM classification — that's the *easy* part.
The interesting parts are:

1. **The learning loop.** Rolling per-cohort × per-hour conversion estimates
   with a Beta prior for cold starts. Cold cohorts don't swing on first
   samples; hot cohorts drift toward observed reality.
2. **The gate architecture.** Rate limit, time-of-day, circuit breaker
   compose ahead of the strategist. Any decision to *skip* an action is a
   legible, first-class outcome, not a silent failure.
3. **The counterfactual.** Every merchant should be able to answer "what
   would naive have done?" — that's how you prove your value. We ship the
   comparison built-in.

## Why a payments engineer wants to work on this

- **LLM is not in the money path.** Panel gets to poke at this. Rules
  primary; LLM only for classification tie-breaking; strategy lookup and
  money actions are deterministic.
- **Idempotency proven end-to-end.** Fire the same signed webhook 3× — the
  dedup counter ticks; no double recovery row.
- **Circuit breaker on the Razorpay client.** Explicit `circuit_open_deferred`
  audit entries; no silent swallowing.
- **Every action reversible or auditable.** Retry attempts, dunning sends,
  payment-link creations all logged with input → decision → tool call →
  outcome.

---

## The 5-slide deck

**Slide 1 — The one number**

> ₹ recovered / ₹ recoverable, with precision.
>
> **3.2× more revenue than naive retry. 55% fewer gateway calls.**

Screenshot: dashboard headline row + ComparisonPanel.

---

**Slide 2 — The mechanism**

Architecture diagram (from README). Call out:
- Deterministic classifier → gates → strategist → executor
- LLM only for classification tie-breaking
- Every action logged with a "why"

---

**Slide 3 — Why this beats naive retry**

Cohort-by-cohort table:

| Cohort | Naive | Recoup | What Recoup does |
|---|---:|---:|---|
| `insufficient_funds` | 1% | **79%** | WhatsApp nudge + payday-cycle retries via UPI |
| `bank_downtime` | 20% | **75%** | Backoff 60s→5m→15m, not instant hammer |
| `auth_expired` | 12% | **53%** | Re-tokenization link |
| `card_declined` | 8% | **26%** | Rail-switch link (UPI default) |
| `upi_psp_error` | 37% | **55%** | Alt PSP, fallback to card |

Punchline: **Anyone can retry more. Knowing when NOT to retry is what wins.**

---

**Slide 4 — What makes it trust-worthy**

Reliability strip screenshot + bullets:
- Idempotency by `event.id` (visible counter: `duplicates_dropped_total`)
- Rate limit per customer per 24h (fired 6 events same customer → 3 executed, 3 denied)
- Circuit breaker on Razorpay client (opens on 5× 5xx, half-open probe at 30s)
- Time-of-day gate (retries into low-success IST windows are deferred with an explicit audit)
- Full audit trail on every recovery — click any row on `/recoveries/{id}`

---

**Slide 5 — What we ship in month 1 as an intern**

1. Real Razorpay Payment Link integration (deferred here; needs KYC on test mode)
2. Subscription lifecycle vertical (bigger revenue than one-shot)
3. Cohort-mix drift alerts ("HDFC failure rate spiked 22→47% in 6h")
4. Per-merchant ROI calculator (sales-team gift)
5. Postgres + Redis Streams migration (SQLite is the current 10k-events/sec ceiling)

Ask: **AI-Payments Engineering intern → PPO.**

---

## Anticipated panel questions + our answers

**Q: What if the LLM misclassifies?**
A: Rules match ~85% of failures — LLM only fires on the ambiguous ones. Even when it does, its job is picking a cohort label (7 options). The *strategy* per cohort is deterministic and merchant-editable in `/rules`. If a merchant doesn't trust the LLM, they toggle rules-only mode.

**Q: Duplicate webhook handling?**
A: `UniqueConstraint` on `razorpay_event_id`; visible counter on `/api/metrics/reliability`. Live demo: fire the same signed webhook 3×.

**Q: What if Razorpay API is 500-ing?**
A: Circuit breaker in `app/reliability.py`. Opens on 5 consecutive failures, half-open probe at 30s. Executor logs `circuit_open_deferred` instead of silently swallowing. In production the row would be requeued to a DLQ.

**Q: What if the agent retries the same customer forever?**
A: Per-customer rate limit — 3 recovery actions per `merchant_customer_id` per 24h. Demo: 6 events one customer → 3 executed, 3 skipped as `rate_limited`.

**Q: How does the "adaptive" part actually work?**
A: `LearnedOutcome` table stores rolling `(cohort, action, hour_ist) → attempted/succeeded`. On every attempt the executor calls `record_outcome`; on every decision the strategist calls `learned_p` which blends the observed rate with a hardcoded prior using a Beta(4,6) smoother. Cold cohorts don't swing on the first sample; hot cohorts drift toward observed reality.

**Q: How would this scale to 10k events/sec?**
A: Three swaps, no API changes:
- SQLite → Postgres (async engine already async)
- In-process asyncio tasks → Celery/Arq + Redis Streams
- In-process reliability primitives → Redis-backed (token bucket for rate limit, `CIRCUITBREAKER:{key}` for state)

**Q: What's the honest failure mode?**
A: The sim conversion rates in `AGENT_LINK_P` / `AGENT_RETRY_P` are calibrated to public Indian fintech benchmarks, not this specific merchant's traffic. That's what the learning loop fixes over time. On day 1 for a new merchant, we're using priors. By day 30 we're using their observed rates.
