"use client";

import { useEffect, useState, useTransition } from "react";
import { AppShell } from "@/components/AppShell";
import { api, type RoiEstimate, type RoiMixRow } from "@/lib/api";
import { inr, pct, cohortLabel } from "@/lib/format";
import { Calculator, TrendingUp } from "lucide-react";

export default function RoiPage() {
  const [failed, setFailed] = useState(5000);
  const [ticket, setTicket] = useState(1200);
  const [subShare, setSubShare] = useState(30);
  const [pending, start] = useTransition();
  const [estimate, setEstimate] = useState<RoiEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = () => {
    setError(null);
    start(async () => {
      try {
        const e = await api.roiEstimate({
          monthly_failed_txns: failed,
          avg_ticket_rupees: ticket,
          subscription_share_pct: subShare,
        });
        setEstimate(e);
      } catch (err: any) {
        setError(err?.message ?? "failed");
      }
    });
  };

  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">ROI calculator</h1>
        <p className="mt-1 text-sm text-muted">
          What Recoup would save you at your volume. Rates come from observed
          benchmark runs when there's enough data; seed defaults otherwise.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-1">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium">
            <Calculator className="h-4 w-4 text-accent" /> Inputs
          </div>
          <Field label="Monthly failed payment attempts" value={failed} setter={setFailed} min={1} max={1_000_000} />
          <Field label="Average ticket size (₹)" value={ticket} setter={setTicket} min={1} max={1_000_000} />
          <Field label="Subscription share (%)" value={subShare} setter={setSubShare} min={0} max={100} />
          <button
            onClick={run}
            disabled={pending}
            className="mt-4 w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
          >
            {pending ? "Estimating…" : "Estimate"}
          </button>
          {error && <div className="mt-3 text-xs text-red-400">{error}</div>}
          <p className="mt-4 text-xs text-muted">
            The subscription share applies a ~3× annual weighting on the recovered
            portion — subscription revenue compounds if you save the customer.
          </p>
        </div>

        <div className="lg:col-span-2 space-y-6">
          {estimate ? <ResultCards e={estimate} /> : <div className="card p-8 text-sm text-muted">Enter your numbers and hit Estimate.</div>}
          {estimate && <MixTable rows={estimate.mix_used} />}
        </div>
      </div>
    </AppShell>
  );
}

function Field({
  label, value, setter, min, max,
}: { label: string; value: number; setter: (n: number) => void; min: number; max: number }) {
  return (
    <label className="mb-3 block">
      <div className="mb-1 text-xs uppercase tracking-wider text-muted">{label}</div>
      <input
        type="number" min={min} max={max}
        value={value}
        onChange={(e) => setter(Number(e.target.value) || 0)}
        className="w-full rounded-md border border-border bg-panel px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

function ResultCards({ e }: { e: RoiEstimate }) {
  const m = e.monthly;
  const a = e.annual;
  const items = [
    { label: "Extra ₹ recovered / month", value: inr(m.lift_paise), sub: `vs naive baseline (${pct(e.rates.naive_weighted)} recovery)`, accent: true },
    { label: "Extra ₹ recovered / year", value: inr(a.lift_paise), sub: `agent weighted rate ${pct(e.rates.agent_weighted)}` },
    { label: "Gateway fees saved / year", value: inr(a.fees_saved_paise), sub: "attempts avoided on doomed retries" },
    { label: "Agent recovery / month", value: inr(m.agent_recovered_paise), sub: `of ${inr(m.eligible_paise)} eligible` },
  ];
  return (
    <div className="grid grid-cols-2 gap-4">
      {items.map((it) => (
        <div key={it.label} className="card p-5">
          <div className="text-xs uppercase tracking-wider text-muted">{it.label}</div>
          <div className={`money mt-2 text-2xl font-semibold ${it.accent ? "text-accent" : ""}`}>{it.value}</div>
          <div className="mt-1 text-xs text-muted">{it.sub}</div>
        </div>
      ))}
      <div className="card p-4 col-span-2 flex items-center gap-2 text-sm text-good">
        <TrendingUp className="h-4 w-4" />
        <span>
          On {inr(m.eligible_paise)}/mo of failed payments, Recoup delivers
          <span className="text-text font-medium"> {inr(a.lift_paise)}</span> in
          annualised recovered revenue plus{" "}
          <span className="text-text font-medium">{inr(a.fees_saved_paise)}</span> in
          gateway fee savings.
        </span>
      </div>
    </div>
  );
}

function MixTable({ rows }: { rows: RoiMixRow[] }) {
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-sm font-medium">Cohort model</div>
        <div className="text-xs text-muted">Recovery rates below drive the estimate</div>
      </div>
      <div className="space-y-1.5 text-xs">
        <div className="grid grid-cols-12 text-muted uppercase tracking-wider">
          <div className="col-span-3">Cohort</div>
          <div className="col-span-2 text-right">Share</div>
          <div className="col-span-3 text-right">Agent recovery</div>
          <div className="col-span-3 text-right">Naive recovery</div>
          <div className="col-span-1 text-right">Source</div>
        </div>
        {rows.map((r) => (
          <div key={r.cohort} className="grid grid-cols-12 py-1">
            <div className="col-span-3 text-sm">{cohortLabel(r.cohort)}</div>
            <div className="col-span-2 text-right money">{pct(r.share)}</div>
            <div className="col-span-3 text-right money text-good">{pct(r.agent_recovery_rate)}</div>
            <div className="col-span-3 text-right money text-muted">{pct(r.naive_recovery_rate)}</div>
            <div className="col-span-1 text-right">
              <span className={`pill ${r.sourced_from === "observed" ? "text-good" : "text-muted"}`}>
                {r.sourced_from}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
