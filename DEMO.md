# Demo video — record it in 30 minutes

**Deliverable:** a 90-second unlisted YouTube / Loom link you paste into the submission form.

**Reality check:** the video is the first (often only) thing 90% of reviewers watch. It matters more than any additional feature you could ship. One take reasonably done beats ten polished takes.

---

## Timing (30 min end to end)

| Minutes | Task |
|---|---|
| 0–5 | Prep — kill zombie tabs, run the pre-flight, seed the DB |
| 5–10 | Setup — QuickTime, resolution, mic test |
| 10–20 | Record 3 takes back to back |
| 20–25 | Pick the best take, minimal trim in QuickTime |
| 25–30 | Upload to YouTube unlisted, paste link into submission form |

---

## 0–5 min · Pre-flight (RUN THIS FIRST)

Open one Terminal. Paste this whole block, hit enter, wait until the last line prints "READY".

```bash
# 1) Kill anything on the demo ports
pkill -f 'uvicorn app.main:app' 2>/dev/null; sleep 2

# 2) Fresh backend
cd /Users/kartikdua/Bulidathon/api
rm -f recoup.db recoup.db-shm recoup.db-wal
source .venv/bin/activate
/usr/bin/nohup uvicorn app.main:app --host 127.0.0.1 --port 8080 > /tmp/uvicorn.log 2>&1 </dev/null &
disown; sleep 3

# 3) Frontend (skip if already running on :3000)
lsof -tiTCP:3000 -sTCP:LISTEN >/dev/null 2>&1 || (
  cd /Users/kartikdua/Bulidathon/web
  /usr/bin/nohup npm run dev > /tmp/next.log 2>&1 </dev/null &
  disown; sleep 8
)

# 4) Seed data + train ML so the dashboard is populated
API=http://localhost:8080
curl -s -X POST $API/api/simulator/benchmark -H 'content-type: application/json' -d '{"count":400,"concurrency":8}' >/dev/null
until [ "$(curl -s $API/api/metrics/compare | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["agent"]["counts"]["total"]+d["naive"]["counts"]["total"])')" -ge 780 ]; do sleep 1; done
curl -s -X POST "$API/api/uplift/train?threshold=0.05" >/dev/null
curl -s -X POST "$API/api/conformal/calibrate?alpha=0.05" >/dev/null

echo "READY — open http://localhost:3000 in Chrome"
```

Also open a **second terminal** to have ready for the live one-liner in Beat 5.

---

## 5–10 min · Setup

- **Browser:** Chrome, **one tab**, no dev tools, no bookmarks bar (Cmd-Shift-B)
- **Screen resolution:** if on retina MacBook, don't zoom — full res
- **QuickTime:** `Cmd-Shift-5` → **Record Selected Portion** → drag box around **just the browser window** (not the whole desktop). Save to Desktop.
- **Mic test:** say "one two three" — QuickTime shows the level. Not maxed, not dead.
- **Kill notifications:** System Settings → Focus → Do Not Disturb ON

---

## 10–20 min · Record (3 takes)

Follow the 7-beat script below. **Don't memorize** — read it once, close this file, record from short-term memory. Small stumbles read as authentic.

Aim for **~90 seconds**. Don't obsess about being 89 vs 92 — just don't go over 2 minutes.

---

## The 7-beat script

### Beat 1 — the promise (0:00 → 0:12)
**Show:** landing page `/`
**Say:**
> "Recoup is an agent that watches a Razorpay merchant's failed payments and recovers the ones that shouldn't have failed. Deterministic rules classify. A contextual bandit picks strategy. A T-learner uplift model gates intervention. Every step is logged and reversible."

### Beat 2 — the counterfactual (0:12 → 0:28)
**Show:** click Dashboard → scroll to ComparisonPanel
**Point at:** the ₹ lift + attempts saved chip
**Say:**
> "Same failure stream. Naive retry gets 2.4L rupees. Our agent gets 8L — three point two times more revenue with 55% fewer calls to Razorpay's API."

### Beat 3 — the cohorts (0:28 → 0:42)
**Show:** scroll to cohort table
**Say:**
> "The story is per-cohort. On insufficient funds, naive gets one percent; we get 79 — because we send a WhatsApp nudge and retry on payday. On expired auth, a re-tokenization link. On card declined, we switch the rail from card to UPI. Anyone can retry more. Knowing when *not* to retry is what wins."

