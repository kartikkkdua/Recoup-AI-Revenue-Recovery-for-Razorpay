import type { DecisionContext } from "@/lib/api";
import { cohortLabel, pct } from "@/lib/format";

export function DecisionExplain({ ctx }: { ctx: DecisionContext }) {
  if (!ctx.classification) return null;
  const c = ctx.classification;
  const p = ctx.probability;
  const gate = ctx.gate_triggered;

  return (
    <div className="card p-5">
      <div className="text-xs uppercase tracking-wider text-muted">Why we did this</div>
      <div className="mt-3 space-y-2 text-sm leading-6">
        <Line>
          Classified as <b>{cohortLabel(c.cohort)}</b> by <span className="pill">{c.reasoning}</span>
          {" "}(confidence {pct(c.confidence, 0)}).
        </Line>
        {ctx.strategy_reason && (
          <Line>
            Playbook: <span className="text-text">{ctx.strategy_reason}</span>
          </Line>
        )}
        {p && (
          <Line>
            Expected recovery <b>{pct(p.learned_blended ?? p.prior ?? 0)}</b>
            {typeof p.observed_attempts === "number" && p.observed_attempts > 0 ? (
              <>
                {" "}(learned from {p.observed_attempts} prior attempts in this hour ·
                observed {pct(p.observed_p ?? 0)},
                prior {pct(p.prior ?? 0)})
              </>
            ) : (
              <> (cold start — using prior; no learned observations yet in this hour)</>
            )}.
          </Line>
        )}
        {gate && (
          <Line>
            <span className="pill text-yellow-400">gate: {gate.step}</span>{" "}
            {typeof gate.defer_hours === "number" && <>Deferred by {gate.defer_hours}h.</>}
            {gate.reason ? <> {String(gate.reason)}</> : null}
          </Line>
        )}
        {ctx.ml && (
          <div className="mt-3 border-t border-border pt-3">
            <div className="text-xs uppercase tracking-wider text-muted mb-2">
              ML pipeline — contextual bandit + semantic memory
            </div>
            <Line>
              <span className="pill text-accent">bandit</span>{" "}
              Sampled <b>{ctx.ml.bandit_chosen}</b> at p={pct(ctx.ml.bandit_sampled_p)}
              {" "}for context ({ctx.ml.bandit_context.ticket_bucket} ticket ·
              {" "}{ctx.ml.bandit_context.hour_bucket} IST).
            </Line>
            <Line>
              <span className="pill">features</span>{" "}
              LTV ₹{(ctx.ml.features.customer_ltv_paise / 100).toLocaleString("en-IN")} ·
              {" "}streak {ctx.ml.features.customer_failure_streak} ·
              {" "}preferred rail: <span className="text-text">{ctx.ml.features.customer_preferred_rail ?? "—"}</span> ·
              {" "}cohort 24h rate {pct(ctx.ml.features.cohort_recent_recovery_rate)}
            </Line>
            {ctx.ml.memory_hits > 0 && (
              <Line>
                <span className="pill text-good">memory</span>{" "}
                Retrieved <b>{ctx.ml.memory_hits}</b> similar past successes ·
                {" "}top action votes:{" "}
                {Object.entries(ctx.ml.memory_action_scores)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 2)
                  .map(([a, s]) => `${a} (${pct(s)})`).join(", ")}
              </Line>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Line({ children }: { children: React.ReactNode }) {
  return <div className="text-muted">{children}</div>;
}
