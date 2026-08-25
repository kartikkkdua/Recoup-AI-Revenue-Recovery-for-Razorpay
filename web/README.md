# Recoup Web

Next.js 14 App Router product — marketing, dashboard, recoveries, rules, settings.

## Run

```bash
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The dashboard hits the FastAPI backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## Pages

- `/` — landing / pitch
- `/dashboard` — headline metrics, cohort table, recent recoveries, simulator button
- `/recoveries` — filterable feed of every recovery
- `/recoveries/[id]` — full agent audit trail per recovery
- `/rules` — retry rules per failure cohort
- `/settings` — Razorpay webhook wiring
