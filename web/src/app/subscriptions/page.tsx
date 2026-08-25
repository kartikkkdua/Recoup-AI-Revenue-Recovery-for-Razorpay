import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { cohortLabel, inr, pct, relTime } from "@/lib/format";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState } from "@/components/ErrorState";

export const dynamic = "force-dynamic";

export default async function SubscriptionsPage() {
  try {
    const [summary, list] = await Promise.all([
      api.subscriptionSummary(),
      api.subscriptionList(50),
    ]);
    const c = summary.counts;
    const items = [
      { label: "MRR retained (this window)", value: inr(summary.mrr_retained_paise), sub: `of ${inr(summary.mrr_at_risk_paise)} at risk`, accent: true },
      { label: "Retention rate", value: pct(summary.retention_rate), sub: `${c.recovered} recovered · ${c.churned} churned` },
      { label: "Annualised MRR retained", value: inr(summary.annualised_mrr_retained_paise), sub: "recovered × 12 months" },
      { label: "In-flight", value: String(c.in_flight), sub: "awaiting customer action" },
    ];
    return (
      <AppShell>
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Subscriptions</h1>
          <p className="text-sm text-muted">
            MRR retention view — a recovered subscription payment saves the
            remaining year of billing, so this is the highest-value slice.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {items.map((it) => (
            <div key={it.label} className="card p-5">
              <div className="text-xs uppercase tracking-wider text-muted">{it.label}</div>
              <div className={`money mt-2 text-2xl font-semibold ${it.accent ? "text-accent" : ""}`}>{it.value}</div>
              <div className="mt-1 text-xs text-muted">{it.sub}</div>
            </div>
          ))}
        </div>

        <div className="mt-8 card p-5">
          <div className="mb-3 flex items-baseline justify-between">
            <div className="text-sm font-medium">Recent subscription recoveries</div>
            <div className="text-xs text-muted">Last {list.items.length}</div>
          </div>
          {list.items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted">
              No subscription recoveries yet. Run the simulator on the dashboard;
              ~30% of injected failures now come tagged as subscription events.
            </div>
          ) : (
            <div className="divide-y divide-border">
              <div className="grid grid-cols-12 py-2 text-xs uppercase tracking-wider text-muted">
                <div className="col-span-3">Subscription</div>
                <div className="col-span-2">Cohort</div>
                <div className="col-span-2 text-right">Amount</div>
                <div className="col-span-2 text-right">Recovered</div>
                <div className="col-span-2">Status</div>
                <div className="col-span-1 text-right">When</div>
              </div>
              {list.items.map((r) => (
                <Link key={r.id} href={`/recoveries/${r.id}`}
                      className="grid grid-cols-12 py-3 items-center text-sm hover:bg-white/5">
                  <div className="col-span-3 font-mono text-xs text-muted truncate pr-2">{r.subscription_id}</div>
                  <div className="col-span-2">{cohortLabel(r.cohort)}</div>
                  <div className="col-span-2 text-right money">{inr(r.amount_paise)}</div>
                  <div className="col-span-2 text-right money text-good">{r.recovered_paise > 0 ? inr(r.recovered_paise) : "—"}</div>
                  <div className="col-span-2"><StatusBadge status={r.status} /></div>
                  <div className="col-span-1 text-right text-xs text-muted">{relTime(r.created_at)}</div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </AppShell>
    );
  } catch {
    return <AppShell><ErrorState message="Backend not reachable." /></AppShell>;
  }
}
