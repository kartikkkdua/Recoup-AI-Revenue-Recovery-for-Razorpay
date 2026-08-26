# Deploy — Render (backend) + Vercel (frontend)

Free tiers on both. Total setup time: **~15 minutes**. What you'll get:

- Backend on `https://recoup-api.onrender.com` (or your custom subdomain)
- Frontend on `https://recoup-<something>.vercel.app`
- Managed Postgres (Render free tier, 90-day retention)
- Stable HTTPS URLs — no more re-registering Razorpay webhooks every time cloudflared restarts

---

## 1. Backend — Render (5 min)

Prereqs: GitHub account signed into Render (`render.com`), the repo pushed to `github.com/kartikkkdua/Recoup-AI-Revenue-Recovery-for-Razorpay`.

### 1a. Create the Blueprint

1. Render dashboard → **New +** → **Blueprint**
2. Connect your GitHub → pick `Recoup-AI-Revenue-Recovery-for-Razorpay`
3. Render auto-detects `api/render.yaml` → **Apply**
4. Wait ~3 min for first build + Postgres provisioning

### 1b. Set the secret env vars

Render will prompt for these on first apply (or set them under the service → Environment):

| Key | Value |
|---|---|
| `RAZORPAY_KEY_ID` | your `rzp_test_...` |
| `RAZORPAY_KEY_SECRET` | (from Razorpay dashboard) |
| `RAZORPAY_WEBHOOK_SECRET` | any strong random string; you'll paste it into Razorpay in step 3 |
| `GEMINI_API_KEY` | your Google AI Studio key |

`DATABASE_URL` is wired automatically from the managed Postgres. `CORS_ORIGIN` you'll update after step 2.

### 1c. Verify

Once the service is Live, open:

```
https://recoup-api.onrender.com/health
```

Should return `{"ok": true}`. If yes → backend is deployed.

**Free tier caveat:** Render's free web services **spin down after 15 min of inactivity** and take ~30s to cold-start on the next request. For your panel demo, hit `/health` once ~1 min before showing the dashboard.

---

## 2. Frontend — Vercel (5 min)

Prereqs: Vercel account signed into GitHub.

### 2a. Import

1. `vercel.com/new` → pick the repo → **Import**
2. **Root Directory**: click Edit → set to `web`
3. Framework: Next.js (auto-detected)
4. **Environment Variables** — add just one:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://recoup-api.onrender.com` (from step 1) |

5. **Deploy**. Wait ~90 seconds.

### 2b. Get your Vercel URL + wire it back to the backend

After deploy, Vercel shows a URL like `https://recoup-abc123.vercel.app`. Copy it.

Back in **Render** → service → **Environment** → change `CORS_ORIGIN` to your Vercel URL. Save (triggers a redeploy).

### 2c. Verify

Open your Vercel URL in the browser. Landing page loads. Click Dashboard — headline metrics show. If yes → frontend is deployed and talking to backend.

---

## 3. Point Razorpay webhooks at the deployed backend

Razorpay Dashboard → Settings → Webhooks → edit your webhook:

- **URL**: `https://recoup-api.onrender.com/webhooks`
- **Secret**: whatever you set as `RAZORPAY_WEBHOOK_SECRET` in step 1b
- **Active Events** (at minimum): `payment.failed`, `payment.captured`, `payment_link.paid`, `subscription.charged.failed`, `subscription.halted`, `refund.processed`

Save. Fire a Test Webhook from the row → refresh Vercel dashboard → new recovery appears.

---

## 4. Seed the deployed instance with a benchmark

Free-tier Postgres starts empty. Hit these once against the live backend:

```bash
API=https://recoup-api.onrender.com
curl -X POST $API/api/simulator/benchmark -H 'content-type: application/json' -d '{"count": 400, "concurrency": 8}'

# wait ~15s for background tasks to complete

curl -X POST "$API/api/uplift/train?threshold=0.05"
curl -X POST "$API/api/conformal/calibrate?alpha=0.05"
```

Now your Vercel dashboard shows real numbers, uplift is trained, conformal intervals live.

---

## 5. Final URL checklist

After all four steps:

- ☐ `https://recoup-api.onrender.com/health` → `{"ok": true}`
- ☐ `https://recoup-api.onrender.com/metrics` → Prometheus text output
- ☐ `https://recoup-<yours>.vercel.app/` → landing page with live numbers
- ☐ `https://recoup-<yours>.vercel.app/dashboard` → headline + comparison + live SSE ticker
- ☐ `https://recoup-<yours>.vercel.app/impact` → causal ATE + CATE slices
- ☐ `https://recoup-<yours>.vercel.app/roi` → interactive calculator
- ☐ Razorpay webhook URL updated + Test Webhook succeeds

That's it. Put the Vercel URL on the submission form. It stays live for months on the free tier — the panel can click it any time.

---

## Cost

- Render free tier: **$0/mo**. Spins down when idle, cold-starts on first request.
- Render Postgres free: **$0/mo**, expires after 90 days (re-provision then).
- Vercel Hobby: **$0/mo** on personal use, unlimited-ish traffic for a hackathon.

Total ongoing: **$0**.

---

## If you want no cold starts (recommended for the panel week)

Upgrade the Render web service to **Starter ($7/mo)** for a week while panels are actively reviewing. No cold starts, no 15-min idle spin-down. Downgrade back to free after the offer decision. This one $7 avoids the "let me refresh… still loading…" moment that tanks demos.

---

## Troubleshooting

**Backend deploy fails on `pip install`:** Render's build log will show it. Almost always missing a system package for a wheel. Add a `build.sh` or check the log — for our current requirements, sklearn + numpy + opentelemetry + asyncpg + fastapi + sqlalchemy all have prebuilt wheels for Python 3.13 on Linux, no compilation needed.

**Vercel build fails on TypeScript strict:** `web/tsconfig.json` compilation error. Run `npm run build` locally first to see the error and fix.

**CORS error in browser:** `CORS_ORIGIN` on Render doesn't match your Vercel URL. Update + redeploy.

**Dashboard says "Backend not reachable":** `NEXT_PUBLIC_API_URL` was set at build time to the wrong URL. Redeploy Vercel with the correct value.

**Razorpay webhook returns 401:** `RAZORPAY_WEBHOOK_SECRET` in Render doesn't match what you set in Razorpay dashboard.
