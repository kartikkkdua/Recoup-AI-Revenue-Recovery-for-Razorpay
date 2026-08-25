import type { Summary } from "@/lib/api";
import { inr, pct } from "@/lib/format";

export function HeadlineMetrics({ summary }: { summary: Summary }) {
  const items = [
    {
      label: "₹ Recovered",
      value: inr(summary.recovered_amount_paise),
      sub: `of ${inr(summary.total_amount_paise)} eligible`,
      accent: true,
    },
    {
      label: "Recovery rate",
      value: pct(summary.recovery_rate),
      sub: `${summary.counts.recovered} of ${summary.counts.total} txns`,
    },
    {
      label: "Attempts spent",
      value: (summary.attempts_total ?? 0).toLocaleString("en-IN"),
      sub: `${summary.counts.skipped} skipped (not retryable)`,
    },
    {
      label: "Gateway fees",
      value: inr(summary.gateway_fees_paise ?? 0),
      sub: "retries + payment links + nudges",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {items.map((it) => (
        <div key={it.label} className="card p-5">
          <div className="text-xs uppercase tracking-wider text-muted">{it.label}</div>
          <div className={`money mt-2 text-3xl font-semibold ${it.accent ? "text-accent" : ""}`}>
            {it.value}
          </div>
          <div className="mt-1 text-xs text-muted">{it.sub}</div>
        </div>
      ))}
    </div>
  );
}