### Beat 4 — the causal impact page (0:42 → 0:55) — **NEW, this is your differentiator**
**Show:** click **Causal Impact** in the nav (or type `/impact`)
**Point at:** the stratified ATE + significant slices with checkmarks
**Say:**
> "We don't just report raw numbers. This is the doubly-robust AIPW estimate: plus 41 percentage points causal lift with a 95% confidence interval that excludes zero. Per-slice CATE shows exactly where the agent's incremental effect is statistically significant — and where it isn't. That's the difference between 'we recover more' and 'we cause more recoveries.'"

### Beat 5 — reliability, live in a terminal (0:55 → 1:10)
**Show:** switch to your prepared second terminal → paste this one-liner:
```bash
python3 - <<'PY'
import hmac,hashlib,json,urllib.request
S="TcmXa7e8Lpqj4udyqZ_pEUeUj0mPPQ0Kp_sJRz8WIU4"
p={"id":"evt_demo_live","event":"payment.failed","contains":["payment"],
   "simulated":True,"payload":{"payment":{"entity":{
   "id":"pay_demo","order_id":"o_demo","amount":49900,"currency":"INR",
   "status":"failed","method":"upi","error_code":"GATEWAY_ERROR",
   "error_reason":"bank_error","error_description":"bank down",
   "notes":{"customer_id":"cust_demo"}}}}}
b=json.dumps(p).encode()
sig=hmac.new(S.encode(),b,hashlib.sha256).hexdigest()
for i in range(3):
    print(urllib.request.urlopen(urllib.request.Request(
      "http://localhost:8080/webhooks",data=b,
      headers={"content-type":"application/json","x-razorpay-signature":sig})).read().decode())
PY
```
**Let the 3 responses stay on screen for 3 full seconds.**
**Say:**
> "Same signed webhook fired three times. Accepted, duplicate, duplicate. Idempotent by event ID. No double recovery. Rate-limited per customer. Circuit-broken on the Razorpay client."

### Beat 6 — "why we did this" on one recovery (1:10 → 1:25)
**Show:** back to browser → Recoveries → click any RECOVERED row
**Point at:** the "Why we did this" card
**Say:**
> "Every recovery has this. Classification reasoning. Bandit context and sampled probability. Semantic memory hits from similar past successes. Uplift model's individual treatment effect. Zero black box on the money path."

### Beat 7 — the close (1:25 → 1:32)
**Show:** back to dashboard
**Say:**
> "Recoup. AI Revenue Recovery track. Real Razorpay integration, 66 tests, doubly-robust causal inference, contextual bandits, conformal uplift intervals. Repo and README in the submission."

**Stop recording.**

---

## 20–25 min · Trim

QuickTime → Edit → Trim → cut the first 1s (mouse pickup) and the last 1s. Save as `recoup-demo.mp4`.

Don't add music. Don't add a lower-third. Naked video reads as engineering-competent; polish reads as marketing-fluff.

---

## 25–30 min · Upload

**YouTube (recommended):**
1. youtube.com → upload → drag `recoup-demo.mp4`
2. Title: `Recoup — AI Revenue Recovery for Razorpay (Buildathon 2026 submission)`
3. Description: paste your GitHub URL + one-line pitch
4. Visibility: **Unlisted** (not private — reviewers can't see private)
5. Copy the link → paste into the submission form

**Loom** works too if you'd rather. Same visibility rule: link-shareable, not private.

---

## Common mistakes that tank the video

1. **Don't zoom into code.** Show the product, not the editor. Panels want to see it work, not read your Python.
2. **Don't apologize for sandbox data.** State it once ("400 synthetic failures") and move on.
3. **Don't rush Beat 5.** The three-response terminal output needs a full 3 seconds on screen for the reviewer's eye to catch "accepted → duplicate → duplicate."
4. **Don't add background music.** Silence + your voice > any track.
5. **Don't rehearse it 20 times.** By take 4 you sound like a memorized script. Take 2 or 3 is usually the sweet spot.
6. **Don't record with dev tools open.** Distracting and screams amateur.

---

## If you're going long

Cuts in order of what to lose first:

1. Beat 6 (Why we did this) — trim to 5 seconds
2. Beat 7's verbal list — just show the dashboard for 3 seconds
3. Middle sentence of Beat 3 — the auth/card bullets are already on the slide deck

## If you're going short

Extend Beat 4 (Causal Impact) — the AIPW confidence interval is the single most credibility-buying visual. Sit on that page for an extra 5 seconds.

---

## After the video is uploaded

Send yourself a Slack/message with:
- YouTube link
- Vercel URL (once deployed)
- GitHub URL: https://github.com/kartikkkdua/Recoup-AI-Revenue-Recovery-for-Razorpay

Those three go on the submission form. That's your submission.
