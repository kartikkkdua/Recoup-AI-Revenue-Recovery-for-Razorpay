# Demo script — 90-second walkthrough

**Recording tool suggestions:** QuickTime Screen Recording (Cmd-Shift-5,
"Record Selected Portion"), or Loom. Aim for 1080p, ≤ 90 seconds. Voice-over
is optional but doubles the impact — panels watch on mute otherwise.

**Before you hit record**

1. Backend running: `cd api && source .venv/bin/activate && uvicorn app.main:app --port 8080`
2. Frontend running: `cd web && npm run dev`
3. Fresh database (so the numbers are clean):
   ```bash
   rm api/recoup.db*
   # restart uvicorn, then:
   curl -X POST http://localhost:8080/api/simulator/benchmark \
     -H 'content-type: application/json' \
     -d '{"count": 400, "concurrency": 48}'
   # wait ~2 minutes for the benchmark to complete
   ```
4. Browser open at `http://localhost:3000/dashboard` — full-screen, dev
   tools closed, one tab.
5. A second terminal open, showing the repo root — for the "duplicate
   defense" moment.

---

## Shot list (90 seconds, seven beats)

### Beat 1 — the promise (0:00 → 0:10)
**Show:** dashboard `/dashboard`, headline row visible.
**Say:** "Recoup is an agent that watches a Razorpay merchant's failed
payments and recovers the ones that shouldn't have failed."
**Point at:** the ₹ Recovered number.

### Beat 2 — the counterfactual (0:10 → 0:25)
**Show:** scroll to the ComparisonPanel.
**Say:** "Same failure stream. Naive retry recovers ₹2.4L. Our agent
recovers ₹5.98L. Three-point-two times more revenue, with fifty-five
percent fewer calls to Razorpay's API."
**Point at:** the delta chip `+₹3.6L` and the "attempts avoided" line
underneath.

### Beat 3 — the cohorts (0:25 → 0:40)
**Show:** scroll to the cohort chart below.
**Say:** "The story is per-cohort. On `insufficient_funds`, naive gets one
percent; we get seventy-nine — because we send a WhatsApp nudge and retry
on payday. On `auth_expired`, we send a re-tokenization link. On
`card_declined`, we switch the rail to UPI. Anyone can retry more. Knowing
when *not* to retry is what wins."

### Beat 4 — the reliability strip (0:40 → 0:55)
**Show:** scroll up to the ReliabilityStrip.
**Say:** "This is what earns a payments company's trust: idempotent by
event ID, rate-limited per customer per 24 hours, circuit-broken on the
Razorpay client. Every gate is visible, every skip is auditable."

### Beat 5 — duplicate defense, live (0:55 → 1:10)
**Show:** switch to terminal, run this one-liner (paste as a single
command, replace the SECRET if you rotated it):
```bash
python3 - <<'PY'
import hmac,hashlib,json,urllib.request
S="TcmXa7e8Lpqj4udyqZ_pEUeUj0mPPQ0Kp_sJRz8WIU4"
p={"id":"evt_demo_live","event":"payment.failed","contains":["payment"],
   "simulated":True,"payload":{"payment":{"entity":{
    "id":"pay_demo","order_id":"order_demo","amount":49900,"currency":"INR",
    "status":"failed","method":"upi","error_code":"GATEWAY_ERROR",
    "error_reason":"bank_error","error_description":"bank down",
    "notes":{"customer_id":"cust_demo"}}}}}
b=json.dumps(p).encode();sig=hmac.new(S.encode(),b,hashlib.sha256).hexdigest()
for i in range(3):
    r=urllib.request.urlopen(urllib.request.Request(
      "http://localhost:8080/webhooks",data=b,
      headers={"content-type":"application/json","x-razorpay-signature":sig}))
    print(r.read().decode())
PY
```
**Say:** "Same signed webhook fired three times." *(let them read the
output: `accepted → duplicate → duplicate`)* "The dedup counter ticks;
no double recovery row created."

### Beat 6 — the "why" on a single recovery (1:10 → 1:25)
**Show:** click any recovery in the recent list → `/recoveries/{id}` page.
**Point at:** the "Why we did this" card.
**Say:** "Every recovery has this card. It shows the classification
reasoning, the blended learned-vs-prior probability we used, and any gate
that triggered. Zero black-box decisions on a money path."

### Beat 7 — the close (1:25 → 1:30)
**Show:** dashboard again.
**Say:** "Recoup. Built for the AI Revenue Recovery track. Repo and README
in the submission."

---

## Voice-over final script (paste into your notes app)

> Recoup is an agent that watches a Razorpay merchant's failed payments and
> recovers the ones that shouldn't have failed.
>
> Same failure stream — naive retry recovers ₹2.4L; our agent recovers
> ₹5.98L. Three-point-two times more revenue with fifty-five percent fewer
> Razorpay API calls.
>
> The story is per-cohort. On insufficient funds, naive gets one percent; we
> get seventy-nine — WhatsApp nudge, payday retry via UPI. On expired auth,
> we send a re-tokenization link. On card declined, we switch the rail to
> UPI. Anyone can retry more. Knowing when *not* to retry is what wins.
>
> This is what earns a payments company's trust: idempotent by event ID,
> rate-limited per customer per twenty-four hours, circuit-broken on the
> Razorpay client. Every gate is visible; every skip is auditable.
>
> Watch — same signed webhook fired three times. Accepted, duplicate,
> duplicate. The dedup counter ticks; no double recovery row.
>
> And every recovery has this card. Classification reasoning, learned-vs-
> prior probability, any gate that triggered. Zero black boxes on a money
> path.
>
> Recoup. AI Revenue Recovery track. Repo and README in the submission.

---

## Common recording mistakes to avoid

- **Don't zoom into code.** Keep the whole dashboard visible; the panel
  wants to see the product, not your text editor.
- **Don't apologize for the sandbox data.** State it once ("400 synthetic
  failures, both strategies") and move on.
- **Don't scroll the terminal too fast.** In beat 5, let the three
  responses stay on screen for a full 3 seconds.
- **Don't add music.** Reads as amateur. Silence + voice > any track.
- **Don't rehearse a script word-for-word on camera.** Read it, close it,
  record from memory. Small stumbles read as authentic.
- **One take is fine.** Panels can tell when something was cut 20 times.

---

## If you're going long

You have three obvious cuts, in order of what to lose first:

1. **Beat 6 (the "why" card)** — visible on the dashboard walkthrough
   already; you can trim this to 5 seconds.
2. **The verbal recap in Beat 7** — just show the dashboard for 3 seconds
   with the ₹ number and let it breathe.
3. **The middle sentence of Beat 3** — the auth_expired / card_declined
   bullets are already on Slide 3 of the deck.

If you're going *short*, extend Beat 2 — the counterfactual is the single
strongest moment. Sit on that panel for an extra 5 seconds.
