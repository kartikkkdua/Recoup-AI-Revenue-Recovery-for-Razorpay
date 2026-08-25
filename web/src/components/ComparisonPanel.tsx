import type { Compare } from "@/lib/api";
import { inr, inrExact, pct } from "@/lib/format";

export function ComparisonPanel({ compare }: { compare: Compare }) {
  const { agent, naive, lift } = compare;
  const naiveExists = naive.counts.total > 0;

  return (
    <div className="card p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <div>
          <div className="text-sm font-medium">Agent vs naive baseline</div>
          <div className="text-xs text-muted">
            Same failures, both strategies. Naive = retry everything 3× on the same rail.
          </div>
        </div>
      </div>

      {!naiveExists ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">
          Run a benchmark to see the head-to-head. Both modes run on the same synthetic failures.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <MetricCol label="Recovery rate" agent={pct(agent.recovery_rate)} naive={pct(naive.recovery_rate)} delta={`+${pct(lift.recovery_rate_delta)}`} good />
            <MetricCol label="₹ Recovered" agent={inr(agent.recovered_amount_paise)} naive={inr(naive.recovered_amount_paise)} delta={`+${inr(lift.extra_recovered_paise)}`} good />
            <MetricCol label="Gateway fees" agent={inr(agent.gateway_fees_paise)} naive={inr(naive.gateway_fees_paise)} delta={`−${inr(lift.fees_saved_paise)}`} good />
          </div>
          <div className="mt-5 rounded-md border border-border bg-panel/50 p-3 text-xs text-muted">
            <span className="text-text font-medium">Attempts avoided: {lift.attempts_saved.toLocaleString("en-IN")}.</span>{" "}
            The agent skipped doomed retries on <em>insufficient_funds</em>, <em>risk_declined</em>, and
            expired-auth cohorts — routing them to dunning, tokenization, or human review instead.
          </div>
        </>
      )}
    </div>
  );
}

function MetricCol({
  label, agent, naive, delta, good,
}: { label: string; agent: string; naive: string; delta: string; good?: boolean }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 flex items-baseline gap-3">
        <div className="money text-2xl font-semibold text-accent">{agent}</div>
        <div className={`text-xs ${good ? "text-good" : "text-muted"}`}>{delta}</div>
      </div>
      <div className="mt-0.5 text-xs text-muted">
        naive: <span className="money text-text">{naive}</span>
      </div>
    </div>
  );
}
